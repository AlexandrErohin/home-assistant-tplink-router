# Tp-Link router integration for Home Assistant (supports also Mercusys router)
[![version](https://img.shields.io/github/manifest-json/v/AlexandrErohin/home-assistant-tplink-router?filename=custom_components%2Ftplink_router%2Fmanifest.json&color=slateblue)](https://github.com/AlexandrErohin/home-assistant-tplink-router/releases/latest)
[![HACS](https://img.shields.io/badge/HACS-Default-orange.svg?logo=HomeAssistantCommunityStore&logoColor=white)](https://github.com/hacs/integration)
[![Community Forum](https://img.shields.io/static/v1.svg?label=Community&message=Forum&color=41bdf5&logo=HomeAssistant&logoColor=white)](https://community.home-assistant.io/t/custom-component-tp-link-router-integration)

Home Assistant component for TP-Link and Mercusys routers administration based on the [TP-Link Router API](https://github.com/AlexandrErohin/TP-Link-Archer-C6U)

> [!WARNING]
> A new router firmware update breaks the compatibility. Please try [this fix](https://github.com/AlexandrErohin/home-assistant-tplink-router/issues/220#issuecomment-3396658175) 

> [!WARNING]
> Please temporarily disable the integration before accessing the router admin page. TP-Link admin page only allows one user at a time. This integration will log you out of the admin page every time it scans for updates (every 30s by default).

See [Supported routers](#supports)

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/sensors.png" width="48%"> <img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/switches.png" width="48%">

## Components
### Events
 - tplink_router_new_device: Fired when a new device appears in your network
 - tplink_router_device_offline: Fired when a device becomes offline
 - tplink_router_device_online: Fired when a device becomes online
 - tplink_router_new_sms: Fired when a new sms received by LTE router
### Switches
 - Router Reboot
 - Router data fetching - you may disable router data fetching before accessing the router, so it wont logging your out.
If you forget to enable it back - it would be automatically enable after 20 minutes
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
 - Connection Type

For LTE Routers
- LTE Enabled
- LTE Connection Status
- LTE Network Type
- LTE SIM Status
- LTE Total Statistics
- LTE Current RX Speed
- LTE Current TX Speed
- Unread SMS
- LTE Signal Level
- LTE RSRP
- LTE RSRQ
- LTE SNR
- LTE ISP Name

### Device Tracker
 - Track connected to router devices by MAC address with connection information

To find your device - Go to `Developer tools` and search for your MAC address - you’ll find sensor like `device_tracker.YOUR_MAC` or `device_tracker.YOUR_PHONE_NAME`.

It will also fire Home Assistant event when a device connects to router

### Services
 - Send SMS message - Available only for MR LTE routers

### Notification
#### Device events
To receive notifications of appearing a new device in your network, or becoming device online\offline add following lines to your `configuration.yaml` file:
```yaml
automation:
  - alias: "New network device"
    trigger:
      platform: event
      event_type: tplink_router_new_device
    action:
      service: notify.mobile_app_<device_name>
      data:
        content: >-
          New device appear {{ trigger.event.data.hostname }} with IP {{ trigger.event.data.ip_address }}
```
Available events:
 - tplink_router_new_device: Fired when a new device appears in your network
 - tplink_router_device_offline: Fired when a device becomes offline
 - tplink_router_device_online: Fired when a device becomes online

All available fields in `trigger.event.data`:
- hostname
- ip_address
- mac_address
- connection
- band
- packets_sent
- packets_received

#### SMS events only for MR LTE routers
To receive notifications of receiving a new sms add following lines to your `configuration.yaml` file:
```yaml
automation:
  - alias: "New sms"
    trigger:
      platform: event
      event_type: tplink_router_new_sms
    action:
      service: notify.mobile_app_<device_name>
      data:
        content: >-
          A new SMS from {{ trigger.event.data.sender }} wth text: {{ trigger.event.data.content }}
```
Available events:
 - tplink_router_new_sms: Fired when a new sms received by LTE router

All available fields in `trigger.event.data`:
- sender
- content
- received_at

### Send SMS only for MR LTE routers
To send SMS add following lines to your automation in yaml:
```yaml
...
action:
  - service: tplink_router.send_sms
    data:
      number: "+1234567890"
      text: "Hello World"
      device: pass_tplink_router_device_id_here
```

Device id is required because user may have several routers that could send SMS - so you need to select the needed router.
You can get the ID from the URL when you visit the tplink device page

## Installation

### HACS (recommended)

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=AlexandrErohin&repository=home-assistant-tplink-router&category=integration" target="_blank"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and open a repository inside the Home Assistant Community Store." /></a>

or go to <b>Hacs</b> and search for `TP-Link Router`.

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
2. If you use `https` connection - You need to turn on "Local Management via HTTPS" (advanced->system->administration) in the router web UI
3. Use Local Password which is for Log In with Local Password. Login with TP-LINK ID doesnt work

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/router.png" width="30%">

4. If you got error - `check if the default router username is correct` The default username for most routers is `admin`. Some routers have the default username - `user`.
5. If you got error - `use web encrypted password instead` Read [web encrypted password](#encrypted_pass)
6. The TP-Link Web Interface only supports upto 1 user logged in at a time (for security reasons, apparently). So you will be logged out from router web interface when the integration updates data

### <a id="encrypted_pass">Web Encrypted Password</a>
If you got error - `use web encrypted password instead. Check the documentation!`
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
- [TP-LINK routers](#tplink)
- [MERCUSYS routers](#mercusys)
### <a id="tplink">TP-LINK routers</a>
- Archer A6 (2.0, 4.0)
- Archer A7 V5
- Archer A8 (1.0, 2.20)
- Archer A9 V6
- Archer A20 v1.0
- Archer AX10 v1.0
- Archer AX12 v1.0
- Archer AX17 v1.0
- Archer AX20 (v1.0, v3.0)
- Archer AX21 (v1.20, v3.0)
- Archer AX23 (v1.0, v1.2)
- Archer AX50 v1.0
- Archer AX53 (v1.0, v2)
- Archer AX55 (v1.0, V1.60, v4.0)
- Archer AX58 v1.0
- Archer AX72 V1
- Archer AX73 (V1, V2.0)
- Archer AX75 V1
- Archer AX90 V1.20
- Archer AX95 v1.0
- Archer AXE75 V1
- Archer AXE5400 v1.0
- Archer AXE16000
- Archer AX1800
- Archer AX3000 V1
- Archer AX6000 V1
- Archer AX11000 V1
- Archer BE220 v1.0
- Archer BE230 v1.0
- Archer BE400 v1.0
- Archer BE550 v1.0
- Archer BE800 v1.0
- Archer BE805 v1.0
- Archer BE3600 1.6
- Archer C1200 (v1.0, v2.0)
- Archer C2300 (v1.0, v2.0)
- Archer C6 (v2.0, v3.0, v3.20, 4.0)
- Archer C6U v1.0
- Archer C7 (v4.0, v5.0)
- Archer C24 (1.0, 2.0)
- Archer C60 v2.0
- Archer C64 1.0
- Archer C80 (1.0, 2.20)
- Archer C5400X V1
- Archer GX90 v1.0
- Archer MR200 (v2, v5, v5.3, v6.0)
- Archer MR550 v1
- Archer MR600 (v1, v2, v3)
- Archer NX200 v2.0
- Archer VR400 (v2, v3)
- Archer VR600 v3
- Archer VR900v
- Archer VR1200v v1
- Archer VR2100v v1
- Archer VX231v v1.0
- Archer VX1800v v1.0
- BE11000 2.0
- Deco M4 2.0
- Deco M4R 2.0
- Deco M5 v3
- Deco M9 Pro
- Deco M9 Plus 1.0
- Deco P7
- Deco X20
- Deco X50 v1.3
- Deco X55 1.0
- Deco X60 V3
- Deco X90
- Deco XE75 (v1.0, v2.0)
- Deco XE75PRO (v3.0)
- EX511 v2.0
- HX510 v1.0
- NX510v v1.0
- TD-W9960 (v1, V1.20)
- TL-MR100 v2.0
- TL-MR105
- TL-MR100-Outdoor v1.0
- TL-MR110-Outdoor v1.0
- TL-MR150 v2
- TL-MR6400 (v5, v5.3)
- TL-MR6500v
- TL-WA1201 3.0
- TL-WA3001 v1.0
- TL-XDR3010 V2
- TL-WDR3600 V1
- TL-XDR6088 v1.0.30
- VX420-G2h v1.1
- VX800v v1
- XC220-G3v v2.30
- RE305 4.0
- RE315 1.0
- RE330 v1
### <a id="mercusys">MERCUSYS routers</a>
- AC10 1.20
- MR47BE v1.0
- MR50G 1.0
- H60XR 1.0
- H47BE 2.0
- Halo H80X 1.0
- Halo H3000x 1.0

Please let me know if you have tested integration with any other model. Open an issue with info about router's model, hardware and firmware versions.

## <a id="add_support">Adding Support For More Models</a>
Guidelines [CONTRIBUTING.md](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/blob/master/CONTRIBUTING.md)
