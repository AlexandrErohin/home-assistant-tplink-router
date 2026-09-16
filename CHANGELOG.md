# Changelog

## [2.40.0] - 2026-09-16

### Added

- **EX:** IoT / 6G / MLO support — `CLIENT_TYPES` for `X_TP_LanConnType` 5–6/8–10, `Status` band enables (`iot_*`, `wifi_6g_*`, `wifi_mlo_*`), `Connection.HOST_MLO*`, and `set_wifi` via `ioTssidEnable` / `mloEnable`; unknown conn types map to `Connection.UNKNOWN` and still count ([#226](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/pull/226), [HA #362](https://github.com/AlexandrErohin/home-assistant-tplink-router/issues/362)).
- **C6U / LuCI:** `set_ewan_connect(enable)` renews/releases the Ethernet WAN DHCP lease via `wan_ipv4_dynamic` (`operation=renew` / `release`); `Status.ewan_connected` from `conn_status` when `wan_ipv4_conntype` is `dhcp` ([#230](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/pull/230)).
- **C80:** `set_ewan_connect(enable)` brings Ethernet WAN up/down via `wan -linkUp` / `wan -linkDown` (`code=0`); `Status.ewan_connected` from WAN block `status` (`None` if the field is absent) ([#227](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/pull/227)).
- Added MR60X 2.0 to supported list

### Fixed

- **MR / VR:** `_merge_response` keeps values that contain `=` (e.g. SMS `content` with a URL query) by splitting each line on the first `=` only ([#231](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/pull/231)).
- **TL-SG108E:** `get_status()` fills `lan_ipv4_addr` from IP settings (`ipStr` / `ip`); lookup is best-effort so a failed IP page does not break port aggregates ([#229](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/pull/229)).
- **RE330 / C80:** when a router rejects an encrypted data body with `00006` (TL-WR844N and similar), retry the same request as plaintext and keep using plaintext for later calls; RE330 also falls back to DHCP-based status when device block `13` is absent ([#59](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/issues/59)).

## [2.39.0] - 2026-09-08

### Added
- Two-step config flow: host/credentials first, then optional features (VPN, trackers, DHCP reservations, and related settings) on a second step; credentials are validated before the custom step ([#404](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/404))
- Option to give each tracked client its own device entry (`tracker_as_device`, off by default) - tracked clients currently only get a device card if another integration already registered a device sharing their MAC, otherwise they're bare entities easy to overlook. Disabling the option later does not delete existing device-registry entries ([#397](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/397))
- DHCP reservations diagnostic sensor and `add_reservation` / `delete_reservation` services for supported c6u-family routers, with opt-in `support_dhcp_reservations` (default on) ([#405](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/405))
- E-WAN connect switch (DHCP Renew/Release) for MR/EX-family routers that report Ethernet WAN status ([#407](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/407))

## [2.38.0] - 2026-09-02

### Added
- TL-SG108E (and other clients with `get_port_status`) port monitoring: per-port link binary sensors and negotiated speed sensors with diagnostic attributes ([#394](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/394))
- Resilient data polling: configurable `scan_retries` / `scan_backoff`, async retries that do not hold the router lock during backoff, and non-fatal SMS inbox fetch ([#384](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/384))
- Switch to enable/disable the LAN IPv4 DHCP server on supported c6u-family routers ([#395](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/395))
- Configurable `scan_pause` (minutes; `0` = never auto re-enable) for the "Router data fetching" switch ([#139](https://github.com/AlexandrErohin/home-assistant-tplink-router/issues/139), [#400](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/400))
- Configurable `offline_timeout` grace period for device trackers when a client disappears from the router list ([#215](https://github.com/AlexandrErohin/home-assistant-tplink-router/issues/215), [#400](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/400))

### Fixed
- An offline/unreachable router no longer aborts setup of other TP-Link Router config entries; client discovery failures are isolated the same way ([#386](https://github.com/AlexandrErohin/home-assistant-tplink-router/issues/386), [#400](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/400))
- Device trackers keep last-known hostname/IP (and restored attributes) so events and entity names stay meaningful when the router reports blank values
- Port status refresh is gated like LTE (`port_status is not None`); shared port helpers and diagnostic entity metadata
- Permanent auth failures are not retried; session timeouts and similar transient errors are

## [2.37.0] - 2026-08-29

### Added
- Option to enable/disable device trackers per router (`support_tracker`) for setups with multiple routers (e.g. WAN router + separate AP), to avoid duplicate device entries ([#390](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/390))
- Async lock so switch actions, reboot, SMS send, and coordinator polling do not race on the same router session ([#392](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/392))

### Fixed
- Device trackers default to enabled when the option is missing (existing installs keep trackers) after the non-AP customisation work
- `send_sms` service now uses the same locked request path as other router actions
- Fixed MR / EX SMS (and USSD on MR): embedded `\n` / `\r` no longer corrupt the wire format; invalid newlines in phone numbers raise `ClientException` ([home-assistant-tplink-router#389](https://github.com/AlexandrErohin/home-assistant-tplink-router/issues/389))
- Fixed MR200 LTE: `get_lte_status()` correctly casts CGI string fields so LTE sensors (`network_type`, `sim_status`, signal level, statistics) work as expected ([TP-Link-Archer-C6U#214](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/pull/214))
- Fixed C6U wifi: `get_wifi()` no longer crashes when firmware reports channel as `'auto'` ([TP-Link-Archer-C6U#202](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/pull/202), [#201](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/issues/201))
