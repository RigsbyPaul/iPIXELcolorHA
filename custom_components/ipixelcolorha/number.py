"""Text speed and rainbow-mode numbers."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IPixelConfigEntry
from .const import CONF_RAINBOW_MODE, CONF_SPEED, DEFAULT_RAINBOW_MODE, DEFAULT_SPEED
from .option_entity import IPixelOptionEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the numbers."""
    async_add_entities(
        [
            IPixelOptionNumber(entry, "text_speed", CONF_SPEED, DEFAULT_SPEED, 0, 100, NumberMode.SLIDER),
            IPixelOptionNumber(
                entry, "rainbow_mode", CONF_RAINBOW_MODE, DEFAULT_RAINBOW_MODE, 0, 9, NumberMode.BOX
            ),
        ]
    )


class IPixelOptionNumber(IPixelOptionEntity, NumberEntity):
    """A text setting kept in the options; used for the next message."""

    _attr_native_step = 1

    def __init__(
        self,
        entry: IPixelConfigEntry,
        key: str,
        option: str,
        default: int,
        low: int,
        high: int,
        mode: NumberMode,
    ) -> None:
        """Initialise the number."""
        super().__init__(entry, key, option, default)
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        self._attr_mode = mode

    @property
    def native_value(self) -> int:
        """Return the stored value."""
        return int(self._value)

    async def async_set_native_value(self, value: float) -> None:
        """Store the new value."""
        await self._async_store(int(value))
