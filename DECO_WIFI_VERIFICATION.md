# Verified Deco Wi-Fi control

Classic Deco Wi-Fi operations use the companion library's verified API. The coordinator serializes each operation and applies recognized values returned by subsequent Wi-Fi reads, including state snapshots attached to verification errors. The switch displays observed state rather than substituting the requested boolean.

Existing `tplink_router` configuration entries, device identities, switch keys, and automation references are reused. SG and E4R clients retain their previous control behavior. Other router families and non-Wi-Fi switches retain their existing paths.

## Optional local app control

Classic Deco clients can configure `deco_tmp_username` and `deco_tmp_host_key_sha256` together. The first value is the app account's SHA-1 identifier; the second is its previously verified SSH server fingerprint in OpenSSH `SHA256:` format. The existing account password is reused. The web session name `admin` is independent from the app account identity. These values are sensitive configuration and must not be included in issue reports.

When both values are valid, setup configures the existing client locally without opening a new connection. Guest-band writes then use the app's local TMP-over-SSH channel. The router fingerprint is checked before one password authentication attempt. A fresh already matching state avoids a redundant command; otherwise one guest-only command is followed by bounded readback. A disconnected app channel permits read-only confirmation on the already authorized HTTP session. Neither an error nor a missing acknowledgement causes an automatic repeated write or an HTTP write fallback.

Both app fields are optional. Incomplete configuration is rejected explicitly. Options changes preserve existing app settings; clearing both app fields disables the optional transport. No additional device or entity is created for this control path.

## Companion release dependency

This contribution remains a draft until the companion library API is merged and released. For reproducible review, the manifest and test requirements temporarily pin the same immutable contribution revision, `9299dd0fa6897e858a189549c5e677bb35c51a6d`. Both Git references must be replaced with the published upstream package version before merging this integration change. No future release number is assumed.

Home Assistant pins the SSH dependency separately to `paramiko==3.5.0` for compatibility with integrations sharing its runtime. The standalone library retains its optional `deco-tmp` dependency group. The dependency policy is a point for maintainer review.

## Validation

Unit tests exercise configuration validation, options preservation, coordinator and switch behavior, session serialization, error snapshots, transport selection, and entity identity.

Hardware validation used Deco BE65 hardware 2.0, firmware 1.3.5 Build 26071712 Rel.18941, and Home Assistant Core 2026.11.3. Guest 2.4 GHz was enabled, disabled, and enabled again through the existing Home Assistant switch. Every service call succeeded and readback matched; host Wi-Fi and other guest-band states remained unchanged. The final enabled state was independently confirmed in the official Deco app.

Guest 5/6 GHz writes have unit coverage but were not exercised on hardware. Support on other Deco firmware still requires hardware validation.
