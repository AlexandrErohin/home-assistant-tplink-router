from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from tplinkrouterc6u import TplinkRouter, Firmware, Status, Wifi
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
            configuration_url=f"http://{router.host}/",
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

    async def reboot(self) -> None:
        await self.hass.async_add_executor_job(self.router.reboot)

    async def set_wifi(self, wifi: Wifi, enable: bool) -> None:
        await self.hass.async_add_executor_job(self.router.set_wifi, wifi, enable)

    async def _async_update_data(self):
        """Asynchronous update of all data."""
        self.status = await self.hass.async_add_executor_job(self.router.get_status)
