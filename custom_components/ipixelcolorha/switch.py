"""Upside-down switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import IPixelConfigEntry
from .const import CONF_CLOCK_24H, CONF_CLOCK_SHOW_DATE
from .entity import IPixelEntity
from .option_entity import IPixelOptionEntity
from .protocol import build_upside_down

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the upside-down and clock switches."""
    async_add_entities(
        [
            IPixelUpsideDownSwitch(entry),
            IPixelOptionSwitch(entry, "clock_24h", CONF_CLOCK_24H),
            IPixelOptionSwitch(entry, "clock_show_date", CONF_CLOCK_SHOW_DATE),
        ]
    )


class IPixelOptionSwitch(IPixelOptionEntity, SwitchEntity):
    """A clock setting kept in the options; used by the Show clock button."""

    def __init__(self, entry: IPixelConfigEntry, key: str, option: str) -> None:
        """Initialise the switch."""
        super().__init__(entry, key, option, True)

    @property
    def is_on(self) -> bool:
        """Return the stored value."""
        return bool(self._value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Store on."""
        await self._async_store(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Store off."""
        await self._async_store(False)


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
