"""Explicit HomeCare creation and private, on-demand reports; no polling storage."""
from copy import deepcopy
from hashlib import sha256
from json import dumps
import math
from typing import Any
from urllib.parse import urlencode

from tplinkrouterc6u import AbstractRouter

from .parental_control import (
    PERIODS, PROFILE_LIMIT_PATH, PROFILE_LIST_PATH, ParentalEditError, ParentalStatus,
    _app_map, _commit_profile, _profile_request, _verify_profile, _wire_profile, parse_profiles,
)

FILTER_PATH = "admin/smart_network?form=patrol_filter"
INSIGHTS_PATH = "admin/smart_network?form=patrol_insights"
HISTORY_PATH = "admin/smart_network?form=patrol_insights_history"
FILTER_LEVELS = ("toddler", "tyke", "pre_teen", "teen", "adult")


def _array(value: object, maximum: int) -> list:
    if value == {}:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Invalid HomeCare list")
    return value


def _categories(value: object) -> list[str]:
    result = _array(value, 256)
    if any(not isinstance(item, str) or not item or len(item) > 256 for item in result):
        raise ValueError("Invalid filter categories")
    if len(set(result)) != len(result):
        raise ValueError("Duplicate filter categories")
    return result


def profile_creation_options(router: AbstractRouter) -> dict[str, Any]:
    """No fallback capacity or invented presets when metadata cannot be read."""
    try:
        limits = _profile_request(router, PROFILE_LIMIT_PATH, "operation=read")
        if not isinstance(limits, dict):
            raise ValueError
        sizes = {}
        for key in ("profile_len", "category_len"):
            value = limits.get(key)
            if isinstance(value, str) and value.isascii() and value.isdigit():
                value = int(value)
            if type(value) is not int or not 1 <= value <= 256:
                raise ValueError
            sizes[key] = value
        filters = _array(_profile_request(router, FILTER_PATH, "operation=load"), 32)
        presets = []
        seen = set()
        for record in filters:
            if not isinstance(record, dict):
                raise ValueError
            level = record.get("filter_level")
            if level not in FILTER_LEVELS:
                continue  # The native metadata also contains an "all" category catalogue.
            if level in seen:
                raise ValueError
            seen.add(level)
            mandatory = _categories(record.get("categories_list"))
            selected = _categories(record.get("prefilter_list"))
            categories = list(dict.fromkeys([*selected, *mandatory]))
            if len(categories) > sizes["category_len"]:
                raise ValueError
            presets.append({"filter_level": level, "categories": categories})
        if not presets:
            raise ValueError
        profiles = parse_profiles(_profile_request(router, PROFILE_LIST_PATH, "operation=load"))
    except (ValueError, TypeError):
        raise ParentalEditError(
            "Profile creation metadata is invalid or incomplete; no defaults were substituted"
        ) from None
    return {
        "maximum": sizes["profile_len"], "remaining": max(0, sizes["profile_len"] - len(profiles)),
        "presets": presets,
    }


def _validate_name(name: str) -> None:
    if (
        not isinstance(name, str) or not name.strip() or len(name.encode("utf-16-le")) // 2 > 64
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise ParentalEditError("Profile name must contain 1–64 characters without control characters")


def create_profile(
    router: AbstractRouter, name: str, filter_level: str, expected_categories: list[str],
) -> tuple[ParentalStatus, dict[str, Any]]:
    """One native Store.insert, then verify the added profile and every incumbent."""
    _validate_name(name)
    options = profile_creation_options(router)
    preset = next((item for item in options["presets"] if item["filter_level"] == filter_level), None)
    if preset is None or preset["categories"] != expected_categories:
        raise ParentalEditError("Filter preset changed or is unavailable; reload creation options before saving")
    data = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
    profiles = parse_profiles(data)
    if len(profiles) >= options["maximum"]:
        raise ParentalEditError("Router profile capacity reached; no profile was created")
    if any(profile.name.casefold() == name.casefold() for profile in profiles.values()):
        raise ParentalEditError("A profile with this name already exists; choose a different name")
    if any(profile.clients is None for profile in profiles.values()):
        raise ParentalEditError("Existing memberships are incomplete; no profile was created")
    apps = _app_map(router)
    expected = {
        "name": name, "filter_level": filter_level, "client_list": [],
        "categories_list": deepcopy(preset["categories"]), "website_list": [],
        "time_limit": {"is_pro": False}, "bedtime": {"is_pro": False},
    }
    for period in PERIODS:
        expected.update({
            f"enable_{period}_time_limit": False, f"{period}_daily_time": "120",
            f"enable_{period}_bed_time": False,
            f"{period}_bed_time_begin": 1320, f"{period}_bed_time_end": 420,
        })
    expected = _wire_profile(expected, apps)
    payload = urlencode({
        "operation": "insert", "index": 0, "key": "add", "old": "add",
        "new": dumps(expected, separators=(",", ":"), ensure_ascii=False),
    })
    acknowledged = True
    try:
        _profile_request(router, PROFILE_LIST_PATH, payload, acknowledgement=True)
    except Exception:
        acknowledged = False
    try:
        confirmation = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
        status = ParentalStatus(parse_profiles(confirmation))
    except Exception:
        return ParentalStatus(None), {
            "confirmed": False, "owner_id": None,
            "error": "Creation outcome is unknown. Inspect profiles before retrying; no automatic retry was made.",
        }
    added = [row for row in confirmation if row["owner_id"] not in profiles]
    owner_id = added[0]["owner_id"] if len(added) == 1 and added[0]["name"] == name else None
    valid = False
    try:
        valid = owner_id is not None and len(confirmation) == len(data) + 1 and _verify_profile(
            {**expected, "owner_id": owner_id, "internet_blocked": False}, added[0], apps,
        ) and all(
            _verify_profile(
                _wire_profile(original, apps),
                next(row for row in confirmation if row["owner_id"] == original["owner_id"]), apps,
            ) for original in data
        )
    except (ValueError, StopIteration):
        valid = False
    confirmed = acknowledged and valid
    return status, {
        "confirmed": confirmed, "owner_id": owner_id,
        "error": None if confirmed else (
            "Creation was not fully confirmed. Inspect the profile list and protected settings before retrying. "
            "No retry or automatic deletion was made."
        ),
    }


def rename_profile(router, logger, owner_id: str, expected_name: str, name: str):
    _validate_name(name)
    data = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
    profiles = parse_profiles(data)
    profile = profiles.get(owner_id)
    if profile is None or profile.name != expected_name:
        raise ParentalEditError("Profile changed or was removed; refresh before renaming")
    if profile.clients is None:
        raise ParentalEditError("Existing memberships are incomplete; rename was not sent")
    if any(p.owner_id != owner_id and p.name.casefold() == name.casefold() for p in profiles.values()):
        raise ParentalEditError("A profile with this name already exists")
    if name == expected_name:
        return ParentalStatus(profiles), None
    index = next(i for i, row in enumerate(data) if row["owner_id"] == owner_id)
    return _commit_profile(router, logger, data, index, {**data[index], "name": name})


def _revision(record: dict[str, Any]) -> str:
    record = deepcopy(record)
    for key in ("key", "limit", "insights"):
        record.pop(key, None)
    if record.get("client_list") == {}:
        record["client_list"] = []
    for client in record.get("client_list", []):
        client.pop("online", None)
        client.pop("owner_id", None)
    return sha256(dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def deletion_preview(router: AbstractRouter, owner_id: str) -> dict[str, Any]:
    records = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
    profiles = parse_profiles(records)
    profile = profiles.get(owner_id)
    if profile is None or profile.clients is None:
        raise ParentalEditError("Profile or its memberships are unavailable; deletion is disabled")
    record = next(row for row in records if row["owner_id"] == owner_id)
    return {
        "owner_id": owner_id, "name": profile.name, "members": [c.mac for c in profile.clients],
        "revision": _revision(record),
    }


def delete_profile(
    router: AbstractRouter, owner_id: str, revision: str,
) -> tuple[ParentalStatus, str | None]:
    records = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
    profiles = parse_profiles(records)
    if owner_id not in profiles or any(p.clients is None for p in profiles.values()):
        raise ParentalEditError("Profile or memberships changed; reload deletion confirmation")
    index = next(i for i, row in enumerate(records) if row["owner_id"] == owner_id)
    original = records[index]
    if not isinstance(revision, str) or revision != _revision(original):
        raise ParentalEditError("Profile changed after confirmation was prepared; review deletion again")
    key = original.get("key", f"key-{index}")
    if not isinstance(key, (str, int)) or isinstance(key, bool):
        raise ParentalEditError("Invalid profile row key; deletion was not sent")
    apps = _app_map(router)
    # Native Store.remove uses traditional form arrays; one key/index encodes as scalars.
    payload = urlencode({"operation": "remove", "key": key, "index": index})
    acknowledged = True
    try:
        _profile_request(router, PROFILE_LIST_PATH, payload, acknowledgement=True)
    except Exception:
        acknowledged = False
    try:
        actual = _profile_request(router, PROFILE_LIST_PATH, "operation=load")
        status = ParentalStatus(parse_profiles(actual))
    except Exception:
        return ParentalStatus(None), "Deletion outcome is unknown; inspect profiles. No automatic retry was made."
    valid = False
    try:
        valid = owner_id not in status.profiles and len(actual) == len(records) - 1 and all(
            _verify_profile(
                _wire_profile(row, apps),
                next(item for item in actual if item["owner_id"] == row["owner_id"]), apps,
            ) for row in records if row["owner_id"] != owner_id
        )
    except (ValueError, StopIteration):
        valid = False
    return status, None if acknowledged and valid else (
        "Deletion was not fully confirmed; inspect profiles and remaining settings. "
        "No retry or automatic recreation was made."
    )


def _number(value: object, maximum: float) -> int | float:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            raise ValueError("Invalid report number") from None
    if (
        not isinstance(value, (int, float)) or isinstance(value, bool)
        or not math.isfinite(value) or not 0 <= value <= maximum
    ):
        raise ValueError("Invalid report number")
    return value


def _site(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError("Invalid report website")
    return value


def _blocked(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Invalid report block flag")
    return value


def parse_insights(data: object) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or "insights" not in data:
        raise ValueError("Invalid profile insights")
    days = _array(data["insights"], 7)
    result = []
    for day in days:
        if not isinstance(day, dict):
            raise ValueError("Invalid insight day")
        sites = []
        for site in _array(day.get("website_list"), 10000):
            if not isinstance(site, dict):
                raise ValueError("Invalid insight website")
            sites.append({
                "website": _site(site.get("website")), "minutes": _number(site.get("spend_online"), 1440),
                "blocked": _blocked(site.get("block")),
            })
        result.append({"minutes": _number(day.get("spend_online"), 1440), "websites": sites})
    return result


def parse_history(data: object) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or "history" not in data:
        raise ValueError("Invalid profile history")
    result = []
    for item in _array(data["history"], 10000):
        if not isinstance(item, dict):
            raise ValueError("Invalid history item")
        result.append({
            "website": _site(item.get("website")), "blocked": _blocked(item.get("block")),
            "timestamp": _number(item.get("access_timestamp"), 253402300799),
        })
    return result


def read_profile_report(router: AbstractRouter, owner_id: str) -> dict[str, Any]:
    """Return reports only to this caller; never retain them in coordinator state."""
    profiles = parse_profiles(_profile_request(router, PROFILE_LIST_PATH, "operation=load"))
    if owner_id not in profiles:
        raise ParentalEditError("Parental profile no longer exists")
    result = {"owner_id": owner_id}
    for key, path, parser in (
        ("insights", INSIGHTS_PATH, parse_insights), ("history", HISTORY_PATH, parse_history),
    ):
        try:
            data = parser(_profile_request(router, path, urlencode({"operation": "read", "owner_id": owner_id})))
            result[key] = {"status": "ok", "data": data}
        except NotImplementedError:
            result[key] = {"status": "unsupported", "error": "This report endpoint is unsupported"}
        except Exception:
            # Never include transport exception text: it can contain decrypted browsing records.
            result[key] = {"status": "unavailable", "error": "Report read failed or its schema is unrecognized"}
    return result
