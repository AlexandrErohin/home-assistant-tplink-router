# Tp-Link router integration for Home Assistant
Home Assistant component for TP-Link router administration based on the [TP-Link Router API](https://github.com/AlexandrErohin/TP-Link-Archer-C6U)

> [!WARNING]
> Please temporarily disable the integration before accessing the router admin page. TP-Link admin page only allows one user at a time. This integration will log you out of the admin page every time it scans for updates (every 30s by default).

See [Supported routers](#supports)

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/sensors.png" width="48%"> <img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/switches.png" width="48%">

## Components
### Events
 - tplink_router_new_device: Fired when a new device appears in your network
 - tplink_router_device_offline: Fired when a device becomes offline
 - tplink_router_device_online: Fired when a device becomes online

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

### Device Tracker
 - Track connected to router devices by MAC address with connection information

To find your device - Go to `Developer tools` and search for your MAC address - you’ll find sensor like `device_tracker.YOUR_MAC` or `device_tracker.YOUR_PHONE_NAME`.

It will also fire Home Assistant event when a device connects to router

### Services
 - Send SMS message - Available only for MR LTE routers

### Notification
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

All available fields in `trigger.event.data`:
- hostname
- ip_address
- mac_address
- connection
- band
- packets_sent
- packets_received

### Send SMS only for MR LTE routers
To send SMS add following lines to your automation in yaml:
```yaml
...
action:
  - service: tplink_router.send_sms
    data:
      number: ""pass phone number here"
      text: "pass text here"
      device: "pass tplink router device id here"
```

Device id is required because user may have several routers that could send SMS - so you need to select the needed router

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
2. Use Local Password which is for Log In with Local Password. Login with TP-LINK ID doesnt work

<img src="https://raw.githubusercontent.com/AlexandrErohin/home-assistant-tplink-router/master/docs/media/router.png" width="30%">

3. If you got error - `use web encrypted password instead. Check the documentation!` Read [web encrypted password](#encrypted_pass)
4. The TP-Link Web Interface only supports upto 1 user logged in at a time (for security reasons, apparently). So you will be logged out from router web interface when the integration updates data

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
### Fully tested Hardware Versions
- Archer A7 V5
- Archer A9 V6
- Archer AX10 v1.0
- Archer AX12 v1.0
- Archer AX20 v1.0
- Archer AX20 v3.0
- Archer AX21 (v1.20, v3.0)
- Archer AX23 v1.0
- Archer AX50 v1.0
- Archer AX53 v2
- Archer AX55 (v1.0, V1.60, v4.0)
- Archer AX72 V1
- Archer AX73 V1
- Archer AX75 V1
- Archer AX90 V1.20
- Archer AXE75 V1
- Archer AXE16000
- Archer AX3000 V1
- Archer AX6000 V1
- Archer AX11000 V1
- Archer BE800 v1.0
- Archer BE805 v1.0
- Archer BE3600 1.6
- Archer C1200 (v1.0, v2.0)
- Archer C2300 (v1.0, v2.0)
- Archer C6 (v2.0, v3.0)
- Archer C6U v1.0
- Archer C7 (v4.0, v5.0)
- Archer C5400X V1
- Archer GX90 v1.0
- Archer MR200 (v5, v5.3, v6.0)
- Archer MR550 v1
- Archer MR600 (v1, v2, v3)
- Archer VR600 v3
- Archer VR900v
- Archer VR2100v v1
- Deco M4 2.0
- Deco M4R 2.0
- Deco M5 v3
- Deco M9 Pro
- Deco M9 Plus 1.0
- Deco P7
- Deco X20
- Deco X50 v1.3
- Deco X60 V3
- Deco X90
- Deco XE75 (v1.0, v2.0)
- EX511 v2.0
- TD-W9960 (v1, V1.20)
- TL-MR100 v2.0
- TL-MR105
- TL-MR6400 (v5, v5.3)
- TL-MR6500v
- TL-XDR3010 V2
- TL-WA3001 v1.0
- NX510v v1.0

### Not fully tested Hardware Versions
- AD7200 V2
- Archer A6 (V2 and V3)
- Archer A10 (V1 and V2)
- Archer A20 (V1, V3)
- Archer C8 (V3 and V4)
- Archer C9 (V4 and V5)
- Archer C59 V2
- Archer C90 V6
- Archer C900 V1
- Archer C1200 V3
- Archer C1900 V2
- Archer C4000 (V2 and V3)
- Archer C5400 V2
- TL-WR1043N V5

Please let me know if you have tested integration with one of this or other model. Open an issue with info about router's model, hardware and firmware versions.

## <a id="add_support">Adding Support For More Models</a>
Guidelines [CONTRIBUTING.md](https://github.com/AlexandrErohin/TP-Link-Archer-C6U/blob/master/CONTRIBUTING.md)
