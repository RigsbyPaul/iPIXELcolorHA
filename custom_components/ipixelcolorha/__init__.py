"""The iPIXELcolorHA integration: show text on iPixel LED matrices over BLE."""

from __future__ import annotations

import logging
from pathlib import Path

import probatio as vol

from homeassistant.components import bluetooth
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.text import DOMAIN as TEXT_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    service,
)
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_ANCHOR,
    ATTR_BACKGROUND_COLOR,
    ATTR_BLOCK_SIZE,
    ATTR_CLEAR,
    ATTR_COLOR,
    ATTR_COLORS,
    ATTR_COMMAND,
    ATTR_DURATION,
    ATTR_EFFECT,
    ATTR_FILE,
    ATTR_HIDE_LOADING,
    ATTR_LABEL,
    ATTR_LAYERS,
    ATTR_LIVE,
    ATTR_MAXIMUM,
    ATTR_MESSAGE,
    ATTR_MINUTES,
    ATTR_POINTS,
    ATTR_RAINBOW_MODE,
    ATTR_RECTANGLES,
    ATTR_RESIZE,
    ATTR_SAVE_SLOT,
    ATTR_SECONDS,
    ATTR_SERIES,
    ATTR_SHOW_DATE,
    ATTR_SIZE,
    ATTR_SLOTS,
    ATTR_SPEED,
    ATTR_STEPS,
    ATTR_STYLE,
    ATTR_TEXT,
    ATTR_URL,
    ATTR_USE_24H,
    ATTR_VALUES,
    ATTR_X,
    ATTR_X_MAX,
    ATTR_X_MIN,
    ATTR_Y,
    ATTR_Y_MAX,
    ATTR_Y_MIN,
    CONF_CONNECT_VIA,
    CONF_IDLE_DISCONNECT,
    CONNECT_VIA_AUTO,
    CONF_KEEP_CONNECTED,
    DEFAULT_IDLE_DISCONNECT,
    DEFAULT_KEEP_CONNECTED,
    DOMAIN,
    README_URL,
    SERVICE_COUNTDOWN,
    SERVICE_DELETE_ALL,
    SERVICE_DELETE_SLOTS,
    SERVICE_DISPLAY_GRAPH,
    SERVICE_DISPLAY_IMAGE,
    SERVICE_DISPLAY_RANDOM_PIXELS,
    SERVICE_DISPLAY_TEXT,
    SERVICE_DRAW_FRAME,
    SERVICE_DRAW_PIXELS,
    SERVICE_SHOW_CLOCK,
    SERVICE_STOPWATCH,
)
from .device import IPixelDevice
from .protocol import (
    CLOCK_STYLES,
    COUNTDOWN_MAX_MINUTES,
    MAX_DRAW_POINTS,
    MAX_FRAME_LAYERS,
    MAX_GRAPH_VALUES,
    MAX_LAYER_RECTANGLES,
    MAX_PLOT_SERIES,
    MAX_SLOT,
    RANDOM_PIXEL_BLOCKS,
    RANDOM_PIXEL_COLORS,
    RANDOM_PIXEL_DURATIONS,
    RANDOM_PIXEL_STEPS,
    TEXT_ANCHORS,
    TEXT_EFFECTS,
    FirmwareInfo,
    PlotStyle,
    ResizeMode,
    TimerAction,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.LIGHT, Platform.SWITCH, Platform.TEXT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

RGB_SCHEMA = vol.All(
    vol.Coerce(tuple), vol.ExactSequence((cv.byte, cv.byte, cv.byte))
)

DISPLAY_TEXT_SCHEMA = {
    vol.Required(ATTR_MESSAGE): cv.string,
    vol.Optional(ATTR_COLOR): RGB_SCHEMA,
    vol.Optional(ATTR_BACKGROUND_COLOR): RGB_SCHEMA,
    vol.Optional(ATTR_SPEED): vol.All(vol.Coerce(int), vol.Range(0, 100)),
    vol.Optional(ATTR_EFFECT): vol.All(vol.Coerce(int), vol.In(TEXT_EFFECTS)),
    vol.Optional(ATTR_RAINBOW_MODE): vol.All(vol.Coerce(int), vol.Range(0, 9)),
    vol.Optional(ATTR_SAVE_SLOT): vol.All(vol.Coerce(int), vol.Range(1, 10)),
}

# The entity method checks that exactly one of file and url is given.
DISPLAY_IMAGE_SCHEMA = {
    vol.Exclusive(ATTR_FILE, "source"): cv.string,
    vol.Exclusive(ATTR_URL, "source"): cv.url,
    vol.Optional(ATTR_RESIZE): vol.In([mode.value for mode in ResizeMode]),
    vol.Optional(ATTR_BACKGROUND_COLOR): RGB_SCHEMA,
    vol.Optional(ATTR_SAVE_SLOT): vol.All(vol.Coerce(int), vol.Range(1, 10)),
    vol.Optional(ATTR_HIDE_LOADING, default=False): cv.boolean,
    vol.Optional(ATTR_LIVE, default=False): cv.boolean,
}

POINTS_SCHEMA = vol.All(
    vol.EnsureList(),
    [vol.ExactSequence((vol.Coerce(float), vol.Coerce(float)))],
    vol.Length(min=1, max=MAX_GRAPH_VALUES),
)

# The entity method checks that one of values, points and series is given.
DISPLAY_GRAPH_SCHEMA = {
    vol.Exclusive(ATTR_VALUES, "data"): vol.All(
        vol.EnsureList(),
        [vol.Coerce(float)],
        vol.Length(min=1, max=MAX_GRAPH_VALUES),
    ),
    vol.Exclusive(ATTR_POINTS, "data"): POINTS_SCHEMA,
    vol.Exclusive(ATTR_SERIES, "data"): vol.All(
        vol.EnsureList(),
        [
            {
                vol.Required(ATTR_POINTS): POINTS_SCHEMA,
                vol.Optional(ATTR_COLOR): RGB_SCHEMA,
            }
        ],
        vol.Length(min=1, max=MAX_PLOT_SERIES),
    ),
    vol.Optional(ATTR_STYLE): vol.In([style.value for style in PlotStyle]),
    vol.Optional(ATTR_COLOR): RGB_SCHEMA,
    vol.Optional(ATTR_BACKGROUND_COLOR): RGB_SCHEMA,
    vol.Optional(ATTR_X_MIN): vol.Coerce(float),
    vol.Optional(ATTR_X_MAX): vol.Coerce(float),
    vol.Optional(ATTR_Y_MIN): vol.Coerce(float),
    vol.Exclusive(ATTR_Y_MAX, "top"): vol.Coerce(float),
    # maximum is the older name for y_max, kept for bar graphs.
    vol.Exclusive(ATTR_MAXIMUM, "top"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional(ATTR_LABEL): cv.string,
    vol.Optional(ATTR_SAVE_SLOT): vol.All(vol.Coerce(int), vol.Range(1, 10)),
    vol.Optional(ATTR_HIDE_LOADING, default=False): cv.boolean,
    vol.Optional(ATTR_LIVE, default=False): cv.boolean,
}



def _in_range(values: range) -> vol.All:
    """Schema for an integer inside a range."""
    return vol.All(vol.Coerce(int), vol.Range(values.start, values.stop - 1))


DISPLAY_RANDOM_PIXELS_SCHEMA = {
    vol.Optional(ATTR_STEPS, default=10): _in_range(RANDOM_PIXEL_STEPS),
    vol.Optional(ATTR_DURATION, default=200): _in_range(RANDOM_PIXEL_DURATIONS),
    vol.Optional(ATTR_COLORS, default=4): _in_range(RANDOM_PIXEL_COLORS),
    vol.Optional(ATTR_BLOCK_SIZE, default=1): _in_range(RANDOM_PIXEL_BLOCKS),
    vol.Optional(ATTR_SAVE_SLOT): vol.All(vol.Coerce(int), vol.Range(1, 10)),
    vol.Optional(ATTR_HIDE_LOADING, default=False): cv.boolean,
}

_COORD = vol.All(vol.Coerce(int), vol.Range(min=0, max=255))

# The entity method checks the points lie on the panel.
DRAW_PIXELS_SCHEMA = {
    vol.Optional(ATTR_POINTS, default=list): vol.All(
        vol.EnsureList(),
        [vol.ExactSequence((_COORD, _COORD))],
        vol.Length(max=MAX_DRAW_POINTS),
    ),
    vol.Optional(ATTR_RECTANGLES, default=list): vol.All(
        vol.EnsureList(),
        [vol.ExactSequence((_COORD, _COORD, _COORD, _COORD))],
        vol.Length(max=64),
    ),
    vol.Optional(ATTR_COLOR): RGB_SCHEMA,
    vol.Optional(ATTR_CLEAR, default=False): cv.boolean,
}

# The entity method checks the points lie on the panel.
DRAW_FRAME_SCHEMA = {
    vol.Required(ATTR_LAYERS): vol.All(
        vol.EnsureList(),
        [
            {
                vol.Required(ATTR_COLOR): RGB_SCHEMA,
                vol.Optional(ATTR_POINTS, default=list): vol.All(
                    vol.EnsureList(),
                    [vol.ExactSequence((_COORD, _COORD))],
                    vol.Length(max=MAX_DRAW_POINTS),
                ),
                vol.Optional(ATTR_RECTANGLES, default=list): vol.All(
                    vol.EnsureList(),
                    [vol.ExactSequence((_COORD, _COORD, _COORD, _COORD))],
                    vol.Length(max=MAX_LAYER_RECTANGLES),
                ),
                vol.Optional(ATTR_TEXT): cv.string,
                vol.Optional(ATTR_X, default=0): vol.Coerce(int),
                vol.Optional(ATTR_Y, default=0): vol.Coerce(int),
                vol.Optional(ATTR_SIZE): vol.All(vol.Coerce(int), vol.Range(4, 256)),
                vol.Optional(ATTR_ANCHOR, default="la"): vol.In(TEXT_ANCHORS),
            }
        ],
        vol.Length(min=1, max=MAX_FRAME_LAYERS),
    ),
    vol.Optional(ATTR_BACKGROUND_COLOR): RGB_SCHEMA,
    vol.Optional(ATTR_SAVE_SLOT): vol.All(vol.Coerce(int), vol.Range(1, 10)),
    vol.Optional(ATTR_HIDE_LOADING, default=True): cv.boolean,
    vol.Optional(ATTR_LIVE, default=False): cv.boolean,
}

SHOW_CLOCK_SCHEMA = {
    vol.Required(ATTR_STYLE): vol.All(
        vol.Coerce(int), vol.Range(CLOCK_STYLES.start, CLOCK_STYLES.stop - 1)
    ),
    vol.Optional(ATTR_USE_24H, default=True): cv.boolean,
    vol.Optional(ATTR_SHOW_DATE, default=True): cv.boolean,
}

TIMER_COMMANDS = [action.name.lower() for action in TimerAction]

# The entity method checks start is given a time above 0:00.
COUNTDOWN_SCHEMA = {
    vol.Required(ATTR_COMMAND): vol.In(TIMER_COMMANDS),
    vol.Optional(ATTR_MINUTES, default=0): vol.All(
        vol.Coerce(int), vol.Range(0, COUNTDOWN_MAX_MINUTES)
    ),
    vol.Optional(ATTR_SECONDS, default=0): vol.All(vol.Coerce(int), vol.Range(0, 59)),
}

STOPWATCH_SCHEMA = {
    vol.Required(ATTR_COMMAND): vol.In(TIMER_COMMANDS),
}

DELETE_SLOTS_SCHEMA = {
    vol.Required(ATTR_SLOTS): vol.All(
        vol.EnsureList(),
        [vol.All(vol.Coerce(int), vol.Range(1, MAX_SLOT))],
        vol.Length(min=1),
    ),
}

# (action, schema, entity method)
ACTIONS = (
    (SERVICE_DISPLAY_TEXT, DISPLAY_TEXT_SCHEMA, "async_display_text"),
    (SERVICE_DISPLAY_IMAGE, DISPLAY_IMAGE_SCHEMA, "async_display_image"),
    (SERVICE_DISPLAY_GRAPH, DISPLAY_GRAPH_SCHEMA, "async_display_graph"),
    (
        SERVICE_DISPLAY_RANDOM_PIXELS,
        DISPLAY_RANDOM_PIXELS_SCHEMA,
        "async_display_random_pixels",
    ),
    (SERVICE_DRAW_PIXELS, DRAW_PIXELS_SCHEMA, "async_draw_pixels"),
    (SERVICE_DRAW_FRAME, DRAW_FRAME_SCHEMA, "async_draw_frame"),
    (SERVICE_SHOW_CLOCK, SHOW_CLOCK_SCHEMA, "async_show_clock"),
    (SERVICE_COUNTDOWN, COUNTDOWN_SCHEMA, "async_countdown"),
    (SERVICE_STOPWATCH, STOPWATCH_SCHEMA, "async_stopwatch"),
    (SERVICE_DELETE_SLOTS, DELETE_SLOTS_SCHEMA, "async_delete_slots"),
    (SERVICE_DELETE_ALL, {}, "async_delete_all"),
)

type IPixelConfigEntry = ConfigEntry[IPixelDevice]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions and serve the README as the documentation page.

    The actions target a matrix's Message entity. The integration page's
    Documentation link opens the GitHub repository; this local copy of the
    README stays available at README_URL.
    """
    if hass.http is not None:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    README_URL, str(Path(__file__).parent / "README.html"), False
                )
            ]
        )
    for name, schema, method in ACTIONS:
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=TEXT_DOMAIN,
            schema=schema,
            func=method,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IPixelConfigEntry) -> bool:
    """Set up a matrix from a config entry."""
    address = entry.unique_id
    assert address is not None
    if not bluetooth.async_address_present(hass, address, connectable=True):
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": address},
        )
    keep_connected, idle_disconnect = _connection_options(entry)
    device = IPixelDevice(
        hass,
        address,
        entry.title,
        keep_connected=keep_connected,
        idle_disconnect=idle_disconnect,
    )
    entry.runtime_data = device
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    @callback
    def _firmware_read(info: FirmwareInfo) -> None:
        """Show the firmware versions on the device page."""
        registry = dr.async_get(hass)
        if device_entry := registry.async_get_device_by_connection(
            (dr.CONNECTION_BLUETOOTH, address), entry.entry_id
        ):
            registry.async_update_device(
                device_entry.id,
                sw_version=info.mcu,
                hw_version=f"Bluetooth {info.bluetooth}",
            )

    device.on_firmware = _firmware_read

    async def _async_stop(_event: Event) -> None:
        await device.async_shutdown()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if keep_connected:
        # The connection is kept anyway, so open it now to read the firmware
        # versions. Otherwise they are read on the first send.
        connect_via = entry.options.get(CONF_CONNECT_VIA, CONNECT_VIA_AUTO)
        entry.async_create_background_task(
            hass,
            _async_read_firmware(
                device, None if connect_via == CONNECT_VIA_AUTO else connect_via
            ),
            f"{DOMAIN} firmware {address}",
        )
    return True


async def _async_read_firmware(device: IPixelDevice, connect_via: str | None) -> None:
    try:
        await device.async_read_firmware(connect_via)
    except HomeAssistantError as err:
        _LOGGER.debug("%s: could not read firmware: %s", device.name, err)


def _connection_options(entry: IPixelConfigEntry) -> tuple[bool, float]:
    """Return keep_connected and the idle timeout in seconds."""
    options = entry.options
    return (
        options.get(CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED),
        float(options.get(CONF_IDLE_DISCONNECT, DEFAULT_IDLE_DISCONNECT)) * 60,
    )


async def _async_options_updated(hass: HomeAssistant, entry: IPixelConfigEntry) -> None:
    """Apply changed connection options; the others are read when used."""
    await entry.runtime_data.async_configure(*_connection_options(entry))


async def async_unload_entry(hass: HomeAssistant, entry: IPixelConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
