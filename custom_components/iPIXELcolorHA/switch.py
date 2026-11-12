"""Upside-down switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import IPixelConfigEntry
from .entity import IPixelEntity
from .protocol import build_upside_down

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the upside-down switch."""
    async_add_entities([IPixelUpsideDownSwitch(entry)])


class IPixelUpsideDownSwitch(IPixelEntity, SwitchEntity, RestoreEntity):
    """Rotates everything on the panel by 180 degrees, for a panel mounted upside down."""

    _attr_assumed_state = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: IPixelConfigEntry) -> None:
        """Initialise the switch."""
        super().__init__(entry, "upside_down")
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore the last state set from Home Assistant."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Flip the picture."""
        await self._async_command(build_upside_down(True))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Show the picture the normal way up."""
        await self._async_command(build_upside_down(False))
        self._attr_is_on = False
        self.async_write_ha_state()
