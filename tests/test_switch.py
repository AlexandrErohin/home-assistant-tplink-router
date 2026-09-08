from custom_components.tplink_router.switch import (
    DHCP_SERVER_SWITCH_TYPES,
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
