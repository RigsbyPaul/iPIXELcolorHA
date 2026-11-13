"""Sync-time, show-clock and resend-message buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.components.text import DOMAIN as TEXT_DOMAIN
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import IPixelConfigEntry
from .const import (
    CONF_CLOCK_24H,
    CONF_CLOCK_SHOW_DATE,
    CONF_CLOCK_STYLE,
    DEFAULT_CLOCK_STYLE,
    DOMAIN,
)
from .entity import IPixelEntity
from .protocol import build_clock_mode

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the buttons."""
    async_add_entities(
        [IPixelSyncTimeButton(entry), IPixelShowClockButton(entry), IPixelResendButton(entry)]
    )


class IPixelSyncTimeButton(IPixelEntity, ButtonEntity):
    """Sets the panel's clock to Home Assistant's local time."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: IPixelConfigEntry) -> None:
        """Initialise the button."""
        super().__init__(entry, "sync_time")

    async def async_press(self) -> None:
        """Send the current time."""
        await self._device.async_sync_time(dt_util.now(), self._connect_via())


class IPixelShowClockButton(IPixelEntity, ButtonEntity):
    """Shows the built-in clock with the clock style, 24-hour and date settings."""

    def __init__(self, entry: IPixelConfigEntry) -> None:
        """Initialise the button."""
        super().__init__(entry, "show_clock")

    async def async_press(self) -> None:
        """Set the time and switch to the clock."""
        options = self._entry.options
        now = dt_util.now()
        command = build_clock_mode(
            int(options.get(CONF_CLOCK_STYLE, DEFAULT_CLOCK_STYLE)),
            bool(options.get(CONF_CLOCK_24H, True)),
            bool(options.get(CONF_CLOCK_SHOW_DATE, True)),
            now,
        )
        await self._device.async_sync_time(now, self._connect_via())
        await self._async_command(command)


class IPixelResendButton(IPixelEntity, ButtonEntity):
    """Sends the current message again, with the current text settings."""

    def __init__(self, entry: IPixelConfigEntry) -> None:
        """Initialise the button."""
        super().__init__(entry, "resend_message")

    async def async_press(self) -> None:
        """Set the message entity to its own value again."""
        entity_id = er.async_get(self.hass).async_get_entity_id(
            TEXT_DOMAIN, DOMAIN, f"{self._device.address}_message"
        )
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in ("unknown", "unavailable", ""):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_message"
            )
        await self.hass.services.async_call(
            TEXT_DOMAIN,
            "set_value",
            {"entity_id": entity_id, "value": state.state},
            blocking=True,
        )
