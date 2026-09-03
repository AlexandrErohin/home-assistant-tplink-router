import logging
from datetime import datetime
from unittest.mock import Mock, patch

from custom_components.tplink_router.device_tracker import (
    TPLinkMeshTracker,
    TPLinkTracker,
    mark_offline_if_expired,
    update_items,
    update_mesh_items,
)


class FakeDeviceType:
    def get_type(self):
        return "wifi"

    def get_band(self):
        return "5g"


class FakeDevice:
    def __init__(self, macaddr="", hostname="", ip="0.0.0.0", active=True):
        self.macaddr = macaddr
        self.hostname = hostname
        self.ipaddr = ip
        self.active = active
        self.type = FakeDeviceType()
        self.packets_sent = 0
        self.packets_received = 0
        self.down_speed = None
        self.up_speed = None
        self.tx_rate = None
        self.rx_rate = None
        self.online_time = None
        self.traffic_usage = None
        self.signal = None
        self.ap_name = None


class FakeHass:
    data = {}
    loop = None


class FakeCoordinator:
    hass = FakeHass()
    unique_id = "entry-1"

    def __init__(self):
        self.logger = logging.getLogger("test")

    def async_add_listener(self, callback):
        pass


def build_tracker():
    coord = FakeCoordinator()
    tracker = TPLinkTracker.__new__(TPLinkTracker)
    tracker.coordinator = coord
    tracker.device = None
    tracker._mac = "AA:BB:CC:DD:EE:FF"
    tracker.active = False
    tracker._restored_attributes = {}
    tracker._last_hostname = ""
    tracker._last_ip_address = ""
    return tracker


def test_remember_keeps_last_meaningful_hostname_and_ip():
    tracker = build_tracker()
    tracker._remember(FakeDevice(hostname="phone", ip="192.168.1.50"))
    assert tracker._last_hostname == "phone"
    assert tracker._last_ip_address == "192.168.1.50"


def test_remember_ignores_blank_values():
    tracker = build_tracker()
    tracker._remember(FakeDevice(hostname="phone", ip="192.168.1.50"))
    tracker._remember(FakeDevice(hostname="", ip="0.0.0.0"))
    assert tracker._last_hostname == "phone"
    assert tracker._last_ip_address == "192.168.1.50"


def test_ip_address_falls_back_to_last_known_when_blank():
    tracker = build_tracker()
    tracker._remember(FakeDevice(hostname="phone", ip="192.168.1.50"))
    tracker.device = FakeDevice(hostname="", ip="0.0.0.0")
    assert tracker.ip_address == "192.168.1.50"


def test_hostname_falls_back_to_last_known_when_blank():
    tracker = build_tracker()
    tracker._remember(FakeDevice(hostname="phone", ip="192.168.1.50"))
    tracker.device = FakeDevice(hostname="", ip="192.168.1.60")
    assert tracker.hostname == "phone"


def test_hostname_falls_back_to_restored_when_device_blank():
    tracker = build_tracker()
    tracker._restored_attributes = {"hostname": "restored-phone", "ip_address": "192.168.1.70"}
    tracker.device = FakeDevice(hostname="", ip="0.0.0.0")
    assert tracker.hostname == "restored-phone"
    assert tracker.ip_address == "192.168.1.70"
    assert tracker.name == "restored-phone"


def test_mark_offline_if_expired_with_zero_timeout_is_immediate():
    tracker = build_tracker()
    tracker.last_seen = datetime(2026, 1, 1, 12, 0, 0)
    now = datetime(2026, 1, 1, 12, 0, 30)
    assert mark_offline_if_expired(tracker, now, timeout_seconds=0) is True


def test_mark_offline_if_expired_respects_timeout():
    tracker = build_tracker()
    tracker.last_seen = datetime(2026, 1, 1, 12, 0, 0)
    now = datetime(2026, 1, 1, 12, 2, 0)  # 2 minutes later
    assert mark_offline_if_expired(tracker, now, timeout_seconds=300) is False


def test_mark_offline_if_expired_fires_after_timeout():
    tracker = build_tracker()
    tracker.last_seen = datetime(2026, 1, 1, 12, 0, 0)
    now = datetime(2026, 1, 1, 12, 6, 0)  # 6 minutes later
    assert mark_offline_if_expired(tracker, now, timeout_seconds=300) is True


def test_mark_offline_if_expired_at_exactly_timeout():
    tracker = build_tracker()
    tracker.last_seen = datetime(2026, 1, 1, 12, 0, 0)
    now = datetime(2026, 1, 1, 12, 5, 0)  # exactly at the timeout boundary
    assert mark_offline_if_expired(tracker, now, timeout_seconds=300) is True


def test_update_items_defers_offline_marking_until_timeout():
    class FakeDT:
        current = datetime(2026, 1, 1, 12, 0, 0)

        @classmethod
        def now(cls):
            return cls.current

    device = FakeDevice(macaddr="AA:BB:CC:DD:EE:FF", hostname="phone", ip="192.168.1.10", active=True)

    class FakeStatus:
        devices = [device]

    class FakeHass:
        def __init__(self):
            self.bus = Mock()

    class FakeCoordinator:
        def __init__(self):
            self.status = FakeStatus()
            self.offline_timeout_seconds = 300
            self.hass = FakeHass()

        def async_add_listener(self, cb):
            pass

    coord = FakeCoordinator()
    tracked = {}

    with patch("custom_components.tplink_router.device_tracker.datetime", FakeDT):
        update_items(coord, Mock(), tracked)

    tracker = tracked["AA:BB:CC:DD:EE:FF"]
    assert tracker.is_connected is True

    coord.status.devices = []
    FakeDT.current = datetime(2026, 1, 1, 12, 2, 0)  # 2 min later, within 300s grace
    with patch("custom_components.tplink_router.device_tracker.datetime", FakeDT):
        update_items(coord, Mock(), tracked)
    assert tracker.is_connected is True
    coord.hass.bus.fire.assert_not_called()

    FakeDT.current = datetime(2026, 1, 1, 12, 6, 0)  # 6 min later, past grace
    with patch("custom_components.tplink_router.device_tracker.datetime", FakeDT):
        update_items(coord, Mock(), tracked)
    assert tracker.is_connected is False
    offline_events = [
        c.args[0] for c in coord.hass.bus.fire.call_args_list
        if c.args[0] == "tplink_router_device_offline"
    ]
    assert len(offline_events) == 1


class FakeMeshNode:
    """Mirrors the fields of tplinkrouterc6u MeshDevice used by the tracker."""

    def __init__(self, mac, name="", model="", role="satellite_router", status="connected",
                 parent_mac=None, ip="10.1.1.2", client_num=0, signal_strength=None,
                 support_reboot=None, device_type="RangeExtender", connect_type="wireless"):
        self.macaddr = mac
        self.name = name
        self.model = model
        self.role = role
        self.status = status
        self.parent_macaddr = parent_mac
        self.ipaddr = ip
        self.client_num = client_num
        self.signal_strength = signal_strength
        self.support_reboot = support_reboot
        self.device_type = device_type
        self.connect_type = connect_type
        self.location = None
        self.mesh_type = "easymesh"
        self.vendor = "TP-Link"

    @property
    def is_main_router(self):
        return self.role == "main_router"


def build_mesh_tracker(node):
    tracker = TPLinkMeshTracker.__new__(TPLinkMeshTracker)
    tracker.coordinator = FakeCoordinator()
    tracker.node = node
    tracker._mac = node.macaddr
    tracker._name = node.name or node.model or node.macaddr
    tracker._last_ip_address = node.ipaddr or ""
    return tracker


class FakeMeshCoordinator:
    hass = FakeHass()
    unique_id = "entry-1"

    def __init__(self, nodes):
        self.mesh_devices = nodes


def test_update_mesh_items_creates_one_tracker_per_node():
    coord = FakeMeshCoordinator([
        FakeMeshNode("24-00-00-00-00-01", name="Main", role="main_router"),
        FakeMeshNode("24-00-00-00-00-02", name="Satellite"),
    ])
    tracked = {}

    update_mesh_items(coord, Mock(), tracked)

    assert sorted(tracked) == ["24-00-00-00-00-01", "24-00-00-00-00-02"]
    assert tracked["24-00-00-00-00-01"].is_connected is True


def test_update_mesh_items_reuses_existing_trackers():
    coord = FakeMeshCoordinator([FakeMeshNode("24-00-00-00-00-01", name="Main")])
    tracked = {}
    add_entities = Mock()

    update_mesh_items(coord, add_entities, tracked)
    first = tracked["24-00-00-00-00-01"]
    coord.mesh_devices = [FakeMeshNode("24-00-00-00-00-01", name="Main", client_num=7)]
    update_mesh_items(coord, add_entities, tracked)

    assert tracked["24-00-00-00-00-01"] is first
    assert tracked["24-00-00-00-00-01"].extra_state_attributes["client_num"] == 7
    # The entity is added once, not on every refresh
    assert add_entities.call_count == 1


def test_update_mesh_items_marks_missing_node_disconnected_without_removing_it():
    coord = FakeMeshCoordinator([FakeMeshNode("24-00-00-00-00-02", name="Satellite")])
    tracked = {}
    update_mesh_items(coord, Mock(), tracked)
    assert tracked["24-00-00-00-00-02"].is_connected is True

    coord.mesh_devices = []
    update_mesh_items(coord, Mock(), tracked)

    assert "24-00-00-00-00-02" in tracked
    assert tracked["24-00-00-00-00-02"].is_connected is False
    assert tracked["24-00-00-00-00-02"].extra_state_attributes == {}


def test_update_mesh_items_skips_nodes_without_mac():
    coord = FakeMeshCoordinator([FakeMeshNode("", name="No MAC")])
    tracked = {}

    update_mesh_items(coord, Mock(), tracked)

    assert tracked == {}


def test_update_mesh_items_handles_absent_node_list():
    coord = FakeMeshCoordinator(None)
    tracked = {}

    update_mesh_items(coord, Mock(), tracked)

    assert tracked == {}


def test_mesh_tracker_unique_id_cannot_collide_with_a_client():
    node = FakeMeshNode("24-00-00-00-00-02", name="Satellite")
    tracker = build_mesh_tracker(node)

    assert tracker.unique_id == "entry-1_tplink_router_mesh_24-00-00-00-00-02"
    assert tracker.unique_id != f"entry-1_tplink_router_{node.macaddr}"


def test_mesh_tracker_exposes_the_deco_attribute_names():
    node = FakeMeshNode(
        "24-00-00-00-00-02", name="Satellite", model="Archer AX55",
        device_type="WirelessRouter", connect_type="wireless",
        parent_mac="24-00-00-00-00-01", client_num=9, signal_strength=2,
        support_reboot=True,
    )
    attributes = build_mesh_tracker(node).extra_state_attributes

    assert attributes["device_type"] == "WirelessRouter"
    assert attributes["device_model"] == "Archer AX55"
    assert attributes["connection_type"] == "wireless"
    assert attributes["status"] == "connected"
    assert attributes["parent_mac"] == "24-00-00-00-00-01"
    assert attributes["client_num"] == 9
    assert attributes["support_reboot"] is True
    assert attributes["is_main_router"] is False


def test_mesh_tracker_does_not_publish_the_bar_level_as_signal():
    """Clients report signal in dBm; a node reports a 1 to 3 level, so the keys differ."""
    node = FakeMeshNode("24-00-00-00-00-02", signal_strength=3)
    attributes = build_mesh_tracker(node).extra_state_attributes

    assert attributes["signal_level"] == 3
    assert "signal" not in attributes


def test_mesh_tracker_omits_fields_the_main_router_does_not_report():
    node = FakeMeshNode("24-00-00-00-00-01", name="Main", role="main_router",
                        device_type="WirelessRouter", connect_type=None)
    attributes = build_mesh_tracker(node).extra_state_attributes

    assert attributes["is_main_router"] is True
    assert "parent_mac" not in attributes
    assert "signal_level" not in attributes
    assert "support_reboot" not in attributes


def test_mesh_tracker_keeps_last_known_ip_when_the_node_drops_out():
    node = FakeMeshNode("24-00-00-00-00-02", ip="10.1.1.63")
    tracker = build_mesh_tracker(node)
    assert tracker.ip_address == "10.1.1.63"

    tracker.node = None

    assert tracker.ip_address == "10.1.1.63"
    assert tracker.is_connected is False
