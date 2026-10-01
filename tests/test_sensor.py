from types import SimpleNamespace

from custom_components.tplink_router.sensor import SENSOR_TYPES, _status_sensor_types


def _status(**overrides):
    fields = {
        "guest_clients_total": None,
        "wifi_clients_total": None,
        "wired_total": None,
        "iot_clients_total": None,
        "clients_total": None,
        "cpu_usage": None,
        "mem_usage": None,
        "conn_type": None,
        "wan_ipv4_addr": None,
        "lan_ipv4_addr": None,
        "wan_ipv6_enabled": None,
        "wan_ipv6_addr": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_status_sensors_include_only_non_none_values():
    status = _status(
        wired_total=8,
        clients_total=3,
        lan_ipv4_addr="192.168.0.1",
        wifi_clients_total=0,
    )
    sensors = _status_sensor_types(status)
    assert [sensor.description.key for sensor in sensors] == [
        "wifi_clients_total",
        "wired_clients_total",
        "clients_total",
        "lan_ipv4_addr",
    ]
    assert [sensor.value(status) for sensor in sensors] == [0, 8, 3, "192.168.0.1"]


def test_status_sensors_skip_none_values():
    status = _status(cpu_usage=0.25, mem_usage=None, wan_ipv4_addr=None)
    sensors = _status_sensor_types(status)
    assert [sensor.description.key for sensor in sensors] == ["cpu_used"]
    assert sensors[0].value(status) == 25.0


def test_status_sensors_empty_when_all_none():
    assert _status_sensor_types(_status()) == ()
