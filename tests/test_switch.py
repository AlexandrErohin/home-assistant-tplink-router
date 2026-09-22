from tplinkrouterc6u import Connection

from custom_components.tplink_router.switch import (
    DHCP_SERVER_SWITCH_TYPES,
    MLO_SWITCH_TYPES,
    STATUS_SWITCH_TYPES,
    WAN_SWITCH_TYPES,
)


def test_dhcp_server_switch_config():
    assert len(DHCP_SERVER_SWITCH_TYPES) == 1
    switch = DHCP_SERVER_SWITCH_TYPES[0]
    assert switch.property == "lan_ipv4_dhcp_enable"
    assert switch.coordinator_key == "status"
    assert switch.description.key == "lan_ipv4_dhcp_enable"
    assert switch.description.name == "LAN IPv4 DHCP Server"


def test_ewan_connect_switch_config():
    assert len(WAN_SWITCH_TYPES) == 1
    switch = WAN_SWITCH_TYPES[0]
    assert switch.property == "ewan_connected"
    assert switch.coordinator_key == "status"
    assert switch.description.key == "ewan_connect"
    assert switch.description.name == "E-WAN connect"
    assert switch.description.icon == "mdi:ethernet"


def test_mlo_2g_stays_in_status_switches():
    by_key = {s.description.key: s for s in STATUS_SWITCH_TYPES}
    switch = by_key["wifi_mlo_24g"]
    assert switch.property == "wifi_mlo_2g_enable"
    assert switch.description.name == "WIFI MLO 2.4G"
    assert Connection.HOST_MLO_2G.is_mlo_switch()
    assert "wifi_mlo_5g" not in by_key
    assert "wifi_mlo_6g" not in by_key


def test_mlo_5g_6g_switch_config():
    """5G/6G MLO switches are gated on status.wifi_mlo_{5,6}g_enable is not None."""
    assert len(MLO_SWITCH_TYPES) == 2
    expected = [
        ("wifi_mlo_5g_enable", "wifi_mlo_5g", "WIFI MLO 5G", Connection.HOST_MLO_5G),
        ("wifi_mlo_6g_enable", "wifi_mlo_6g", "WIFI MLO 6G", Connection.HOST_MLO_6G),
    ]
    for switch, (prop, key, name, conn) in zip(MLO_SWITCH_TYPES, expected):
        assert switch.property == prop
        assert switch.coordinator_key == "status"
        assert switch.description.key == key
        assert switch.description.name == name
        assert conn.is_mlo_switch()
        assert not conn.is_host_wifi()
