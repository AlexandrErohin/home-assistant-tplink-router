import logging

from custom_components.tplink_router.device_tracker import TPLinkTracker


class FakeDevice:
    def __init__(self, hostname="", ip="0.0.0.0"):
        self.hostname = hostname
        self.ipaddr = ip
        self.active = True


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
