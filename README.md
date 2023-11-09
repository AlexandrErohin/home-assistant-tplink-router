# home-assistant-tplink-router
Home Assistant component for complete router administration of the TP Link Archer C6U based on the [TP-Link Archer C6U](https://github.com/AlexandrErohin/TP-Link-Archer-C6U)

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/sensor.png" width="48%"> <img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/switch.png" width="48%">

## Components
### Switches
 - Router Reboot
 - 2.4Ghz main wifi Enable/Disable
 - 5Ghz main wifi Enable/Disable
 - 2.4Ghz guest wifi Enable/Disable
 - 5Ghz guest wifi Enable/Disable

### Sensors
 - Total amount of wired clients
 - Total amount of main wifi clients
 - Total amount of guest wifi clients
 - Total amount of all connected clients

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
Midea Smart AC is configured via the GUI. See [the HA docs](https://www.home-assistant.io/getting-started/integration/) for more details.

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/config_flow.png" width="48%">

1. Go to the <b>Settings</b>-><b>Devices & services</b>.
2. Click on `+ ADD INTEGRATION`, search for `TP-Link Router`.
3. Fill IP address and Password.
4. Click `SUBMIT`
