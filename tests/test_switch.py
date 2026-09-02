from custom_components.tplink_router.switch import DHCP_SERVER_SWITCH_TYPES


def test_dhcp_server_switch_config():
    assert len(DHCP_SERVER_SWITCH_TYPES) == 1
    switch = DHCP_SERVER_SWITCH_TYPES[0]
    assert switch.property == "lan_ipv4_dhcp_enable"
    assert switch.coordinator_key == "status"
    assert switch.description.key == "lan_ipv4_dhcp_enable"
    assert switch.description.name == "LAN IPv4 DHCP Server"
