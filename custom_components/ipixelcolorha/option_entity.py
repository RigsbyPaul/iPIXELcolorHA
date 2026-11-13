"""Base for configuration entities that store their value in the entry's options."""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory

from . import IPixelConfigEntry
from .entity import IPixelEntity


class IPixelOptionEntity(IPixelEntity):
    """A setting kept in the config entry's options, so it matches the options dialog."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: IPixelConfigEntry, key: str, option: str, default: Any) -> None:
        """Initialise the entity."""
        super().__init__(entry, key)
        self._option = option
        self._default = default

    @property
    def _value(self) -> Any:
        return self._entry.options.get(self._option, self._default)

    async def _async_store(self, value: Any) -> None:
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, self._option: value}
        )

    async def async_added_to_hass(self) -> None:
        """Follow changes made in the options dialog."""
        await super().async_added_to_hass()
        self.async_on_remove(self._entry.add_update_listener(self._async_options_changed))

    async def _async_options_changed(self, *_args: Any) -> None:
        self.async_write_ha_state()
