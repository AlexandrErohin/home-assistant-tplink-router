import logging
from datetime import datetime
from unittest.mock import Mock, patch

from custom_components.tplink_router.device_tracker import (
    TPLinkTracker,
    mark_offline_if_expired,
    update_items,
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
