"""Panel size and model sensors, from the device info the panel reports."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IPixelConfigEntry
from .entity import IPixelEntity
from .protocol import PanelInfo

PARALLEL_UPDATES = 0


def _size(info: PanelInfo) -> str | None:
    if info.width is None or info.height is None:
        return None
    return f"{info.width}x{info.height}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the diagnostic sensors."""
    async_add_entities(
        [
            IPixelPanelSensor(entry, "panel_size", _size),
            IPixelPanelSensor(entry, "device_type", lambda info: info.device_type),
        ]
    )


class IPixelPanelSensor(IPixelEntity, SensorEntity):
    """Something the panel reports about itself, read when its clock is set."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: IPixelConfigEntry,
        key: str,
        value: Callable[[PanelInfo], str | int | None],
    ) -> None:
        """Initialise the sensor."""
        super().__init__(entry, key)
        self._value = value

    @property
    def native_value(self) -> str | int | None:
        """Return the reported value, or None before the panel has answered."""
        info = self._device.panel_info
        return None if info is None else self._value(info)

    async def async_added_to_hass(self) -> None:
        """Update when the panel reports again."""
        await super().async_added_to_hass()
        self.async_on_remove(self._device.async_add_listener(self._async_reported))

    @callback
    def _async_reported(self) -> None:
        self.async_write_ha_state()
