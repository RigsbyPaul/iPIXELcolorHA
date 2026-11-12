"""Config flow for iPIXELcolorHA."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import probatio as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_current_scanners,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COLOR,
    CONF_CONNECT_VIA,
    CONF_EFFECT,
    CONF_FONT_PATH,
    CONF_HEIGHT,
    CONF_IDLE_DISCONNECT,
    CONF_KEEP_CONNECTED,
    CONF_RAINBOW_MODE,
    CONF_SAVE_SLOT,
    CONF_SPEED,
    CONF_WIDTH,
    CONNECT_VIA_AUTO,
    DEFAULT_COLOR,
    DEFAULT_EFFECT,
    DEFAULT_HEIGHT,
    DEFAULT_IDLE_DISCONNECT,
    DEFAULT_KEEP_CONNECTED,
    DEFAULT_WIDTH,
    DEFAULT_RAINBOW_MODE,
    DEFAULT_SAVE_SLOT,
    DEFAULT_SPEED,
    DEVICE_NAME_PREFIX,
    DOMAIN,
)
from .device import IPixelDevice
from .protocol import DISPLAY_HEIGHTS, TEXT_EFFECTS, PanelInfo, load_font

_LOGGER = logging.getLogger(__name__)

HEIGHT_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[str(h) for h in DISPLAY_HEIGHTS],
        mode=selector.SelectSelectorMode.LIST,
        translation_key="height",
    )
)
WIDTH_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=8, max=1024, step=1, mode=selector.NumberSelectorMode.BOX
    )
)


def _is_matrix(info: BluetoothServiceInfoBleak) -> bool:
    return bool(info.name) and info.name.startswith(DEVICE_NAME_PREFIX)


class IPixelColorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a matrix found over Bluetooth."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._address = ""
        self._name = ""
        self._found: dict[str, str] = {}
        self._panel: PanelInfo | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a matrix discovered by Home Assistant's Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not _is_matrix(discovery_info):
            return self.async_abort(reason="not_supported")
        self._address = discovery_info.address
        self._name = discovery_info.name
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered matrix."""
        if user_input is not None:
            return await self.async_step_size()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._name},
        )

    async def async_step_size(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the panel size, pre-filled with what the panel reports."""
        if user_input is not None:
            return self._create(user_input)

        if self._panel is None:
            self._panel = await self._async_detect()
        width = self._panel.width if self._panel and self._panel.width else DEFAULT_WIDTH
        height = (
            self._panel.height
            if self._panel and self._panel.height in DISPLAY_HEIGHTS
            else DEFAULT_HEIGHT
        )
        return self.async_show_form(
            step_id="size",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HEIGHT, default=str(height)): HEIGHT_SELECTOR,
                    vol.Required(CONF_WIDTH, default=width): WIDTH_SELECTOR,
                }
            ),
            description_placeholders={
                "name": self._name,
                "detected": self._detected_text(),
            },
        )

    async def _async_detect(self) -> PanelInfo | None:
        """Ask the panel for its type; also sets its clock. None on failure."""
        device = IPixelDevice(self.hass, self._address, self._name)
        try:
            return await device.async_sync_time(dt_util.now())
        except HomeAssistantError as err:
            _LOGGER.debug("Could not read the panel type of %s: %s", self._name, err)
            return None

    def _detected_text(self) -> str:
        if self._panel is None:
            return "The panel did not report its size, so check these values."
        if self._panel.width is None:
            return (
                f"The panel reported type {self._panel.device_type}, which is not "
                "known, so check these values."
            )
        return (
            f"The panel reported type {self._panel.device_type}: "
            f"{self._panel.width} x {self._panel.height} pixels."
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a matrix from the ones currently in range."""
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._name = self._found[self._address].split(" (")[0]
            return await self.async_step_size()

        configured = self._async_current_ids(include_ignore=False)
        self._found = {
            info.address: f"{info.name} ({info.address})"
            for info in async_discovered_service_info(self.hass, connectable=True)
            if _is_matrix(info) and info.address not in configured
        }
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._found)}),
        )

    @callback
    def _create(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._name,
            data={},
            options={
                CONF_HEIGHT: int(user_input[CONF_HEIGHT]),
                CONF_WIDTH: int(user_input[CONF_WIDTH]),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return IPixelOptionsFlow()


class IPixelOptionsFlow(OptionsFlow):
    """Default text settings for a matrix."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the defaults used by the message entity."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HEIGHT] = int(user_input[CONF_HEIGHT])
            user_input[CONF_WIDTH] = int(user_input[CONF_WIDTH])
            user_input[CONF_EFFECT] = int(user_input[CONF_EFFECT])
            user_input[CONF_IDLE_DISCONNECT] = int(user_input[CONF_IDLE_DISCONNECT])
            font_path = user_input.get(CONF_FONT_PATH, "").strip()
            if font_path:
                try:
                    await self.hass.async_add_executor_job(
                        _check_font, font_path, user_input[CONF_HEIGHT]
                    )
                except OSError:
                    errors[CONF_FONT_PATH] = "invalid_font"
            if not errors:
                user_input[CONF_FONT_PATH] = font_path
                return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        connect_via = options.get(CONF_CONNECT_VIA, CONNECT_VIA_AUTO)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HEIGHT, default=str(options.get(CONF_HEIGHT, DEFAULT_HEIGHT))
                ): HEIGHT_SELECTOR,
                vol.Required(
                    CONF_WIDTH, default=options.get(CONF_WIDTH, DEFAULT_WIDTH)
                ): WIDTH_SELECTOR,
                vol.Required(CONF_CONNECT_VIA, default=connect_via): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=self._adapter_options(connect_via),
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_KEEP_CONNECTED,
                    default=options.get(CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_IDLE_DISCONNECT,
                    default=options.get(CONF_IDLE_DISCONNECT, DEFAULT_IDLE_DISCONNECT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=1440,
                        step=1,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_FONT_PATH, default=options.get(CONF_FONT_PATH, "")
                ): selector.TextSelector(),
                vol.Required(
                    CONF_COLOR, default=options.get(CONF_COLOR, DEFAULT_COLOR)
                ): selector.ColorRGBSelector(),
                vol.Required(
                    CONF_SPEED, default=options.get(CONF_SPEED, DEFAULT_SPEED)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=1)
                ),
                vol.Required(
                    CONF_EFFECT, default=str(options.get(CONF_EFFECT, DEFAULT_EFFECT))
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[str(e) for e in TEXT_EFFECTS],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="effect",
                    )
                ),
                vol.Required(
                    CONF_RAINBOW_MODE,
                    default=options.get(CONF_RAINBOW_MODE, DEFAULT_RAINBOW_MODE),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=9, step=1)
                ),
                vol.Required(
                    CONF_SAVE_SLOT, default=options.get(CONF_SAVE_SLOT, DEFAULT_SAVE_SLOT)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=10, step=1)
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    @callback
    def _adapter_options(self, current: str) -> list[selector.SelectOptionDict]:
        """List Automatic plus every connectable Bluetooth adapter and proxy."""
        choices = [
            selector.SelectOptionDict(
                value=CONNECT_VIA_AUTO, label="Automatic (best signal)"
            )
        ]
        sources = {CONNECT_VIA_AUTO}
        for scanner in async_current_scanners(self.hass):
            if scanner.connectable and scanner.source not in sources:
                sources.add(scanner.source)
                # HA's scanner name already ends with the source in brackets.
                label = (
                    scanner.name
                    if scanner.source in scanner.name
                    else f"{scanner.name} ({scanner.source})"
                )
                choices.append(
                    selector.SelectOptionDict(value=scanner.source, label=label)
                )
        if current not in sources:
            # Keep a saved proxy selectable while it is offline.
            choices.append(
                selector.SelectOptionDict(value=current, label=f"{current} (not connected)")
            )
        return choices


def _check_font(path: str, height: int) -> None:
    """Raise OSError if the font file cannot be loaded."""
    if not Path(path).is_file():
        raise OSError(f"{path} is not a file")
    load_font(height, path)
