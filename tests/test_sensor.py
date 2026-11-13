from types import SimpleNamespace

from tplinkrouterc6u import PortStatus, RouterPortStatus

from custom_components.tplink_router.sensor import TPLinkRouterPortLinkSpeedSensor, _status_sensor_types


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
        "wan_ipv4_uptime": None,
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


def test_status_sensors_include_wan_ipv4_uptime():
    status = _status(wan_ipv4_uptime=3600)
    sensors = _status_sensor_types(status)
    assert [sensor.description.key for sensor in sensors] == ["wan_ipv4_uptime"]
    assert sensors[0].value(status) == 3600


def test_status_sensors_empty_when_all_none():
    assert _status_sensor_types(_status()) == ()


def _port_coordinator(ports):
    return SimpleNamespace(unique_id="test", device_info=None, port_status=ports, last_update_success=True)


def test_port_link_speed_sensor_router_port():
    # Router ports (Archer C5400X) come as RouterPortStatus: only link, speed and duplex
    ports = [RouterPortStatus(port=0, link_up=True, negotiated_speed=1000, negotiated_duplex="full")]
    sensor = TPLinkRouterPortLinkSpeedSensor(_port_coordinator(ports), 0)
    assert sensor.native_value == 1000
    assert sensor.extra_state_attributes == {"negotiated_duplex": "full"}


def test_port_link_speed_sensor_switch_port():
    # Switch ports (TL-SG108E) come as PortStatus and keep all their attributes
    port = PortStatus(
        port=1, enabled=True, link_up=True, auto_negotiation=True, configured_speed=1000, configured_duplex="full",
        negotiated_speed=1000, negotiated_duplex="full", flow_control_enabled=False, flow_control_active=False,
        lag=0, tx_good_packets=10, tx_bad_packets=0, rx_good_packets=20, rx_bad_packets=0,
    )
    sensor = TPLinkRouterPortLinkSpeedSensor(_port_coordinator([port]), 1)
    assert sensor.native_value == 1000
    assert sensor.extra_state_attributes == {
        "negotiated_duplex": "full",
        "enabled": True,
        "auto_negotiation": True,
        "configured_speed": 1000,
        "configured_duplex": "full",
        "flow_control_enabled": False,
        "flow_control_active": False,
        "lag": 0,
        "tx_good_packets": 10,
        "tx_bad_packets": 0,
        "rx_good_packets": 20,
        "rx_bad_packets": 0,
    }
