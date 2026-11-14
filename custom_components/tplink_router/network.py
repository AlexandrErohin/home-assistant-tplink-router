"""Admin-only network workspace backed by the existing coordinator."""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import entity_registry

from .const import DOMAIN
from .coordinator import TPLinkRouterCoordinator

PANEL_PATH = "tplink-network"
RESOURCE = "/tplink_router_frontend/network-panel.js"
DETAIL_FIELDS = (
    "packets_sent", "packets_received", "down_speed", "up_speed", "tx_rate", "rx_rate",
    "online_time", "traffic_usage", "signal",
)


def canonical_mac(value: str) -> str:
    return value.lower().replace("-", ":")


def snapshot(hass: HomeAssistant, coordinator: TPLinkRouterCoordinator) -> dict[str, Any]:
    """Return no browsing data and never confuse restored tracker state with online."""
    stamp = getattr(coordinator, "network_updated_at", None)
    age = (datetime.now().astimezone() - stamp).total_seconds() if stamp else None
    interval = coordinator.update_interval.total_seconds() if coordinator.update_interval else 60
    paused = coordinator.scan_stopped_at is not None
    stale = age is None or age > max(120, interval * 2)
    available = coordinator.last_update_success
    profiles = coordinator.parental_status
    profile_list, memberships, devices = [], {}, {}
    if profiles is not None and profiles.profiles is not None:
        for profile in profiles.profiles.values():
            members = []
            if profile.clients is not None:
                for client in profile.clients:
                    mac = canonical_mac(client.mac)
                    memberships.setdefault(mac, []).append(profile.owner_id)
                    members.append(mac)
                    devices[mac] = {
                        "mac": mac, "name": client.name or mac, "device_type": client.client_type,
                        "ip": None, "connection": "unknown", "band": None, "online": False, "cached": True,
                    }
            profile_list.append({
                "owner_id": profile.owner_id, "name": profile.name or profile.owner_id,
                "internet_blocked": profile.internet_blocked, "settings": profile.settings,
                "members": members, "assignments_valid": profile.clients is not None,
            })
    # Remember historical tracker data for explicit All/Offline views only.
    registry = entity_registry.async_get(hass)
    for entry in entity_registry.async_entries_for_config_entry(registry, coordinator.unique_id):
        state = hass.states.get(entry.entity_id)
        if entry.domain != "device_tracker" or state is None:
            continue
        attrs = state.attributes
        mac = attrs.get("mac")
        if not isinstance(mac, str) or "_mesh_" in entry.unique_id:
            continue
        mac = canonical_mac(mac)
        previous = devices.get(mac, {})
        devices[mac] = {
            **previous, "mac": mac, "name": attrs.get("host_name") or attrs.get("friendly_name") or mac,
            "ip": attrs.get("ip"), "connection": attrs.get("connection") or "unknown",
            "band": attrs.get("band"), "online": False, "cached": True,
            **{key: attrs[key] for key in DETAIL_FIELDS if key in attrs},
        }
    for device in coordinator.status.devices:
        mac = canonical_mac(device.macaddr)
        connection = device.type.get_type()
        devices[mac] = {
            **devices.get(mac, {}), "mac": mac, "name": device.hostname or mac, "ip": device.ipaddr,
            "connection": connection if connection in ("host", "guest", "wired") else "unknown",
            "band": device.type.get_band(), "online": device.active is True and available and not stale and not paused,
            "cached": not available or stale or paused, "reported_active": device.active is True,
            **{key: getattr(device, key) for key in DETAIL_FIELDS if getattr(device, key, None) is not None},
        }
    for mac, device in devices.items():
        device["owners"] = memberships.get(mac, [])
    return {
        "entry_id": coordinator.unique_id, "available": available, "paused": paused, "stale": stale,
        "updated_at": stamp.isoformat() if stamp else None, "age_seconds": age,
        "stale_after_seconds": max(120, interval * 2),
        "devices": list(devices.values()), "profiles": profile_list,
        "profiles_available": profiles is not None and profiles.profiles is not None,
        "memberships_available": (
            profiles is not None and profiles.profiles is not None
            and all(profile.clients is not None for profile in profiles.profiles.values())
        ),
        "capabilities": {
            "create_profile": profiles is not None, "reports": profiles is not None,
            "create_reason": (
                "Load live capacity and filter presets before creating an empty profile; assign devices afterward."
            ),
            "reports_reason": (
                "Reports are profile-wide, loaded only on request, and not stored in HA entity history. "
                "No byte-usage totals or individual-device browsing attribution are provided."
            ),
            "telemetry_note": (
                "Speeds, traffic and online time are raw router values. Units, period and resets are unverified; "
                "not daily or monthly totals."
            ),
        },
    }


def _coordinator(hass: HomeAssistant, entry_id: str) -> TPLinkRouterCoordinator:
    coord = hass.data.get(DOMAIN, {}).get(entry_id)
    if coord is None or hass.config_entries.async_get_entry(entry_id) is None:
        raise HomeAssistantError("Router is no longer loaded; refresh the workspace")
    return coord


@websocket_api.websocket_command({
    vol.Required("type"): "tplink_router/network",
    vol.Optional("entry_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_network(hass, connection, msg):
    if not connection.user.is_active:
        raise Unauthorized
    entries = hass.data.get(DOMAIN, {})
    if "entry_id" not in msg:
        connection.send_result(msg["id"], [
            {"entry_id": key, "name": entry.title}
            for key in entries if (entry := hass.config_entries.async_get_entry(key)) is not None
        ])
        return
    connection.send_result(msg["id"], snapshot(hass, _coordinator(hass, msg["entry_id"])))


@websocket_api.websocket_command({
    vol.Required("type"): "tplink_router/network_action",
    vol.Required("entry_id"): str,
    vol.Required("action"): vol.In((
        "refresh", "change_profile", "assign_devices", "create_profile",
        "rename_profile", "delete_profile", "schedule", "access",
    )),
    vol.Optional("mac"): vol.Match(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$"),
    vol.Optional("expected_owner"): str,
    vol.Optional("destination"): str,
    vol.Optional("macs"): vol.All(
        [vol.Match(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")], vol.Length(min=1, max=32),
    ),
    vol.Optional("owner_id"): str,
    vol.Optional("period"): vol.In(("workday", "weekend")),
    vol.Optional("kind"): vol.In(("bed_time", "time_limit")),
    vol.Optional("enabled"): bool,
    vol.Optional("minutes"): vol.Any(int, float),
    vol.Optional("begin"): str,
    vol.Optional("end"): str,
    vol.Optional("name"): vol.All(str, vol.Length(min=1, max=64)),
    vol.Optional("filter_level"): vol.In(("toddler", "tyke", "pre_teen", "teen", "adult")),
    vol.Optional("categories"): vol.All([vol.All(str, vol.Length(min=1, max=256))], vol.Length(max=256)),
    vol.Optional("expected_name"): str,
    vol.Optional("revision"): vol.Match(r"^[0-9a-f]{64}$"),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_action(hass, connection, msg):
    if not connection.user.is_active:
        raise Unauthorized
    coordinator = _coordinator(hass, msg["entry_id"])
    action = msg["action"]
    required = {
        "refresh": (), "change_profile": ("mac", "expected_owner", "destination"),
        "assign_devices": ("macs", "destination"),
        "create_profile": ("name", "filter_level", "categories"),
        "rename_profile": ("owner_id", "expected_name", "name"),
        "delete_profile": ("owner_id", "revision"),
        "schedule": ("owner_id", "period", "kind"), "access": ("owner_id", "enabled"),
    }[action]
    if any(key not in msg for key in required):
        raise HomeAssistantError("Required action fields are missing; refresh and retry")
    result = None
    if action == "refresh":
        await coordinator.async_request_refresh()
    elif action == "change_profile":
        await coordinator.change_device_profile(msg["mac"], msg["expected_owner"], msg["destination"])
    elif action == "access":
        await coordinator.set_profile_access(msg["owner_id"], msg["enabled"])
    elif action == "assign_devices":
        current = snapshot(hass, coordinator)
        if not current["available"] or current["stale"] or current["paused"] or not current["memberships_available"]:
            raise HomeAssistantError("Current memberships are unavailable; refresh before assigning selected devices")
        result = await coordinator.assign_profile_devices(msg["destination"], msg["macs"])
    elif action == "create_profile":
        _require_current(snapshot(hass, coordinator))
        result = await coordinator.create_parental_profile(msg["name"], msg["filter_level"], msg["categories"])
    elif action in ("rename_profile", "delete_profile"):
        _require_current(snapshot(hass, coordinator))
        await coordinator.manage_parental_profile(
            action, msg["owner_id"],
            **{key: msg[key] for key in ("name", "expected_name", "revision") if key in msg},
        )
    else:
        await coordinator.set_profile_schedule(
            msg["owner_id"], msg["period"], msg["kind"],
            **{key: msg[key] for key in ("enabled", "minutes", "begin", "end") if key in msg},
        )
    data = snapshot(hass, coordinator)
    if result is not None:
        data["creation_result" if action == "create_profile" else "assignment_result"] = result
    connection.send_result(msg["id"], data)


def _require_current(data: dict[str, Any]) -> None:
    if not data["available"] or data["stale"] or data["paused"] or not data["profiles_available"]:
        raise HomeAssistantError("Current profile data is unavailable; resume polling or refresh before continuing")


@websocket_api.websocket_command({
    vol.Required("type"): "tplink_router/profile_read",
    vol.Required("entry_id"): str,
    vol.Required("kind"): vol.In(("creation_options", "report", "delete_preview")),
    vol.Optional("owner_id"): vol.All(str, vol.Length(min=1, max=64)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_profile_read(hass, connection, msg):
    if not connection.user.is_active:
        raise Unauthorized
    coordinator = _coordinator(hass, msg["entry_id"])
    _require_current(snapshot(hass, coordinator))
    if msg["kind"] in ("report", "delete_preview") and "owner_id" not in msg:
        raise HomeAssistantError("Choose a profile before loading its report")
    connection.send_result(msg["id"], await coordinator.get_profile_feature(
        msg["kind"], msg.get("owner_id", ""),
    ))


async def setup_network_panel(hass: HomeAssistant) -> None:
    lock = hass.data.setdefault(f"{DOMAIN}_network_lock", asyncio.Lock())
    async with lock:
        await _register_network_panel(hass)


async def _register_network_panel(hass: HomeAssistant) -> None:
    if hass.data.get(f"{DOMAIN}_network_panel"):
        return
    if not hass.data.get(f"{DOMAIN}_network_registered"):
        await hass.http.async_register_static_paths([
            StaticPathConfig(
                RESOURCE, str(Path(__file__).parent / "frontend" / "network-panel.js"), False,
            ),
        ])
        websocket_api.async_register_command(hass, websocket_network)
        websocket_api.async_register_command(hass, websocket_action)
        websocket_api.async_register_command(hass, websocket_profile_read)
        hass.data[f"{DOMAIN}_network_registered"] = True
    await panel_custom.async_register_panel(
        hass, frontend_url_path=PANEL_PATH, webcomponent_name="tplink-network-panel",
        sidebar_title="Network & parental controls", sidebar_icon="mdi:lan",
        module_url=f"{RESOURCE}?v=3", require_admin=True,
    )
    hass.data[f"{DOMAIN}_network_panel"] = True


def unload_network_panel(hass: HomeAssistant) -> None:
    if hass.data.pop(f"{DOMAIN}_network_panel", False):
        frontend.async_remove_panel(hass, PANEL_PATH)
