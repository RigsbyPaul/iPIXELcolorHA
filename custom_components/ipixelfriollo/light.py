"""Panel power and brightness as a light."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import IPixelConfigEntry
from .entity import IPixelEntity
from .protocol import build_brightness, build_power

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the panel light."""
    async_add_entities([IPixelPanelLight(entry)])


def _to_percent(brightness: int) -> int:
    """Map HA brightness (1-255) to the panel's 1-100."""
    return max(1, round(brightness * 100 / 255))


class IPixelPanelLight(IPixelEntity, LightEntity, RestoreEntity):
    """Turns the panel's LEDs on and off and sets their brightness.

    The panel does not report these back, so the state is the last one set
    from Home Assistant.
    """

    _attr_assumed_state = True
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_name = None  # the device's own name

    def __init__(self, entry: IPixelConfigEntry) -> None:
        """Initialise the light."""
        super().__init__(entry, "panel")
        self._attr_is_on = True
        self._attr_brightness = 255

    async def async_added_to_hass(self) -> None:
        """Restore the last state set from Home Assistant."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
            if (brightness := last.attributes.get(ATTR_BRIGHTNESS)) is not None:
                self._attr_brightness = brightness
        self._device.brightness_percent = _to_percent(self._attr_brightness)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the panel on, setting the brightness if one is given."""
        if not self._attr_is_on:
            await self._async_command(build_power(True))
            self._attr_is_on = True
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            await self._async_command(build_brightness(_to_percent(brightness)))
            self._attr_brightness = brightness
            self._device.brightness_percent = _to_percent(brightness)
        elif self._attr_is_on and not kwargs:
            # Plain "turn on" when already on: re-send power in case the panel
            # was switched off elsewhere, such as from the phone app.
            await self._async_command(build_power(True))
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the panel's LEDs off."""
        await self._async_command(build_power(False))
        self._attr_is_on = False
        self.async_write_ha_state()
