"""Sync-time button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import IPixelConfigEntry
from .entity import IPixelEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sync-time button."""
    async_add_entities([IPixelSyncTimeButton(entry)])


class IPixelSyncTimeButton(IPixelEntity, ButtonEntity):
    """Sets the panel's clock to Home Assistant's local time."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: IPixelConfigEntry) -> None:
        """Initialise the button."""
        super().__init__(entry, "sync_time")

    async def async_press(self) -> None:
        """Send the current time."""
        await self._device.async_sync_time(dt_util.now(), self._connect_via())
