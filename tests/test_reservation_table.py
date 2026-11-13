"""Reservation table: capacity, verified writes, in-place update, sensors, services."""
import asyncio
import logging
from json import loads
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qsl

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.tplink_router import (
    UPDATE_RESERVATION_SCHEMA,
    _reservation_coordinator,
)
from custom_components.tplink_router.binary_sensor import TPLinkRouterReservationsNearFullSensor
from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.coordinator import TPLinkRouterCoordinator
from custom_components.tplink_router.reservations import (
    ReservationError,
    ReservationRow,
    ReservationTable,
    add_reservation,
    delete_reservation,
    fetch_table,
    has_luci_wire_support,
    is_randomized_mac,
    update_reservation,
)
from custom_components.tplink_router.sensor import (
    TPLinkRouterReservationsCapacitySensor,
    TPLinkRouterReservationsSensor,
)
from custom_components.tplink_router.utils import normalize_mac


class FakeLuciRouter:
    """Mimics tplinkrouterc6u's TplinkRequest.request() on the reservation form.

    A valid response returns only the "data" block; an invalid one returns the
    whole envelope when ignore_errors is set (that is how the helper reads
    "others.max_rules" with a stock library).
    """

    _url_ipv4_reservations = "admin/dhcps?form=reservation"

    def __init__(self, rows, max_rules=64, drop_writes=False):
        self.table = [dict(r) for r in rows]
        self.max_rules = max_rules
        self.drop_writes = drop_writes
        self.calls = []

    def _is_valid_response(self, data):
        return bool(data.get("success")) and "data" in data

    def request(self, path, data, ignore_response=False, ignore_errors=False):
        self.calls.append((path, data))
        body = dict(parse_qsl(data))
        op = body.get("operation")
        if op == "load":
            envelope = {"success": True, "data": [dict(r) for r in self.table]}
            if self.max_rules is not None:
                envelope["others"] = {"max_rules": self.max_rules}
        else:
            if not self.drop_writes:
                if op == "insert":
                    self.table.append(loads(body["new"]))
                elif op == "update":
                    old = loads(body["old"])
                    self.table = [loads(body["new"]) if r["mac"] == old["mac"] else r for r in self.table]
            envelope = {"success": True, "data": {}}
        if self._is_valid_response(envelope):
            return envelope["data"]
        if ignore_errors:
            return envelope
        raise RuntimeError("error response")

    def get_ipv4_reservations(self):
        raise AssertionError("LuCI path must not use the list-only getter")

    def delete_ipv4_reservation(self, mac):
        self.calls.append(("remove", mac))
        if not self.drop_writes:
            self.table = [r for r in self.table if normalize_mac(r["mac"]) != normalize_mac(mac)]


ROWS = [
    {"mac": "2E-6B-B3-EC-42-40", "ip": "192.168.1.212", "comment": "S24-Ultra", "hostname": "S24-Ultra",
     "enable": "on"},
    {"mac": "80-45-6B-31-C6-68", "ip": "192.168.1.247", "comment": "printer", "hostname": "printer",
     "enable": "on"},
]


def _ops(router):
    return [dict(parse_qsl(d)).get("operation", d) for _, d in router.calls]


def test_normalize_mac_and_randomized_flag():
    assert normalize_mac("aa:60:27:17:8d:45") == "AA-60-27-17-8D-45"
    assert is_randomized_mac("AA-60-27-17-8D-45") is True       # locally administered
    assert is_randomized_mac("80:45:6b:31:c6:68") is False      # vendor OUI
    assert is_randomized_mac("52:54:00:76:4a:92") is False      # QEMU/KVM guest, fixed
    assert is_randomized_mac("") is False
    assert is_randomized_mac("garbage") is False
    with pytest.raises(ValueError):
        normalize_mac("nope")


def test_fetch_table_reads_max_rules_with_stock_library():
    router = FakeLuciRouter(ROWS)
    assert has_luci_wire_support(router)
    table = fetch_table(router)
    assert (table.used, table.max_rules, table.free, table.is_full) == (2, 64, 62, False)
    assert table.rows[0] == ReservationRow("2E-6B-B3-EC-42-40", "192.168.1.212", "S24-Ultra", True)
    # the temporary override is removed again
    assert "_is_valid_response" not in vars(router)


def test_fetch_table_prefers_native_library_support():
    info = SimpleNamespace(
        reservations=[SimpleNamespace(macaddr="02-00-00-00-00-01", ipaddr="10.0.0.1", hostname="a", enabled=False)],
        max_rules=32,
    )
    router = Mock(spec=["get_ipv4_reservations_info", "update_ipv4_reservation"])
    router.get_ipv4_reservations_info.return_value = info
    table = fetch_table(router)
    assert table.max_rules == 32
    assert table.rows == [ReservationRow("02-00-00-00-00-01", "10.0.0.1", "a", False)]


def test_fetch_table_falls_back_to_list_getter():
    router = Mock(spec=["get_ipv4_reservations"])
    router.get_ipv4_reservations.return_value = [
        SimpleNamespace(macaddr="02-00-00-00-00-01", ipaddr="10.0.0.1", hostname=None, enabled=True)
    ]
    table = fetch_table(router)
    assert table.max_rules is None and table.free is None and not table.is_full
    assert table.rows[0].name == ""


def test_add_reservation_sends_ui_payload_and_verifies():
    router = FakeLuciRouter(ROWS)
    row = add_reservation(router, "aa:60:27:17:8d:45", "192.168.1.107", "S24-Ultra-new")
    assert row == ReservationRow("AA-60-27-17-8D-45", "192.168.1.107", "S24-Ultra-new", True)
    assert _ops(router) == ["load", "insert", "load"]
    new = loads(dict(parse_qsl(router.calls[1][1]))["new"])
    assert new == {"mac": "AA-60-27-17-8D-45", "ip": "192.168.1.107", "comment": "S24-Ultra-new",
                   "hostname": "S24-Ultra-new", "enable": "on"}


def test_add_reservation_refuses_full_table_and_duplicates():
    full = FakeLuciRouter(ROWS, max_rules=2)
    with pytest.raises(ReservationError, match="full"):
        add_reservation(full, "02:00:00:00:00:01", "192.168.1.100")
    assert _ops(full) == ["load"]

    router = FakeLuciRouter(ROWS)
    with pytest.raises(ReservationError, match="already has a reservation"):
        add_reservation(router, "2e:6b:b3:ec:42:40", "192.168.1.100")
    with pytest.raises(ReservationError, match="already reserved"):
        add_reservation(router, "02:00:00:00:00:01", "192.168.1.212")
    assert "insert" not in _ops(router)


def test_add_reservation_detects_silent_drop():
    router = FakeLuciRouter(ROWS, drop_writes=True)
    with pytest.raises(ReservationError, match="did not store"):
        add_reservation(router, "02:00:00:00:00:01", "192.168.1.100")


def test_update_reservation_moves_mac_in_place():
    router = FakeLuciRouter(ROWS)
    row = update_reservation(router, "2E-6B-B3-EC-42-40", mac="aa:60:27:17:8d:45")
    assert row == ReservationRow("AA-60-27-17-8D-45", "192.168.1.212", "S24-Ultra", True)
    body = dict(parse_qsl(router.calls[2][1]))
    assert body["operation"] == "update"
    assert body["key"] == "2E-6B-B3-EC-42-40"
    assert loads(body["old"])["mac"] == "2E-6B-B3-EC-42-40"
    assert loads(body["new"]) == {"mac": "AA-60-27-17-8D-45", "ip": "192.168.1.212", "comment": "S24-Ultra",
                                  "hostname": "S24-Ultra", "enable": "on"}
    # position kept, no extra row
    assert [r["mac"] for r in router.table] == ["AA-60-27-17-8D-45", "80-45-6B-31-C6-68"]


def test_update_reservation_ip_name_enable_and_errors():
    router = FakeLuciRouter(ROWS)
    row = update_reservation(router, "80-45-6B-31-C6-68", ip="192.168.1.240", comment="Bambu A1", enable=False)
    assert row == ReservationRow("80-45-6B-31-C6-68", "192.168.1.240", "Bambu A1", False)

    with pytest.raises(ReservationError, match="No reservation"):
        update_reservation(router, "02:00:00:00:00:99", ip="192.168.1.100")
    with pytest.raises(ReservationError, match="already reserved"):
        update_reservation(router, "80-45-6B-31-C6-68", ip="192.168.1.212")
    with pytest.raises(ReservationError, match="did not store"):
        update_reservation(FakeLuciRouter(ROWS, drop_writes=True), "80-45-6B-31-C6-68", ip="192.168.1.241")


def test_update_reservation_unsupported_router():
    router = Mock(spec=["get_ipv4_reservations"])
    router.get_ipv4_reservations.return_value = [
        SimpleNamespace(macaddr="02-00-00-00-00-01", ipaddr="10.0.0.1", hostname="a", enabled=True)
    ]
    with pytest.raises(ReservationError, match="does not support"):
        update_reservation(router, "02:00:00:00:00:01", ip="10.0.0.2")


def test_delete_reservation_verifies():
    router = FakeLuciRouter(ROWS)
    delete_reservation(router, "80:45:6b:31:c6:68")
    assert [r["mac"] for r in router.table] == ["2E-6B-B3-EC-42-40"]
    with pytest.raises(ReservationError, match="No reservation"):
        delete_reservation(router, "80:45:6b:31:c6:68")
    with pytest.raises(ReservationError, match="kept"):
        delete_reservation(FakeLuciRouter(ROWS, drop_writes=True), "80:45:6b:31:c6:68")


class FakeHass:
    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def _coordinator(router, table=None, supported=True):
    coord = TPLinkRouterCoordinator.__new__(TPLinkRouterCoordinator)
    coord.hass = FakeHass()
    coord.router = router
    coord.logger = logging.getLogger("test")
    coord.reservation_table = table
    coord.reservations_supported = supported
    coord._reservation_poll_failed = False
    coord._lock = asyncio.Lock()
    coord.async_update_listeners = Mock()
    router.authorize = Mock()
    router.logout = Mock()
    return coord


def test_poll_retries_after_failed_setup_probe_and_keeps_last_known(caplog):
    router = FakeLuciRouter(ROWS)
    coord = _coordinator(router, table=None)
    with patch("custom_components.tplink_router.coordinator.fetch_table", side_effect=RuntimeError("busy")):
        assert coord.poll_reservation_table() is None
        assert coord.poll_reservation_table() is None
    assert sum("failed to fetch IPv4 reservations" in r.message and r.levelno == logging.WARNING
               for r in caplog.records) == 1
    table = coord.poll_reservation_table()
    assert table.used == 2 and table.max_rules == 64
    coord.reservation_table = table
    with patch("custom_components.tplink_router.coordinator.fetch_table", side_effect=RuntimeError("busy")):
        assert coord.poll_reservation_table() is table


def test_poll_stops_when_not_implemented():
    coord = _coordinator(FakeLuciRouter(ROWS))
    with patch("custom_components.tplink_router.coordinator.fetch_table", side_effect=NotImplementedError):
        assert coord.poll_reservation_table() is None
    assert coord.reservations_supported is False


def test_coordinator_writes_update_table_and_raise_ha_errors():
    router = FakeLuciRouter(ROWS)
    coord = _coordinator(router)

    row = asyncio.run(coord.update_ipv4_reservation("2E-6B-B3-EC-42-40", mac="AA:60:27:17:8D:45"))
    assert row.mac == "AA-60-27-17-8D-45"
    assert coord.reservation_table.find_mac("AA-60-27-17-8D-45") is not None
    coord.async_update_listeners.assert_called()
    router.authorize.assert_called()
    router.logout.assert_called()

    asyncio.run(coord.add_ipv4_reservation("02:00:00:00:00:01", "192.168.1.100", "test"))
    asyncio.run(coord.delete_ipv4_reservation("02:00:00:00:00:01"))
    assert coord.reservation_table.used == 2

    with pytest.raises(HomeAssistantError, match="already reserved"):
        asyncio.run(coord.add_ipv4_reservation("02:00:00:00:00:01", "192.168.1.212"))
    coord.router = FakeLuciRouter(ROWS, drop_writes=True)
    coord.router.authorize = Mock()
    coord.router.logout = Mock()
    with pytest.raises(HomeAssistantError, match="did not store"):
        asyncio.run(coord.add_ipv4_reservation("02:00:00:00:00:01", "192.168.1.100"))


def _table():
    return ReservationTable(
        [ReservationRow("02-00-00-00-00-{:02X}".format(i), "10.0.0.{}".format(i), "h{}".format(i), True)
         for i in range(61)],
        64,
    )


def _entity(cls, coordinator, *args):
    entity = cls.__new__(cls)
    entity.coordinator = coordinator
    entity.hass = None
    if args:
        entity.__init__(coordinator, *args)
    return entity


def test_reservation_sensors():
    coordinator = Mock()
    coordinator.unique_id = "entry-1"
    coordinator.device_info = {"identifiers": {(DOMAIN, "mac")}}
    coordinator.reservation_table = None
    sensor = _entity(TPLinkRouterReservationsSensor, coordinator)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {"reservations": []}

    coordinator.reservation_table = _table()
    assert sensor.native_value == 61
    attrs = sensor.extra_state_attributes
    assert attrs["max_reservations"] == 64 and attrs["free"] == 3
    assert attrs["reservations"][0] == {"mac": "02-00-00-00-00-00", "ip": "10.0.0.0", "hostname": "h0",
                                        "enabled": True}

    limit = TPLinkRouterReservationsCapacitySensor(coordinator, "limit")
    free = TPLinkRouterReservationsCapacitySensor(coordinator, "free")
    assert (limit.native_value, free.native_value) == (64, 3)
    assert limit.unique_id == "entry-1_tplink_router_dhcp_reservations_limit"
    coordinator.reservation_table = ReservationTable([], None)
    assert limit.native_value is None


def test_near_full_binary_sensor():
    coordinator = Mock()
    coordinator.unique_id = "entry-1"
    coordinator.device_info = {}
    coordinator.reservation_table = None
    sensor = TPLinkRouterReservationsNearFullSensor(coordinator, 60)
    assert sensor.is_on is None
    coordinator.reservation_table = _table()  # 61/64
    assert sensor.is_on is True
    assert sensor.extra_state_attributes == {"warning_threshold": 60, "used": 61, "max_reservations": 64,
                                             "free": 3}
    coordinator.reservation_table = ReservationTable(_table().rows[:59], 64)
    assert sensor.is_on is False
    # a threshold above the table size still fires when the table is full
    big = TPLinkRouterReservationsNearFullSensor(coordinator, 100)
    coordinator.reservation_table = ReservationTable(_table().rows[:2], 2)
    assert big.is_on is True


def test_update_reservation_schema():
    data = UPDATE_RESERVATION_SCHEMA({"device": "abc", "old_mac": "2e:6b:b3:ec:42:40", "mac": "AA-60-27-17-8D-45"})
    assert data["old_mac"] == "2e:6b:b3:ec:42:40" and "ip" not in data
    data = UPDATE_RESERVATION_SCHEMA({"device": "abc", "old_mac": "2e:6b:b3:ec:42:40", "ip": "192.168.1.5",
                                      "comment": "x", "enable": False})
    assert data["enable"] is False
    with pytest.raises(vol.Invalid):
        UPDATE_RESERVATION_SCHEMA({"device": "abc", "old_mac": "bad"})
    with pytest.raises(vol.Invalid):
        UPDATE_RESERVATION_SCHEMA({"device": "abc", "old_mac": "2e:6b:b3:ec:42:40", "ip": "999.1.1.1"})


def test_reservation_service_coordinator_errors():
    hass = Mock()
    with patch("custom_components.tplink_router.get_coordinator_for_device", return_value=None):
        with pytest.raises(ServiceValidationError):
            _reservation_coordinator(hass, "dev", "add_ipv4_reservation")

    coordinator = Mock()
    coordinator.reservations_supported = True
    coordinator.supports_reservation_update = False
    coordinator.router = Mock(spec=["get_ipv4_reservations", "add_ipv4_reservation"])
    with patch("custom_components.tplink_router.get_coordinator_for_device", return_value=coordinator):
        assert _reservation_coordinator(hass, "dev", "add_ipv4_reservation") is coordinator
        with pytest.raises(ServiceValidationError):
            _reservation_coordinator(hass, "dev", "update_ipv4_reservation")
        with pytest.raises(ServiceValidationError):
            _reservation_coordinator(hass, "dev", "delete_ipv4_reservation")
