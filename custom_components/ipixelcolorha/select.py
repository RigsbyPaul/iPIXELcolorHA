"""Text effect and clock style selects."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IPixelConfigEntry
from .const import CONF_CLOCK_STYLE, CONF_EFFECT, DEFAULT_CLOCK_STYLE, DEFAULT_EFFECT
from .option_entity import IPixelOptionEntity
from .protocol import CLOCK_STYLES, TEXT_EFFECTS

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the selects."""
    async_add_entities(
        [
            IPixelOptionSelect(entry, "text_effect", CONF_EFFECT, DEFAULT_EFFECT, TEXT_EFFECTS),
            IPixelOptionSelect(
                entry, "clock_style", CONF_CLOCK_STYLE, DEFAULT_CLOCK_STYLE, CLOCK_STYLES
            ),
        ]
    )


class IPixelOptionSelect(IPixelOptionEntity, SelectEntity):
    """A numbered choice kept in the options; used the next time it applies."""

    def __init__(
        self,
        entry: IPixelConfigEntry,
        key: str,
        option: str,
        default: int,
        values: range | tuple[int, ...],
    ) -> None:
        """Initialise the select."""
        super().__init__(entry, key, option, default)
        self._attr_options = [str(v) for v in values]

    @property
    def current_option(self) -> str:
        """Return the stored value."""
        return str(int(self._value))

    async def async_select_option(self, option: str) -> None:
        """Store the new value."""
        await self._async_store(int(option))
