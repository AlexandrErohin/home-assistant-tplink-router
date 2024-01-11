# Tp-Link router integration for Home Assistant
Home Assistant component for TP-Link router administration based on the [TP-Link Router API](https://github.com/AlexandrErohin/TP-Link-Archer-C6U)

See [Supported routers](#supports)

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/sensors.png" width="70%">

## Components
### Switches
 - Router Reboot
 - 2.4Ghz main wifi Enable/Disable
 - 5Ghz main wifi Enable/Disable
 - 2.4Ghz guest wifi Enable/Disable
 - 5Ghz guest wifi Enable/Disable
 - 2.4Ghz IoT wifi network Enable/Disable
 - 5Ghz IoT wifi network Enable/Disable

### Sensors
 - Total amount of wired clients
 - Total amount of main wifi clients
 - Total amount of guest wifi clients
 - Total amount of all connected clients
 - CPU used
 - Memory used

### Device Tracker
 - Track clients by MAC address across 2.4Ghz, 5Ghz guest and main wifi with connection information

## Installation

### HACS (recommended)

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

1. Go to the <b>Hacs</b>-><b>Integrations</b>.
2. Add this repository (https://github.com/AlexandrErohin/home-assistant-tplink-router) as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/)
4. Click on `+ Explore & Download Repositories`, search for `TP-Link Router`.
5. Search for `TP-Link Router`.
6. Navigate to `TP-Link Router` integration
7. Press `DOWNLOAD` and in the next window also press `DOWNLOAD`.
8. After download, restart Home Assistant.

### Manual

1. Locate the `custom_components` directory in your Home Assistant configuration directory. It may need to be created.
2. Copy the `custom_components/tplink_router` directory into the `custom_components` directory.
3. Restart Home Assistant.

## Configuration
TP-Link Router is configured via the GUI. See [the HA docs](https://www.home-assistant.io/getting-started/integration/) for more details.

The default data is preset already.

If you use `https` connection to your router you may get error `certificate verify failed: EE certificate key too weak`. To fix this - unset `Verify ssl`

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/config_flow.png" width="48%">

1. Go to the <b>Settings</b>-><b>Devices & services</b>.
2. Click on `+ ADD INTEGRATION`, search for `TP-Link Router`.
3. Fill Password.
4. Click `SUBMIT`

## <a id="supports">Supported routers</a>
### Fully tested Hardware Versions
- Archer A7 V5
- Archer AX10 v1.0
- Archer AX55 V1.60
- Archer AX73 V1
- Archer AX3000 V1
- Archer AX11000 V1
- Archer C6 v2.0
- Archer C6 v3.0
- Archer C6U v1.0
- Archer C7 v5.0

### Not fully tested Hardware Versions
- AD7200 V2
- Archer A6 (V2 and V3)
- Archer A9 V6
- Archer A10 (V1 and V2)
- Archer A20 (V1, V3)
- Archer AX50 V1
- Archer AX6000 V1
- Archer C7 V4
- Archer C8 (V3 and V4)
- Archer C9 (V4 and V5)
- Archer C59 V2
- Archer C90 V6
- Archer C900 V1
- Archer C1200 V3 (V2 - should work, but not have been tested)
- Archer C1900 V2
- Archer C2300 (V1, V2)
- Archer C4000 (V2 and V3)
- Archer C5400 V2
- Archer C5400X V1
- TL-WR1043N V5

Please let me know if you have tested integration with one of this or other model. Open an issue with info about router's model, hardware and firmware versions.
