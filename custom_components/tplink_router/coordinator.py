from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from tplinkrouterc6u import TplinkRouter, Firmware, Status
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from .const import DOMAIN


class TPLinkRouterCoordinator(DataUpdateCoordinator):
    def __init__(
            self,
            hass: HomeAssistant,
            router: TplinkRouter,
            update_interval: int,
            info: tuple[Firmware, Status],
            logger,
    ) -> None:
        self.router = router
        self.firmware = info[0]
        self.status = info[1]
        self.device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, self.status.macaddr)},
            identifiers={(DOMAIN, self.status.macaddr)},
            manufacturer="TPLink",
            model=self.firmware.model,
            name="TPLinkRouter",
            sw_version=self.firmware.firmware_version,
            hw_version=self.firmware.hardware_version,
        )

        super().__init__(
            hass,
            logger,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self):
        """Asynchronous update of all data."""
        self.status = await self.router.get_status()
