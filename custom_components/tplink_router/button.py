"""Component providing support for TPLinkRouter button entities."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from homeassistant.const import EntityCategory
from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .coordinator import TPLinkRouterCoordinator


@dataclass
class TPLinkRouterButtonEntityDescriptionMixin:
    method: Callable[[TPLinkRouterCoordinator], Any]


@dataclass
class TPLinkButtonEntityDescription(
    ButtonEntityDescription, TPLinkRouterButtonEntityDescriptionMixin
):
    """A class that describes button entities for the host."""


BUTTON_TYPES = (
    TPLinkButtonEntityDescription(
        key="reboot",
        name="Reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        method=lambda coordinator: coordinator.reboot(),
    ),
)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    buttons = []

    for description in BUTTON_TYPES:
        buttons.append(TPLinkRouterButtonEntity(coordinator, description))
    async_add_entities(buttons, False)


class TPLinkRouterButtonEntity(CoordinatorEntity[TPLinkRouterCoordinator], ButtonEntity):
    entity_description: TPLinkButtonEntityDescription

    def __init__(
            self,
            coordinator: TPLinkRouterCoordinator,
            description: TPLinkButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_{description.key}"
        self.entity_description = description

    async def async_press(self) -> None:
        await self.entity_description.method(self.coordinator)
