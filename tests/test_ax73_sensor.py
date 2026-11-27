from types import SimpleNamespace

from custom_components.tplink_router.ax73_sensor import AX73WifiClientsSensor, update_ax73_client_sensors


def _client(band="5G", active=True):
    return SimpleNamespace(
        type=SimpleNamespace(get_band=lambda: band),
        active=active,
        macaddr="02-00-00-00-00-01",
        ipaddr="192.0.2.10",
        hostname="example-client",
        rx_rate=1201000,
        tx_rate=-1,
        signal=-57,
        packets_sent=0,
        packets_received=None,
        online_time=30,
        ap_name=None,
    )


def test_ax73_wifi_summary_excludes_wired_and_inactive_clients():
    coordinator = SimpleNamespace(
        unique_id="router", device_info=None, last_update_success=True,
        status=SimpleNamespace(devices=[_client(), _client(band=None), _client(active=False)]),
    )
    sensor = AX73WifiClientsSensor(coordinator)
    assert sensor.native_value == 1
    client = sensor.extra_state_attributes["clients"][0]
    assert client["band"] == "5G"
    assert client["rx_rate"] == 1201
    assert client["tx_rate"] is None
    assert client["signal"] == -57


def test_ax73_client_entities_discover_late_metrics_and_drop_stale_values():
    client = _client()
    coordinator = SimpleNamespace(
        unique_id="router", device_info=None, last_update_success=True,
        status=SimpleNamespace(devices=[client]),
    )
    entities = []
    tracked = set()
    update_ax73_client_sensors(coordinator, entities.extend, tracked)
    sensors = {sensor.entity_description.key: sensor for sensor in entities}
    assert set(sensors) == {"band", "rx_rate", "signal", "packets_sent", "online_time"}
    assert sensors["rx_rate"].native_value == 1201
    assert sensors["rx_rate"].unique_id == "router_ax73_02-00-00-00-00-01_rx_rate"
    assert not sensors["rx_rate"].entity_registry_enabled_default
    assert sensors["packets_sent"].native_value == 0

    client.tx_rate = 866700
    update_ax73_client_sensors(coordinator, entities.extend, tracked)
    assert len(entities) == 6
    assert entities[-1].native_value == 866.7

    client.active = False
    assert not entities[-1].available
    assert entities[-1].native_value is None
