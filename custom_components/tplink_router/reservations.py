"""DHCP reservation helpers (table capacity, verified writes, in-place update).

tplinkrouterc6u >= the release with ``get_ipv4_reservations_info`` /
``update_ipv4_reservation`` does all of this natively, and that path is used
when present. For older releases (the pinned one included) the same wire
format is spoken here through the client's own authenticated ``request()``,
so the integration works with the stock library:

* load:   ``operation=load`` -> ``{"data": [rows], "others": {"max_rules": N}}``
* insert: ``operation=insert`` + ``new=<row json>`` (name sent as both
  ``comment`` and ``hostname``; Archer AX1800 stores an empty name otherwise)
* update: ``operation=update`` + ``key``/``new``/``old`` row json (web UI format)
* remove: library ``delete_ipv4_reservation``

Every write is verified by reloading the table, because some firmware
(Archer AX1800 v1.20) answers ``success: true`` without storing anything, e.g.
when the table is full.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from json import dumps
from typing import Any
from urllib.parse import urlencode

from homeassistant.exceptions import HomeAssistantError

from .utils import normalize_mac


class ReservationError(HomeAssistantError):
    """A reservation change was refused or did not persist on the router."""


@dataclass
class ReservationRow:
    mac: str
    ip: str
    name: str
    enabled: bool

    def as_dict(self) -> dict[str, Any]:
        return {"mac": self.mac, "ip": self.ip, "hostname": self.name, "enabled": self.enabled}


@dataclass
class ReservationTable:
    rows: list[ReservationRow] = field(default_factory=list)
    max_rules: int | None = None

    @property
    def used(self) -> int:
        return len(self.rows)

    @property
    def free(self) -> int | None:
        if self.max_rules is None:
            return None
        return max(0, self.max_rules - self.used)

    @property
    def is_full(self) -> bool:
        return self.max_rules is not None and self.used >= self.max_rules

    def find_mac(self, mac: str) -> ReservationRow | None:
        mac = normalize_mac(mac)
        return next((row for row in self.rows if row.mac == mac), None)

    def find_ip(self, ip: str) -> ReservationRow | None:
        return next((row for row in self.rows if row.ip == ip), None)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("on", "1", "true", "yes")


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def has_native_support(router: Any) -> bool:
    """tplinkrouterc6u already verifies writes and exposes the table capacity."""
    return hasattr(router, "get_ipv4_reservations_info") and hasattr(router, "update_ipv4_reservation")


def has_luci_wire_support(router: Any) -> bool:
    """Client speaks the LuCI ``admin/dhcps?form=reservation`` form (Archer C6U family)."""
    return (
        isinstance(getattr(router, "_url_ipv4_reservations", None), str)
        and "form=reservation" in router._url_ipv4_reservations
        and callable(getattr(router, "request", None))
        and callable(getattr(router, "_is_valid_response", None))
    )


def supports_reservations(router: Any) -> bool:
    return hasattr(router, "get_ipv4_reservations")


def supports_update(router: Any) -> bool:
    return has_native_support(router) or has_luci_wire_support(router)


def _path(router: Any) -> str:
    return router._url_ipv4_reservations.split("&operation=")[0]


def _rows_from_raw(data: Any) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if not data:
            return []
        if isinstance(data.get("list"), list):
            return data["list"]
    raise ReservationError(f"Unexpected reservation table payload: {type(data).__name__}")


def _luci_load(router: Any) -> tuple[list[dict], int | None]:
    """Load raw rows plus ``others.max_rules`` through the client's own session.

    ``request()`` returns only the ``data`` block of a valid response; with
    ``ignore_errors`` it returns the whole decrypted envelope for an *invalid*
    one. Treating every response as invalid for this single call yields the
    envelope (rows + ``others``) without re-implementing login/encryption.
    """
    def _never_valid(_data: Any) -> bool:
        return False

    router._is_valid_response = _never_valid
    try:
        envelope = router.request(router._url_ipv4_reservations, "operation=load", ignore_errors=True)
    finally:
        del router._is_valid_response
    if not isinstance(envelope, dict) or not envelope.get("success"):
        raise ReservationError(f"Router refused to load the reservation table: {envelope}")
    others = envelope.get("others") if isinstance(envelope.get("others"), dict) else {}
    return _rows_from_raw(envelope.get("data")), _int_or_none(others.get("max_rules"))


def _row(mac: Any, ip: Any, name: Any, enabled: Any) -> ReservationRow:
    return ReservationRow(normalize_mac(str(mac)), str(ip).strip(), str(name or ""), _bool(enabled))


def fetch_table(router: Any) -> ReservationTable:
    """Read the reservation table (blocking; call inside an authorized session)."""
    if has_native_support(router):
        info = router.get_ipv4_reservations_info()
        return ReservationTable(
            [_row(r.macaddr, r.ipaddr, r.hostname, r.enabled) for r in info.reservations],
            info.max_rules,
        )
    if has_luci_wire_support(router):
        rows, max_rules = _luci_load(router)
        return ReservationTable(
            [_row(r.get("mac", ""), r.get("ip", ""), r.get("comment") or r.get("hostname"), r.get("enable"))
             for r in rows if r.get("mac")],
            max_rules,
        )
    return ReservationTable(
        [_row(r.macaddr, r.ipaddr, r.hostname, r.enabled) for r in router.get_ipv4_reservations()],
        None,
    )


def _check_conflicts(table: ReservationTable, mac: str, ip: str, ignore_mac: str | None = None) -> None:
    other = table.find_mac(mac)
    if other is not None and other.mac != ignore_mac:
        raise ReservationError(f"MAC {mac} already has a reservation ({other.ip})")
    other = table.find_ip(ip)
    if other is not None and other.mac != ignore_mac:
        raise ReservationError(f"IP {ip} is already reserved for {other.mac} ({other.name})")


def add_reservation(router: Any, mac: str, ip: str, comment: str = "", enable: bool = True) -> ReservationRow:
    """Insert a reservation and return the stored row (blocking)."""
    mac = normalize_mac(mac)
    table = fetch_table(router)
    if table.is_full:
        raise ReservationError(f"DHCP reservation table is full ({table.used}/{table.max_rules})")
    _check_conflicts(table, mac, ip)

    if has_native_support(router):
        router.add_ipv4_reservation(mac, ip, comment, enable)
    elif has_luci_wire_support(router):
        new = {"mac": mac, "ip": ip, "comment": comment, "hostname": comment, "enable": "on" if enable else "off"}
        router.request(_path(router), urlencode({"operation": "insert", "new": dumps(new)}))
    else:
        router.add_ipv4_reservation(mac, ip, comment, enable)

    stored = fetch_table(router).find_mac(mac)
    if stored is None or stored.ip != ip:
        raise ReservationError(
            f"Router answered OK but did not store the reservation {mac} -> {ip}"
            + (" (table may be full)" if table.max_rules is None else "")
        )
    return stored


def update_reservation(
    router: Any,
    old_mac: str,
    mac: str | None = None,
    ip: str | None = None,
    comment: str | None = None,
    enable: bool | None = None,
) -> ReservationRow:
    """Edit a reservation in place (router ``update`` operation) and return the stored row."""
    old_mac = normalize_mac(old_mac)
    new_mac = normalize_mac(mac) if mac else old_mac
    table = fetch_table(router)
    current = table.find_mac(old_mac)
    if current is None:
        raise ReservationError(f"No reservation found for MAC {old_mac}")
    new_ip = ip or current.ip
    _check_conflicts(table, new_mac, new_ip, ignore_mac=old_mac)

    if has_native_support(router):
        router.update_ipv4_reservation(old_mac, macaddr=new_mac, ipaddr=new_ip, comment=comment, enable=enable)
    elif has_luci_wire_support(router):
        raw_rows, _ = _luci_load(router)
        target = next((r for r in raw_rows if r.get("mac") and normalize_mac(r["mac"]) == old_mac), None)
        if target is None:
            raise ReservationError(f"No reservation found for MAC {old_mac}")
        new = dict(target)
        if mac:
            new["mac"] = new_mac
        new["ip"] = new_ip
        if comment is not None:
            new["comment"] = comment
            new["hostname"] = comment
        if enable is not None:
            new["enable"] = "on" if enable else "off"
        router.request(_path(router), urlencode({
            "operation": "update",
            "key": target["mac"],
            "new": dumps(new),
            "old": dumps(target),
        }))
    else:
        raise ReservationError("This router does not support editing DHCP reservations")

    after = fetch_table(router)
    stored = after.find_mac(new_mac)
    if (
        stored is None
        or stored.ip != new_ip
        or (enable is not None and stored.enabled != enable)
        or (new_mac != old_mac and after.find_mac(old_mac) is not None)
    ):
        raise ReservationError(f"Router answered OK but did not store the update of reservation {old_mac}")
    return stored


def delete_reservation(router: Any, mac: str) -> None:
    """Remove a reservation and make sure it is gone (blocking)."""
    mac = normalize_mac(mac)
    if fetch_table(router).find_mac(mac) is None:
        raise ReservationError(f"No reservation found for MAC {mac}")
    router.delete_ipv4_reservation(mac)
    if fetch_table(router).find_mac(mac) is not None:
        raise ReservationError(f"Router answered OK but kept the reservation {mac}")


def is_randomized_mac(mac: str | None) -> bool:
    """True for locally administered (privacy/randomized) MAC addresses.

    The locally-administered bit (0x02 of the first octet) is set by phones,
    tablets and laptops that randomize their Wi-Fi MAC per network. QEMU/KVM
    guests (52:54:00) also carry that bit but keep a fixed address, so they are
    not reported as randomized.
    """
    if not mac:
        return False
    try:
        normalized = normalize_mac(mac)
    except ValueError:
        return False
    if normalized.startswith("52-54-00"):
        return False
    return bool(int(normalized[:2], 16) & 0x02)
