from datetime import datetime
from types import SimpleNamespace

from homeassistant.helpers import device_registry as dr
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.tplink_router import _fire_sms_event
from custom_components.tplink_router.const import DOMAIN, EVENT_NEW_SMS


def _add_router(hass, mac):
    """Register a router device the way async_setup_entry does."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    identifiers = {(DOMAIN, mac)}
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers=identifiers, name=f"Router {mac}"
    )
    coordinator = SimpleNamespace(
        unique_id=entry.entry_id,
        device_info={"identifiers": identifiers},
        new_sms=[
            SimpleNamespace(
                sender="+100",
                content=f"hello from {mac}",
                received_at=datetime(2026, 11, 18, 10, 30),
            )
        ],
    )
    return entry, device, coordinator


async def test_sms_event_identifies_the_receiving_router(hass):
    entry, device, coordinator = _add_router(hass, "aa:bb:cc:dd:ee:01")
    events = async_capture_events(hass, EVENT_NEW_SMS)

    _fire_sms_event(hass, coordinator)
    await hass.async_block_till_done()

    assert [e.data for e in events] == [
        {
            "sender": "+100",
            "content": "hello from aa:bb:cc:dd:ee:01",
            "received_at": "2026-11-18T10:30:00",
            "device_id": device.id,
            "config_entry_id": entry.entry_id,
        }
    ]
    assert coordinator.new_sms == []


async def test_sms_events_from_two_routers_can_be_told_apart(hass):
    entry_a, device_a, coord_a = _add_router(hass, "aa:bb:cc:dd:ee:01")
    entry_b, device_b, coord_b = _add_router(hass, "aa:bb:cc:dd:ee:02")
    events = async_capture_events(hass, EVENT_NEW_SMS)

    _fire_sms_event(hass, coord_a)
    _fire_sms_event(hass, coord_b)
    await hass.async_block_till_done()

    assert [e.data["device_id"] for e in events] == [device_a.id, device_b.id]
    assert [e.data["config_entry_id"] for e in events] == [
        entry_a.entry_id,
        entry_b.entry_id,
    ]


async def test_sms_event_without_registered_device_has_no_device_id(hass):
    entry, device, coordinator = _add_router(hass, "aa:bb:cc:dd:ee:01")
    dr.async_get(hass).async_remove_device(device.id)
    events = async_capture_events(hass, EVENT_NEW_SMS)

    _fire_sms_event(hass, coordinator)
    await hass.async_block_till_done()

    assert events[0].data["device_id"] is None
    assert events[0].data["config_entry_id"] == entry.entry_id


async def test_no_sms_means_no_event(hass):
    _entry, _device, coordinator = _add_router(hass, "aa:bb:cc:dd:ee:01")
    coordinator.new_sms = []
    events = async_capture_events(hass, EVENT_NEW_SMS)

    _fire_sms_event(hass, coordinator)
    await hass.async_block_till_done()

    assert events == []
