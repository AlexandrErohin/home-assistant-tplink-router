# Tp-Link router integration for Home Assistant
Home Assistant component for TP-Link router administration based on the [TP-Link Router API](https://github.com/AlexandrErohin/TP-Link-Archer-C6U)

See [Supported routers](#supports)

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/sensors.png" width="48%"> <img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/switches.png" width="48%">

## Components
### Switches
 - Router Reboot
 - 2.4Ghz host wifi Enable/Disable
 - 5Ghz host wifi Enable/Disable
 - 6Ghz host wifi Enable/Disable
 - 2.4Ghz guest wifi Enable/Disable
 - 5Ghz guest wifi Enable/Disable
 - 6Ghz guest wifi Enable/Disable
 - 2.4Ghz IoT wifi network Enable/Disable
 - 5Ghz IoT wifi network Enable/Disable
 - 6Ghz IoT wifi network Enable/Disable

### Sensors
 - Total amount of wired clients
 - Total amount of IoT clients
 - Total amount of host wifi clients
 - Total amount of guest wifi clients
 - Total amount of all connected clients
 - CPU used
 - Memory used

### Device Tracker
 - Track connected to router devices by MAC address with connection information

To find your device - Go to `Developer tools` and search for your MAC address - you’ll find sensor like `device_tracker.YOUR_MAC` or `device_tracker.YOUR_PHONE_NAME`.

## Installation

### HACS (recommended)

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

[![Install quickly via a HACS link](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=AlexandrErohin&repository=home-assistant-tplink-router&category=integration)

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

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/config_flow.png" width="48%">

1. Go to the <b>Settings</b>-><b>Devices & services</b>.
2. Click on `+ ADD INTEGRATION`, search for `TP-Link Router`.
3. Fill Password.
4. Click `SUBMIT`

NOTE!
1. If you use `https` connection to your router you may get error `certificate verify failed: EE certificate key too weak`. To fix this - unset `Verify ssl`
2. Use Local Password which is for Log In with Local Password

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/router.png" width="30%">

3. If you got error - `You need to use web encrypted password instead. Check the documentation!` Read [web encrypted password](#encrypted_pass)
4. The TP-Link Web Interface only supports upto 1 user logged in at a time (for security reasons, apparently). So you will be logged out from router web interface when the integration updates data

### <a id="encrypted_pass">Web Encrypted Password</a>
If you got error - `You need to use web encrypted password instead. Check the documentation!`
1. Go to the login page of your router. (default: 192.168.0.1).
2. Type in the password you use to login into the password field.
3. Click somewhere else on the page so that the password field is not selected anymore.
4. Open the JavaScript console of your browser (usually by pressing F12 and then clicking on "Console").
5. Type `document.getElementById("login-password").value;`
6. Copy the returned value as password and use it.

### Edit Configuration
You may edit configuration data like:
1. Router url
2. Password
3. Scan interval
4. Verify https

To do that:

1. Go to the <b>Settings</b>-><b>Devices & services</b>.
2. Search for `TP-Link Router`, and click on it.
3. Click on `CONFIGURE`
4. Edit the options you need and click `SUBMIT`

## <a id="supports">Supported routers</a>
### Fully tested Hardware Versions
- Archer A7 V5
- Archer AX10 v1.0
- Archer AX12 v1.0
- Archer AX20 v1.0
- Archer AX21 v1.20
- Archer AX23 v1.0
- Archer AX50 v1.0
- Archer AX55 v1.0
- Archer AX55 V1.60
- Archer AX72 V1
- Archer AX73 V1
- Archer AX75 V1
- Archer AXE75 V1
- Archer AX3000 V1
- Archer AX6000 V1
- Archer AX11000 V1
- Archer C1200 v2.0 (You need to use [web encrypted password](#encrypted_pass))
- Archer C2300 v1.0 (You need to use [web encrypted password](#encrypted_pass))
- Archer C6 v2.0
- Archer C6 v3.0
- Archer C6U v1.0
- Archer C7 v5.0
- Archer MR200 v5
- Archer MR200 v5.3
- Archer MR600 v1
- Archer MR600 v3
- Archer VR900v
- Deco M4 2.0
- Deco M4R 2.0
- Deco M9 Pro
- Deco XE75 2.0
- TL-WA3001 v1.0
- TL-MR105

### Not fully tested Hardware Versions
- AD7200 V2
- Archer A6 (V2 and V3)
- Archer A9 V6
- Archer A10 (V1 and V2)
- Archer A20 (V1, V3)
- Archer C7 V4
- Archer C8 (V3 and V4)
- Archer C9 (V4 and V5)
- Archer C59 V2
- Archer C90 V6
- Archer C900 V1
- Archer C1200 V3
- Archer C1900 V2
- Archer C2300 (V1, V2)
- Archer C4000 (V2 and V3)
- Archer C5400 V2
- Archer C5400X V1
- TD-W9960 v1
- TL-WR1043N V5

Please let me know if you have tested integration with one of this or other model. Open an issue with info about router's model, hardware and firmware versions.

## <a id="add_support">Adding Support For More Models</a>
Guidelines [CONTRIBUTING.md](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/blob/master/CONTRIBUTING.md)
