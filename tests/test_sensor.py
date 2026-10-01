from types import SimpleNamespace

from homeassistant.const import EntityCategory
from tplinkrouterc6u import TPLinkSG108EClient, TplinkRouter

from custom_components.tplink_router.sensor import SENSOR_TYPES, _status_sensor_types


def test_sg108e_status_sensors():
    router = TPLinkSG108EClient.__new__(TPLinkSG108EClient)
    sensors = _status_sensor_types(router)
    assert [sensor.description.key for sensor in sensors] == [
        "wired_clients_total",
        "clients_total",
        "lan_ipv4_addr",
    ]
    assert [sensor.description.name for sensor in sensors] == [
        "Total ports",
        "Connected ports",
        "Management IPv4 Address",
    ]
    assert all(
        sensor.description.entity_category == EntityCategory.DIAGNOSTIC for sensor in sensors
    )

    status = SimpleNamespace(
        wired_total=8,
        clients_total=3,
        lan_ipv4_addr="lan",
    )
    assert [sensor.value(status) for sensor in sensors] == [8, 3, "lan"]


def test_non_sg_selects_sensor_types():
    router = TplinkRouter.__new__(TplinkRouter)
    assert _status_sensor_types(router) is SENSOR_TYPES
