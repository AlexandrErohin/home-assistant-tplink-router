# Changelog

## [Unreleased]

### Added
- Option to give each tracked client its own device entry (`tracker_as_device`, off by default) - tracked clients currently only get a device card if another integration already registered a device sharing their MAC, otherwise they're bare entities easy to overlook ([#397](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/397))

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
