# Changelog

## [Unreleased]

### Added
- Option to give each tracked client its own device entry (`tracker_as_device`, off by default) - tracked clients currently only get a device card if another integration already registered a device sharing their MAC, otherwise they're bare entities easy to overlook ([#397](https://github.com/AlexandrErohin/home-assistant-tplink-router/pull/397))

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
