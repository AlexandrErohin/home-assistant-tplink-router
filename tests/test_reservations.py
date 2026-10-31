from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import voluptuous as vol

from custom_components.tplink_router import (
    ADD_RESERVATION_SCHEMA,
    DELETE_RESERVATION_SCHEMA,
    get_coordinator_for_device,
)
from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.sensor import TPLinkRouterReservationsSensor


def test_reservations_sensor_native_value_and_attributes():
    reservation = SimpleNamespace(
        macaddr="AA-BB-CC-DD-EE-FF",
        ipaddr="192.168.1.50",
        hostname="phone",
        enabled=True,
    )
    coordinator = Mock()
    coordinator.unique_id = "entry-1"
    coordinator.device_info = {"identifiers": {("tplink_router", "mac")}}
    coordinator.reservations = [reservation]

    sensor = TPLinkRouterReservationsSensor.__new__(TPLinkRouterReservationsSensor)
    sensor.coordinator = coordinator
    sensor.hass = None
    sensor.entity_description = Mock(key="dhcp_reservations")

    assert sensor.native_value == 1
    assert sensor.extra_state_attributes == {
        "reservations": [
            {
                "mac": "AA-BB-CC-DD-EE-FF",
                "ip": "192.168.1.50",
                "hostname": "phone",
                "enabled": True,
            }
        ]
    }


def test_reservations_sensor_empty_when_none_or_empty():
    coordinator = Mock()
    coordinator.reservations = None
    sensor = TPLinkRouterReservationsSensor.__new__(TPLinkRouterReservationsSensor)
    sensor.coordinator = coordinator
    assert sensor.native_value is None

    coordinator.reservations = []
    assert sensor.native_value == 0
    assert sensor.extra_state_attributes == {"reservations": []}


def test_add_reservation_schema_validates_mac_and_ip():
    data = ADD_RESERVATION_SCHEMA(
        {
            "device": "abc123",
            "mac": "aa:bb:cc:dd:ee:ff",
            "ip": "192.168.1.20",
            "comment": "laptop",
            "enable": True,
        }
    )
    assert data["mac"] == "aa:bb:cc:dd:ee:ff"
    assert data["ip"] == "192.168.1.20"


def test_add_reservation_schema_rejects_bad_mac():
    with pytest.raises(vol.Invalid):
        ADD_RESERVATION_SCHEMA(
            {"device": "abc123", "mac": "bad", "ip": "192.168.1.20"}
        )


def test_delete_reservation_schema_requires_mac():
    data = DELETE_RESERVATION_SCHEMA(
        {"device": "abc123", "mac": "AA-BB-CC-DD-EE-FF"}
    )
    assert data["mac"] == "AA-BB-CC-DD-EE-FF"
    with pytest.raises(vol.Invalid):
        DELETE_RESERVATION_SCHEMA({"device": "abc123", "mac": "nope"})


def test_get_coordinator_for_device_uses_config_entry_scoped_lookup():
    entry = SimpleNamespace(entry_id="entry-1", domain=DOMAIN)
    device = SimpleNamespace(id="dev-1")
    coordinator = Mock()
    coordinator.router = Mock(spec=["add_ipv4_reservation"])
    coordinator.support_dhcp_reservations = True

    hass = Mock()
    hass.data = {DOMAIN: {"entry-1": coordinator}}

    # create=True: helper exists only on Home Assistant >= 2026.8
    with patch(
        "custom_components.tplink_router.device_registry.async_get_device_and_config_entry_for_domain",
        return_value=(device, entry),
        create=True,
    ) as lookup:
        assert (
            get_coordinator_for_device(hass, "dev-1", "add_ipv4_reservation")
            is coordinator
        )
    lookup.assert_called_once_with(hass, "dev-1", domain=DOMAIN)


def test_get_coordinator_for_device_returns_none_when_device_missing():
    hass = Mock()
    hass.data = {DOMAIN: {}}
    with patch(
        "custom_components.tplink_router.device_registry.async_get_device_and_config_entry_for_domain",
        return_value=(None, None),
        create=True,
    ):
        assert get_coordinator_for_device(hass, "missing", "send_sms") is None
    assert get_coordinator_for_device(hass, None, "send_sms") is None


def test_get_coordinator_for_device_rejects_disabled_dhcp_reservations():
    entry = SimpleNamespace(entry_id="entry-1", domain=DOMAIN)
    coordinator = Mock()
    coordinator.router = Mock(spec=["add_ipv4_reservation"])
    coordinator.support_dhcp_reservations = False
    hass = Mock()
    hass.data = {DOMAIN: {"entry-1": coordinator}}

    with patch(
        "custom_components.tplink_router.device_registry.async_get_device_and_config_entry_for_domain",
        return_value=(SimpleNamespace(id="dev-1"), entry),
        create=True,
    ):
        assert (
            get_coordinator_for_device(hass, "dev-1", "add_ipv4_reservation") is None
        )
