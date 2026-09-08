from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import voluptuous as vol

from custom_components.tplink_router import ADD_RESERVATION_SCHEMA, DELETE_RESERVATION_SCHEMA
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
