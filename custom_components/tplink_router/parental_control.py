"""HomeCare profiles using the coordinator's existing authenticated client."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from json import dumps
from logging import Logger
import re
from typing import Any
from urllib.parse import urlencode

from tplinkrouterc6u import AbstractRouter
from tplinkrouterc6u.client.c6u import TplinkBaseRouter


PROFILE_LIST_PATH = "admin/smart_network?form=patrol_owner_list"
PROFILE_BLOCK_PATH = "admin/smart_network?form=patrol_owner_block"
PROFILE_DEVICES_PATH = "admin/smart_network?form=patrol_devices"
PROFILE_LIMIT_PATH = "admin/smart_network?form=patrol_limit"
PROFILE_APPS_PATH = "admin/smart_network?form=app_list"
PERIODS = ("workday", "weekend")
SCHEDULE_FLAGS = tuple(
    f"enable_{period}_{kind}"
    for period in PERIODS for kind in ("time_limit", "bed_time")
)


@dataclass(frozen=True)
class ParentalDevice:
    device_id: str
    name: str
    mac: str
    client_type: str | int
    owner_id: str = ""

    def as_dict(self) -> dict[str, str | int]:
        return {
            "device_id": self.device_id, "name": self.name, "mac": self.mac,
            "client_type": self.client_type, "owner_id": self.owner_id,
        }


@dataclass(frozen=True)
class ParentalProfile:
    owner_id: str
    name: str
    internet_blocked: bool
    clients: tuple[ParentalDevice, ...] | None = ()
    settings: dict[str, bool | int] = field(default_factory=dict)


@dataclass(frozen=True)
class ParentalStatus:
    # None means a failed read, not a successful empty profile list.
    profiles: dict[str, ParentalProfile] | None


def supports_parental_control(router: AbstractRouter, model: str) -> bool:
    """Only enable the inspected HomeCare API, not unrelated HomeShield APIs."""
    return isinstance(router, TplinkBaseRouter) and model.strip().lower() in (
        "archer ax50", "ax50",
    )


def parse_profiles(data: object) -> dict[str, ParentalProfile]:
    """Validate the complete response without retaining filters or browsing data."""
    if not isinstance(data, list):
        raise ValueError("Invalid parental profile list")
    profiles = {}
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Invalid parental profile record")
        owner_id = item.get("owner_id")
        name = item.get("name")
        blocked = item.get("internet_blocked")
        if (
            not isinstance(owner_id, str)
            or not owner_id.strip()
            or not isinstance(name, str)
            or not isinstance(blocked, bool)
            or owner_id in profiles
        ):
            raise ValueError("Invalid parental profile fields")
        settings = {}
        for period in PERIODS:
            for kind, fields in (
                ("time_limit", (f"{period}_daily_time",)),
                ("bed_time", (f"{period}_bed_time_begin", f"{period}_bed_time_end")),
            ):
                pro = item.get("time_limit" if kind == "time_limit" else "bedtime", {})
                if not isinstance(pro, dict) or pro.get("is_pro", False) is not False:
                    continue
                flag = f"enable_{period}_{kind}"
                if not isinstance(item.get(flag), bool):
                    continue
                try:
                    values = {
                        key: _minutes(
                            item.get(key), daily=kind == "time_limit",
                            disabled_budget=kind == "time_limit" and not item[flag],
                        ) for key in fields
                    }
                except ValueError:
                    continue
                settings.update({flag: item[flag], **values})
        try:
            clients = parse_devices(item.get("client_list", []))
        except ValueError:
            clients = None
        profiles[owner_id] = ParentalProfile(owner_id, name, blocked, clients, settings)
    return profiles


def _minutes(value: object, *, daily: bool = False, disabled_budget: bool = False) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Invalid parental schedule minutes")
    if daily:
        if not (value == 0 and disabled_budget) and (not 15 <= value <= 960 or value % 15):
            raise ValueError("Daily limits must be 15-960 minutes in 15-minute steps")
    elif not 0 <= value < 1440:
        raise ValueError("Invalid parental bedtime minutes")
    return value


def parse_devices(data: object) -> tuple[ParentalDevice, ...]:
    # This firmware serializes empty LuCI arrays as {}, not just [].
    if isinstance(data, dict) and not data:
        return ()
    if not isinstance(data, list):
        raise ValueError("Invalid parental device list")
    devices = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Invalid parental device record")
        if any(not isinstance(item.get(key), str) for key in ("name", "mac")):
            raise ValueError("Invalid parental device fields")
        if (
            not isinstance(item.get("device_id"), (str, int)) or isinstance(item["device_id"], bool)
            or not isinstance(item.get("client_type"), (str, int)) or isinstance(item["client_type"], bool)
        ):
            raise ValueError("Invalid parental device identifiers")
        device_id = str(item["device_id"])
        owner_id = item.get("owner_id", "")
        if isinstance(owner_id, int) and not isinstance(owner_id, bool):
            owner_id = str(owner_id)
        if (
            not device_id.strip() or device_id in seen or not isinstance(owner_id, str)
            or not re.fullmatch(r"[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}", item["mac"])
        ):
            raise ValueError("Invalid parental device identity")
        seen.add(device_id)
        devices.append(ParentalDevice(device_id, item["name"], item["mac"], item["client_type"], owner_id))
    return tuple(devices)


def schedule_changes(
    period: str, kind: str, *, enabled: bool | None = None,
    minutes: int | None = None, begin: str | None = None, end: str | None = None,
) -> dict[str, bool | int]:
    """Translate explicit HA inputs; never substitute defaults for omitted values."""
    if period not in PERIODS or kind not in ("bed_time", "time_limit"):
        raise ValueError("Invalid parental schedule type")
    changes: dict[str, bool | int] = {}
    if enabled is not None:
        if not isinstance(enabled, bool):
            raise ValueError("Enabled must be a boolean")
        changes[f"enable_{period}_{kind}"] = enabled
    if kind == "time_limit":
        if begin is not None or end is not None:
            raise ValueError("Bedtime fields are not daily limits")
        if minutes is not None:
            changes[f"{period}_daily_time"] = _minutes(minutes, daily=True)
    else:
        if minutes is not None:
            raise ValueError("Daily minutes are not a bedtime window")
        for key, value in (("begin", begin), ("end", end)):
            if value is not None:
                if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d(?::00)?", value):
                    raise ValueError("Bedtimes must use HH:MM with zero seconds")
                hour, minute = value.split(":")[:2]
                changes[f"{period}_bed_time_{key}"] = int(hour) * 60 + int(minute)
    if not changes:
        raise ValueError("Specify at least one parental setting")
    return changes


def _profile_request(
    router: AbstractRouter, path: str, data: str, *, acknowledgement: bool = False,
) -> object:
    if not isinstance(router, TplinkBaseRouter):
        raise NotImplementedError
    # The pinned library includes decrypted responses in its debug error logs.
    # Calls are serialized by the coordinator; restore its logger before returning.
    logger = router._logger
    data_block = router._data_block
    try:
        router._logger = None
        if acknowledgement:
            # HomeCare write acknowledgements can omit "data". Have the pinned
            # transport validate and extract "success" rather than discard errors.
            router._data_block = "success"
        result = router.request(path, data)
        if acknowledgement and result is not True:
            raise ValueError("Invalid parental profile write acknowledgement")
        return result
    finally:
        router._logger = logger
        router._data_block = data_block


def collect_parental_status(
    router: AbstractRouter, logger: Logger,
) -> ParentalStatus | None:
    """Keep transient/unknown failures polling; only explicit unsupported stops it."""
    try:
        return ParentalStatus(parse_profiles(_profile_request(
            router, PROFILE_LIST_PATH, "operation=load",
        )))
    except NotImplementedError:
        return None
    except Exception:
        # Library errors can contain the entire decrypted profile response.
        logger.warning("TPLink Router parental profile read failed; retrying next poll")
        return ParentalStatus(None)


def write_profile_access(router: AbstractRouter, owner_id: str, enabled: bool) -> None:
    """Use form encoding and JavaScript boolean spelling, as the HomeCare UI does."""
    if not isinstance(owner_id, str) or not owner_id.strip() or not isinstance(enabled, bool):
        raise ValueError("Invalid parental profile access parameters")
    _profile_request(
        router,
        PROFILE_BLOCK_PATH,
        urlencode({
            "operation": "write",
            "owner_id": owner_id,
            "internet_blocked": "false" if enabled else "true",
        }),
        acknowledgement=True,
    )


class ParentalEditError(ValueError):
    """A safe, user-facing validation or confirmation error."""


def read_parental_devices(router: AbstractRouter) -> tuple[ParentalDevice, ...]:
    return parse_devices(_profile_request(router, PROFILE_DEVICES_PATH, "operation=load"))


def read_profile_devices(
    router: AbstractRouter, owner_id: str, scope: str = "profile",
) -> list[dict[str, str | int]]:
    if not isinstance(owner_id, str) or not owner_id.strip() or scope not in ("profile", "inventory"):
        raise ParentalEditError("Invalid parental profile or device scope")
    profiles = parse_profiles(_profile_request(router, PROFILE_LIST_PATH, "operation=load"))
    if owner_id not in profiles:
        raise ParentalEditError("Parental profile no longer exists")
    if scope == "inventory":
        return [device.as_dict() for device in read_parental_devices(router)]
    clients = profiles[owner_id].clients
    if clients is None:
        raise ParentalEditError("Assigned device list is invalid")
    # Membership in this fresh profile record is authoritative, including offline
    # assignments and stale/missing per-client owner_id metadata.
    return [{**device.as_dict(), "owner_id": owner_id} for device in clients]


def _wire_profile(profile: dict[str, Any], apps: dict[str, Any]) -> dict[str, Any]:
    """The UI moves application aliases from website_list into app_list on save."""
    result = deepcopy(profile)
    # The native Store excludes this read-only list response field from old/new.
    result.pop("insights", None)
    for period in PERIODS:
        for endpoint in ("begin", "end"):
            key = f"{period}_bed_time_{endpoint}"
            value = result.get(key)
            if (
                isinstance(value, str) and value.isascii() and value.isdigit()
                and int(value) < 1440
            ):
                result[key] = int(value)
    for key in ("website_list", "categories_list"):
        value = result.get(key)
        if isinstance(value, dict) and not value:
            result[key] = []
        elif not isinstance(value, list):
            raise ParentalEditError("Profile filters are incomplete; edit was not sent")
    if isinstance(result.get("client_list"), dict) and not result["client_list"]:
        result["client_list"] = []
    app_list = result.get("app_list", [])
    if not isinstance(app_list, list):
        raise ParentalEditError("Profile application filters are invalid; edit was not sent")
    app_list = deepcopy(app_list)
    websites = []
    for website in result["website_list"]:
        if not isinstance(website, str):
            raise ParentalEditError("Profile website filters are invalid; edit was not sent")
        if website in apps:
            if apps[website] not in app_list:
                app_list.append(apps[website])
        else:
            websites.append(website)
    result["website_list"] = websites
    result["app_list"] = app_list
    return result


def _app_map(router: AbstractRouter) -> dict[str, Any]:
    data = _profile_request(router, PROFILE_APPS_PATH, "operation=read")
    if not isinstance(data, list):
        raise ParentalEditError("Application filter metadata is unavailable; edit was not sent")
    result = {}
    for item in data:
        if (
            not isinstance(item, dict) or not isinstance(item.get("name"), str)
            or not isinstance(item.get("app_id"), (str, int)) or isinstance(item["app_id"], bool)
            or item["name"] in result and result[item["name"]] != item["app_id"]
        ):
            raise ParentalEditError("Application filter metadata is invalid; edit was not sent")
        result[item["name"]] = item["app_id"]
    return result


def _profile_write_record(profile: dict[str, Any]) -> dict[str, Any]:
    """Native NEW is configuration, not the response's per-device runtime metadata."""
    result = deepcopy(profile)
    result["client_list"] = [
        {key: str(client[key]) if key == "device_id" else client[key]
         for key in ("client_type", "name", "mac", "device_id")}
        for client in result["client_list"]
    ]
    for period in PERIODS:
        key = f"{period}_daily_time"
        # Native combobox has no selection for this observed disabled sentinel.
        if result.get(f"enable_{period}_time_limit") is False and result.get(key) == "0":
            result.pop(key)
    return result


def _profile_mismatches(
    expected: dict[str, Any], actual: dict[str, Any], apps: dict[str, Any],
) -> tuple[str, ...]:
    """Compare protected fields without returning any household values."""
    actual = _wire_profile(actual, apps)
    mismatches = []
    # Usage counters (limit) can change while the edit is in progress.
    fields = {
        "owner_id", "name", "internet_blocked", "filter_level", "categories_list",
        "website_list", "app_list", "time_limit", "bedtime",
        *SCHEDULE_FLAGS,
        *(f"{period}_{key}" for period in PERIODS for key in ("daily_time", "bed_time_begin", "bed_time_end")),
    }
    protected_fields = set(expected) - {"key", "limit", "insights", "client_list"}
    unknown_changed = False
    for key in protected_fields - fields:
        if expected[key] != actual.get(key):
            unknown_changed = True
    if unknown_changed:
        mismatches.append("profile_metadata")
    for key in fields:
        old, new = expected.get(key), actual.get(key)
        if key.endswith(("_daily_time", "_bed_time_begin", "_bed_time_end")) and old is not None:
            try:
                old_minutes = _minutes(old, daily=key.endswith("_daily_time"))
                new_minutes = _minutes(new, daily=key.endswith("_daily_time"))
            except ValueError:
                if old != new:
                    mismatches.append(key)
            else:
                if old_minutes != new_minutes:
                    mismatches.append(key)
        elif old != new:
            mismatches.append(key)

    def assignments(record: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
        return {
            client.device_id: (client.mac.lower().replace("-", ":"), client.name, str(client.client_type))
            for client in parse_devices(record.get("client_list", []))
        }

    if assignments(expected) != assignments(actual):
        mismatches.append("client_list")
    expected_clients = expected.get("client_list", [])
    actual_clients = {str(client["device_id"]): client for client in actual.get("client_list", [])}
    for client in expected_clients:
        confirmed = actual_clients.get(str(client["device_id"]))
        # Native saves regenerate online/owner_id; neither is a configurable priority.
        protected = set(client) - {"device_id", "mac", "name", "client_type", "online", "owner_id"}
        if confirmed is not None and any(client[key] != confirmed.get(key) for key in protected):
            mismatches.append("client_metadata")
            break
    return tuple(sorted(mismatches))


def _verify_profile(expected: dict[str, Any], actual: dict[str, Any], apps: dict[str, Any]) -> bool:
    return not _profile_mismatches(expected, actual, apps)


def _assignment_readback_error(
    status: ParentalStatus, owner_id: str, expected: dict[str, Any],
    add_device: str | None, remove_device: str | None,
) -> str | None:
    """Describe confirmed membership only; metadata mismatches remain failures."""
    profiles = status.profiles
    profile = profiles.get(owner_id) if profiles is not None else None
    if profile is None or profile.clients is None:
        return None
    if add_device is not None:
        candidate = next(client for client in parse_devices(expected["client_list"]) if client.device_id == add_device)

        def normalize(mac: str) -> str:
            return mac.lower().replace("-", ":")
        if not any(
            client.device_id == candidate.device_id and normalize(client.mac) == normalize(candidate.mac)
            for client in profile.clients
        ):
            memberships_known = all(other.clients is not None for other in profiles.values())
            assigned_elsewhere = any(
                normalize(client.mac) == normalize(candidate.mac)
                for other in profiles.values() if other.clients is not None for client in other.clients
            )
            state = (
                "The device is unassigned in read-back. " if memberships_known and not assigned_elsewhere
                else "Inspect current profile memberships before retrying. "
            )
            return (
                "Profile edit read-back mismatch: the requested device assignment is absent from the destination. "
                + state + "No automatic retry was made."
            )
        return (
            "Profile edit read-back mismatch: the device is assigned to the destination, "
            "but its details or other protected profile settings differ. Do not retry the assignment; inspect settings."
        )
    if remove_device is not None and any(client.device_id == remove_device for client in profile.clients):
        return (
            "Profile edit read-back mismatch: the device is still assigned to the original profile. "
            "No automatic retry was made."
        )
    return None


def _log_profile_mismatch(
    logger: Logger, mismatches: tuple[str, ...], expected: dict[str, Any], actual: dict[str, Any] | None,
    add_device: str | None, remove_device: str | None, add_devices: tuple[str, ...] = (),
) -> None:
    """Emit only fixed field labels, types, counts and identity-presence booleans."""
    record = actual or {}
    categories = {
        "profile_metadata", "client_metadata", "other_profile", "profile_shape", "profile_missing",
    }
    types = [
        f"{key}:{type(expected.get(key)).__name__}->{type(record.get(key)).__name__}"
        for key in mismatches if key not in categories
    ]
    diagnostics: dict[str, Any] = {"field_types": ", ".join(types)}
    if categories.intersection(mismatches):
        diagnostics["mismatch_categories"] = ", ".join(sorted(categories.intersection(mismatches)))
    for label, item in (("expected", expected), ("actual", record)):
        clients = item.get("client_list")
        diagnostics[f"{label}_client_count"] = (
            len(clients) if isinstance(clients, list) else 0 if clients == {} else None
        )
    try:
        expected_clients = parse_devices(expected.get("client_list"))
        actual_clients = parse_devices(record.get("client_list"))
    except ValueError:
        diagnostics["membership_readback_valid"] = False
    else:
        diagnostics["membership_readback_valid"] = True
        requested_ids = ((add_device,) if add_device is not None else ()) + add_devices
        if requested_ids:
            expected_by_id = {client.device_id: client for client in expected_clients}
            presence = []
            for device_id in requested_ids:
                candidate = expected_by_id.get(device_id)
                presence.append(candidate is not None and any(
                    client.device_id == candidate.device_id
                    and client.mac.lower().replace("-", ":") == candidate.mac.lower().replace("-", ":")
                    for client in actual_clients
                ))
            diagnostics["requested_assignment_presence"] = presence
            if len(presence) == 1:
                diagnostics["requested_assignment_present"] = presence[0]
        if remove_device is not None:
            diagnostics["removed_assignment_still_present"] = any(
                client.device_id == remove_device for client in actual_clients
            )
    logger.warning("TPLink Router parental read-back mismatch diagnostics: %s", diagnostics)


def edit_profile(
    router: AbstractRouter, logger: Logger, owner_id: str, *,
    changes: dict[str, bool | int] | None = None,
    add_device: str | None = None, remove_device: str | None = None,
    restore_client: dict[str, Any] | None = None,
) -> tuple[ParentalStatus, str | None]:
    """Fresh read/modify/write/read-back; caller holds the shared request lock."""
    data = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
    profiles = parse_profiles(data)
    if owner_id not in profiles:
        raise ParentalEditError("Parental profile no longer exists")
    if sum(value is not None for value in (changes, add_device, remove_device)) != 1:
        raise ParentalEditError("Specify exactly one parental edit")
    index = next(i for i, item in enumerate(data) if item["owner_id"] == owner_id)
    original = deepcopy(data[index])
    updated = deepcopy(original)
    profile = profiles[owner_id]
    if profile.clients is None:
        raise ParentalEditError("Assigned device list is invalid; edit was not sent")
    if changes is not None:
        if not changes or any(key not in profile.settings for key in changes):
            raise ParentalEditError("Schedule is unavailable, incomplete or managed by HomeCare Pro")
        for key, value in changes.items():
            if key in SCHEDULE_FLAGS:
                if not isinstance(value, bool):
                    raise ParentalEditError("Schedule enable flags must be boolean")
                updated[key] = value
            else:
                minutes = _minutes(value, daily=key.endswith("_daily_time"))
                # The UI's combobox emits daily budgets as strings; clocks are numbers.
                updated[key] = str(minutes) if key.endswith("_daily_time") else minutes
        for period in PERIODS:
            flag, budget = f"enable_{period}_time_limit", f"{period}_daily_time"
            if changes.get(flag) is True:
                try:
                    _minutes(updated[budget], daily=True)
                except ValueError:
                    raise ParentalEditError(
                        "Set a daily budget of 15-960 minutes before enabling this limit"
                    ) from None
        for period in PERIODS:
            begin, end = f"{period}_bed_time_begin", f"{period}_bed_time_end"
            if (
                (begin in changes or end in changes or changes.get(f"enable_{period}_bed_time") is True)
                and _minutes(updated[begin]) == _minutes(updated[end])
            ):
                raise ParentalEditError("Bedtime start and end must differ")
    else:
        device_id = add_device if add_device is not None else remove_device
        if not isinstance(device_id, str) or not device_id.strip():
            raise ParentalEditError("A router device_id is required")
        clients = deepcopy(original.get("client_list", []))
        if isinstance(clients, dict) and not clients:
            clients = []
        existing = {client.device_id for client in profile.clients}
        if (
            device_id in existing and add_device is not None
            or device_id not in existing and remove_device is not None
        ):
            return ParentalStatus(profiles), None
        if add_device is not None:
            candidates = (
                parse_devices([restore_client]) if restore_client is not None
                else read_parental_devices(router)
            )
            device = next((candidate for candidate in candidates if candidate.device_id == device_id), None)
            if device is None:
                raise ParentalEditError("Device is not in the router's assignable device list")
            if (restore_client is None and device.owner_id not in ("", owner_id)) or any(
                other.owner_id != owner_id and (
                    other.clients is None or any(
                        client.device_id == device_id
                        or client.mac.lower().replace("-", ":") == device.mac.lower().replace("-", ":")
                        for client in other.clients
                    )
                ) for other in profiles.values()
            ):
                raise ParentalEditError("Device belongs to another profile; remove it there first")
            limits = _profile_request(router, PROFILE_LIMIT_PATH, "operation=read")
            maximum = limits.get("devices_len") if isinstance(limits, dict) else None
            if isinstance(maximum, str) and maximum.isascii() and maximum.isdigit():
                maximum = int(maximum)
            if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
                raise ParentalEditError("Router device limit is unavailable; edit was not sent")
            if len(clients) >= maximum:
                raise ParentalEditError("Profile has reached the router's device limit")
            client = device.as_dict()
            client.pop("owner_id")
            if restore_client is not None:
                restored = parse_devices([restore_client])[0]
                if restored.device_id != device_id:
                    raise ParentalEditError("Restored assignment identity does not match the device")
                client = deepcopy(restore_client)
            clients.append(client)
        else:
            clients = [client for client in clients if str(client["device_id"]) != device_id]
        updated["client_list"] = clients
    if updated == original:
        return ParentalStatus(profiles), None
    return _commit_profile(
        router, logger, data, index, updated, add_device=add_device, remove_device=remove_device,
    )


def _commit_profile(
    router: AbstractRouter, logger: Logger, data: list[dict[str, Any]], index: int,
    updated: dict[str, Any], *, add_device: str | None = None, remove_device: str | None = None,
    add_devices: tuple[str, ...] = (),
) -> tuple[ParentalStatus, str | None]:
    """One native update, no retry; retain raw expected state apart from wire projection."""
    original = data[index]
    owner_id = original["owner_id"]
    apps = _app_map(router)
    updated = _wire_profile(updated, apps)
    # Store.update adds the generated UI row key and index even when owner_id exists.
    key = original.get("key")
    if key is None:
        key = f"key-{index}"
    if not isinstance(key, (str, int)) or isinstance(key, bool):
        raise ParentalEditError("Invalid profile row key; edit was not sent")
    old = {**original, "key": key}
    old.pop("insights", None)
    updated["key"] = key
    payload = urlencode({
        "operation": "update", "index": index, "key": key,
        "old": dumps(old, separators=(",", ":"), ensure_ascii=False),
        "new": dumps(_profile_write_record(updated), separators=(",", ":"), ensure_ascii=False),
    })
    error = None
    try:
        _profile_request(router, PROFILE_LIST_PATH, payload, acknowledgement=True)
    except Exception:
        error = "Profile edit acknowledgement failed; the router may have applied the change"
    # Do not let a failed acknowledgement hide the actual state or prevent recovery.
    try:
        confirmation = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
        status = ParentalStatus(parse_profiles(confirmation))
    except Exception:
        logger.warning("TPLink Router parental edit read-back failed; retrying next poll")
        return ParentalStatus(None), error or "Profile edit could not be read back; it may have been applied"
    if error is None:
        actual = next((item for item in confirmation if item["owner_id"] == owner_id), None)
        try:
            mismatches = _profile_mismatches(updated, actual, apps) if actual is not None else ("profile_missing",)
        except ValueError:
            mismatches = ("profile_shape",)
        try:
            if any(
                not _verify_profile(
                    _wire_profile(record, apps),
                    next(item for item in confirmation if item["owner_id"] == record["owner_id"]),
                    apps,
                )
                for record in data if record["owner_id"] != owner_id
            ):
                mismatches += ("other_profile",)
        except (ValueError, StopIteration):
            mismatches += ("other_profile",)
        if mismatches:
            _log_profile_mismatch(logger, mismatches, updated, actual, add_device, remove_device, add_devices)
            error = _assignment_readback_error(status, owner_id, updated, add_device, remove_device) or (
                "Profile edit read-back mismatch; check settings in the router"
            )
    return status, error


def assign_profile_devices(
    router: AbstractRouter, logger: Logger, owner_id: str, macs: list[str],
) -> tuple[ParentalStatus, dict[str, Any]]:
    """Assign selected unassigned devices with one update and per-device actual outcomes."""
    if not isinstance(owner_id, str) or not owner_id:
        raise ParentalEditError("Choose an existing destination profile")
    if not isinstance(macs, list) or not 1 <= len(macs) <= 32 or any(
        not isinstance(mac, str) or not re.fullmatch(r"[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}", mac)
        for mac in macs
    ):
        raise ParentalEditError("Select 1-32 devices with valid identities")
    selected = [mac.lower().replace("-", ":") for mac in macs]
    if len(set(selected)) != len(selected):
        raise ParentalEditError("Duplicate selected devices; no edit was sent")
    data = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
    profiles = parse_profiles(data)
    if owner_id not in profiles:
        raise ParentalEditError("Destination profile no longer exists")
    if any(profile.clients is None for profile in profiles.values()):
        raise ParentalEditError("Profile memberships are incomplete; no edit was sent")
    if any(
        client.mac.lower().replace("-", ":") in selected
        for profile in profiles.values() for client in profile.clients
    ):
        raise ParentalEditError(
            "A selected device is already assigned. Refresh; use individual review for explicit moves"
        )
    inventory = read_parental_devices(router)
    candidates = []
    for mac in selected:
        matches = [device for device in inventory if device.mac.lower().replace("-", ":") == mac]
        if len(matches) != 1 or matches[0].owner_id:
            raise ParentalEditError("A selected device is missing, ambiguous or ownership changed; refresh")
        candidates.append(matches[0])
    if any(
        client.device_id in {device.device_id for device in candidates}
        for profile in profiles.values() for client in profile.clients
    ):
        raise ParentalEditError("Selected device identity conflicts with an existing assignment")
    limits = _profile_request(router, PROFILE_LIMIT_PATH, "operation=read")
    maximum = limits.get("devices_len") if isinstance(limits, dict) else None
    if isinstance(maximum, str) and maximum.isascii() and maximum.isdigit():
        maximum = int(maximum)
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        raise ParentalEditError("Router device capacity is unavailable; no edit was sent")
    if len(profiles[owner_id].clients) + len(candidates) > maximum:
        raise ParentalEditError("Selected devices exceed destination capacity; no edit was sent")
    index = next(i for i, record in enumerate(data) if record["owner_id"] == owner_id)
    updated = deepcopy(data[index])
    clients = updated.get("client_list", [])
    updated["client_list"] = ([] if clients == {} else clients) + [
        {key: value for key, value in device.as_dict().items() if key != "owner_id"}
        for device in candidates
    ]
    status, error = _commit_profile(
        router, logger, data, index, updated,
        add_devices=tuple(device.device_id for device in candidates),
    )
    outcomes = []
    for mac, device in zip(selected, candidates, strict=True):
        actual = None if status.profiles is None else status.profiles.get(owner_id)
        result = "unknown"
        if actual is not None and actual.clients is not None and all(
            profile.clients is not None for profile in status.profiles.values()
        ):
            memberships = [
                (profile.owner_id, client) for profile in status.profiles.values()
                for client in profile.clients if client.mac.lower().replace("-", ":") == mac
            ]
            if not memberships:
                result = "not_assigned"
            elif len(memberships) == 1 and memberships[0][0] == owner_id and (
                memberships[0][1].device_id == device.device_id
            ):
                result = "assigned_unconfirmed" if error else "assigned"
            else:
                result = "conflict"
        outcomes.append({"mac": mac, "status": result})
    return status, {"outcomes": outcomes, "confirmed": error is None, "error": error}


def change_device_profile(
    router: AbstractRouter, logger: Logger, mac: str, expected_owner: str, destination: str,
) -> tuple[ParentalStatus, str | None]:
    """Explicit, verified move with compensating recovery, under the shared lock."""
    data = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
    profiles = parse_profiles(data)
    if any(profile.clients is None for profile in profiles.values()):
        raise ParentalEditError("Profile memberships are incomplete; refresh and retry")
    normalized = mac.lower().replace("-", ":")
    memberships = [
        (profile.owner_id, client)
        for profile in profiles.values() for client in profile.clients
        if client.mac.lower().replace("-", ":") == normalized
    ]
    if len(memberships) > 1:
        raise ParentalEditError("Device has conflicting memberships; resolve them in the router")
    source = memberships[0][0] if memberships else ""
    if source != expected_owner or destination and destination not in profiles:
        raise ParentalEditError("Profile membership changed or target was removed; refresh before retrying")
    if source == destination:
        return ParentalStatus(profiles), None
    device = memberships[0][1] if memberships else None
    if destination:
        inventory = read_parental_devices(router)
        candidate = next((item for item in inventory if item.mac.lower().replace("-", ":") == normalized), None)
        if candidate is None or candidate.owner_id not in ("", source):
            raise ParentalEditError("Device is unavailable for assignment or ownership changed; refresh")
        if device is not None and candidate.device_id != device.device_id:
            raise ParentalEditError("Router device identity changed; refresh before moving")
        device = candidate
        limits = _profile_request(router, PROFILE_LIMIT_PATH, "operation=read")
        maximum = limits.get("devices_len") if isinstance(limits, dict) else None
        if isinstance(maximum, str) and maximum.isascii() and maximum.isdigit():
            maximum = int(maximum)
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
            raise ParentalEditError("Router device capacity is unavailable")
        if len(profiles[destination].clients) >= maximum:
            raise ParentalEditError("Destination profile has reached the router's device limit")
    if device is None:
        raise ParentalEditError("Device no longer exists; refresh")
    if any(
        client.device_id == device.device_id and client.mac.lower().replace("-", ":") != normalized
        for profile in profiles.values() for client in profile.clients
    ):
        raise ParentalEditError("Router device identity is ambiguous; resolve it before moving")
    # Validate filter serialization before removing any protection.
    apps = _app_map(router)
    for record in data:
        if record["owner_id"] in (source, destination):
            key = record.get("key")
            if key is not None and (not isinstance(key, (str, int)) or isinstance(key, bool)):
                raise ParentalEditError("Invalid profile row key; move was not sent")
            _wire_profile(record, apps)
    status = ParentalStatus(profiles)
    if source:
        status, error = edit_profile(router, logger, source, remove_device=device.device_id)
        if error:
            try:
                original_client = next(
                    client for record in data if record["owner_id"] == source
                    for client in record["client_list"] if str(client["device_id"]) == device.device_id
                )
                status, restore_error = _restore_assignment(router, logger, source, original_client)
                if restore_error is None:
                    return status, "Removal failed; the original profile assignment was restored"
            except Exception:
                logger.warning("TPLink Router original assignment recovery could not be confirmed")
            return status, "Removal was not confirmed. Refresh and inspect the original profile before retrying"
    if not destination:
        return status, None
    try:
        transferred = None
        if source:
            transferred = deepcopy(next(
                client for record in data if record["owner_id"] == source
                for client in record["client_list"] if str(client["device_id"]) == device.device_id
            ))
            if "owner_id" in transferred:
                transferred["owner_id"] = int(destination) if (
                    isinstance(transferred["owner_id"], int) and destination.isascii() and destination.isdigit()
                ) else destination
        status, error = edit_profile(
            router, logger, destination, add_device=device.device_id, restore_client=transferred,
        )
    except Exception:
        status, error = collect_parental_status(router, logger) or ParentalStatus(None), "Assignment failed"
    if error is None:
        return status, None
    if not source:
        return status, error + ". Refresh to inspect the actual assignment before retrying."
    # A failed acknowledgement may still have applied the destination assignment.
    # Never restore the source until destination removal has been confirmed.
    try:
        status, cleanup_error = edit_profile(router, logger, destination, remove_device=device.device_id)
        if cleanup_error:
            return status, "Move failed and destination cleanup is unconfirmed; refresh and inspect both profiles"
        # Restore the original raw device record, not a reconstruction from inventory.
        original_client = next(
            client for record in data if record["owner_id"] == source
            for client in record.get("client_list", []) if str(client["device_id"]) == device.device_id
        )
        status, restore_error = _restore_assignment(router, logger, source, original_client)
        if restore_error:
            return status, "Move failed and original assignment could not be confirmed; inspect both profiles"
        return status, "Move failed; the original profile assignment was restored"
    except Exception:
        return collect_parental_status(router, logger) or ParentalStatus(None), (
            "Move failed and recovery could not be confirmed. Refresh and inspect both profiles before retrying"
        )


def _restore_assignment(
    router: AbstractRouter, logger: Logger, owner_id: str, client: dict[str, Any],
) -> tuple[ParentalStatus, str | None]:
    # Restoration must preserve opaque assignment fields too. Use the same
    # verified writer, substituting only this candidate's original record.
    return edit_profile(router, logger, owner_id, add_device=str(client["device_id"]), restore_client=client)
