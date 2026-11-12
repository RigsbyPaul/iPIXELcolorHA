"""Text entity that shows its value on the matrix."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

import aiohttp

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import IPixelConfigEntry
from .const import (
    ATTR_ANCHOR,
    ATTR_COLOR,
    ATTR_POINTS,
    ATTR_RECTANGLES,
    ATTR_SIZE,
    ATTR_TEXT,
    ATTR_X,
    ATTR_Y,
    CONF_COLOR,
    CONF_EFFECT,
    CONF_FONT_PATH,
    CONF_HEIGHT,
    CONF_RAINBOW_MODE,
    CONF_SAVE_SLOT,
    CONF_SPEED,
    CONF_WIDTH,
    DEFAULT_COLOR,
    DEFAULT_EFFECT,
    DEFAULT_HEIGHT,
    DEFAULT_RAINBOW_MODE,
    DEFAULT_SAVE_SLOT,
    DEFAULT_SPEED,
    DEFAULT_WIDTH,
    DOMAIN,
    DOWNLOAD_TIMEOUT,
    MAX_PICTURE_BYTES,
)
from .entity import IPixelEntity
from .protocol import (
    DrawLayer,
    ResizeMode,
    TextStyle,
    TimerAction,
    DIY_ENTER_CLEAR,
    DIY_ENTER_KEEP,
    build_clock_mode,
    build_countdown,
    build_delete_all,
    build_delete_slots,
    build_diy_mode,
    build_diy_pixels,
    draw_points,
    encode_chart,
    encode_frame,
    encode_image,
    encode_live_chart,
    encode_live_image,
    encode_random_pixels,
    encode_text,
    build_stopwatch,
)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the message entity."""
    async_add_entities([IPixelMessageText(entry)])


class IPixelMessageText(IPixelEntity, TextEntity, RestoreEntity):
    """The last message sent to the matrix. Setting it sends a new one.

    It also carries the matrix's actions (display_text, display_image,
    show_clock, delete_slots, delete_all), which target this entity.
    """

    _attr_native_max = 255

    def __init__(self, entry: IPixelConfigEntry) -> None:
        """Initialise the entity."""
        super().__init__(entry, "message")
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        """Restore the last message."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and last.state not in (
            "unknown",
            "unavailable",
        ):
            self._attr_native_value = last.state

    async def async_set_value(self, value: str) -> None:
        """Send the new message using the configured defaults."""
        await self.async_display_text(message=value)

    async def async_display_text(
        self,
        message: str,
        color: tuple[int, int, int] | None = None,
        background_color: tuple[int, int, int] | None = None,
        speed: int | None = None,
        effect: int | None = None,
        rainbow_mode: int | None = None,
        save_slot: int | None = None,
    ) -> None:
        """Render a message and send it to the matrix."""
        options: dict[str, Any] = self._entry.options

        def pick(value: int | None, key: str, default: int) -> int:
            # Number selectors store floats, so normalise to int.
            return int(options.get(key, default) if value is None else value)

        try:
            style = TextStyle(
                color=tuple(int(c) for c in color or options.get(CONF_COLOR, DEFAULT_COLOR)),
                background=tuple(background_color) if background_color else None,
                speed=pick(speed, CONF_SPEED, DEFAULT_SPEED),
                effect=pick(effect, CONF_EFFECT, DEFAULT_EFFECT),
                rainbow_mode=pick(rainbow_mode, CONF_RAINBOW_MODE, DEFAULT_RAINBOW_MODE),
            )
            frames = await self.hass.async_add_executor_job(
                encode_text,
                message,
                int(options.get(CONF_HEIGHT, DEFAULT_HEIGHT)),
                style,
                pick(save_slot, CONF_SAVE_SLOT, DEFAULT_SAVE_SLOT),
                options.get(CONF_FONT_PATH) or None,
            )
        except (ValueError, OSError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_message",
                translation_placeholders={"error": str(err)},
            ) from err

        await self._device.async_send_frames(frames, self._connect_via())
        self._attr_native_value = message
        self.async_write_ha_state()

    async def async_display_image(
        self,
        file: str | None = None,
        url: str | None = None,
        resize: str | None = None,
        background_color: tuple[int, int, int] | None = None,
        save_slot: int | None = None,
        hide_loading: bool = False,
        live: bool = False,
    ) -> None:
        """Send a picture or animation to the matrix, fitted to its size.

        With live the first frame is shown as a live frame: not saved to a
        slot, and animations are not played.
        """
        if (file is None) == (url is None):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="image_source"
            )
        data = await (self._async_read_file(file) if file else self._async_download(url))
        options: dict[str, Any] = self._entry.options
        width = int(options.get(CONF_WIDTH, DEFAULT_WIDTH))
        height = int(options.get(CONF_HEIGHT, DEFAULT_HEIGHT))
        mode = ResizeMode(resize or ResizeMode.FIT)
        background = tuple(background_color) if background_color else (0, 0, 0)
        try:
            if live:
                frames = await self.hass.async_add_executor_job(
                    encode_live_image, data, width, height, mode, background
                )
            else:
                frames = await self.hass.async_add_executor_job(
                    encode_image,
                    data,
                    width,
                    height,
                    int(options.get(CONF_SAVE_SLOT, DEFAULT_SAVE_SLOT) if save_slot is None else save_slot),
                    mode,
                    background,
                )
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_image",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._device.async_send_frames(
            frames, self._connect_via(), hide_loading=hide_loading and not live, strict=not live
        )

    async def async_display_graph(
        self,
        values: list[float] | None = None,
        points: list[list[float]] | None = None,
        series: list[dict[str, Any]] | None = None,
        style: str | None = None,
        color: tuple[int, int, int] | None = None,
        background_color: tuple[int, int, int] | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
        y_min: float | None = None,
        y_max: float | None = None,
        maximum: float | None = None,
        label: str | None = None,
        save_slot: int | None = None,
        hide_loading: bool = False,
        live: bool = False,
    ) -> None:
        """Draw values as bars, or x-y points as lines or dots, and send it.

        With live the graph is shown as a live frame, not saved to a slot.
        """
        if values is None and points is None and series is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_graph_data",
            )
        options: dict[str, Any] = self._entry.options
        try:
            size = (
                int(options.get(CONF_WIDTH, DEFAULT_WIDTH)),
                int(options.get(CONF_HEIGHT, DEFAULT_HEIGHT)),
            )
            target = (
                partial(encode_live_chart, *size)
                if live
                else partial(
                    encode_chart,
                    *size,
                    int(options.get(CONF_SAVE_SLOT, DEFAULT_SAVE_SLOT) if save_slot is None else save_slot),
                )
            )
            frames = await self.hass.async_add_executor_job(
                partial(
                    target,
                    values=values,
                    points=points,
                    series=None
                    if series is None
                    else [
                        (item[ATTR_POINTS], item.get(ATTR_COLOR)) for item in series
                    ],
                    style=style,
                    color=tuple(int(c) for c in color or options.get(CONF_COLOR, DEFAULT_COLOR)),
                    background=tuple(background_color) if background_color else (0, 0, 0),
                    x_min=x_min,
                    x_max=x_max,
                    y_min=y_min,
                    y_max=maximum if y_max is None else y_max,
                    label=label or None,
                )
            )
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._device.async_send_frames(
            frames, self._connect_via(), hide_loading=hide_loading and not live, strict=not live
        )

    async def _async_read_file(self, path: str) -> bytes:
        """Read a picture from a folder Home Assistant allows access to."""
        if not self.hass.config.is_allowed_path(path):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="file_not_allowed",
                translation_placeholders={"file": path},
            )

        def read() -> bytes:
            with open(path, "rb") as handle:
                data = handle.read(MAX_PICTURE_BYTES + 1)
            if len(data) > MAX_PICTURE_BYTES:
                raise ValueError("larger than 10 MB")
            return data

        try:
            return await self.hass.async_add_executor_job(read)
        except (OSError, ValueError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="file_unreadable",
                translation_placeholders={"file": path, "error": str(err)},
            ) from err

    async def _async_download(self, url: str) -> bytes:
        """Download a picture, refusing anything larger than the limit."""
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(DOWNLOAD_TIMEOUT), session.get(url) as response:
                response.raise_for_status()
                # read(n) returns only what has arrived so far, so keep
                # reading until the body ends or passes the size limit.
                buffer = bytearray()
                while len(buffer) <= MAX_PICTURE_BYTES:
                    chunk = await response.content.read(
                        MAX_PICTURE_BYTES + 1 - len(buffer)
                    )
                    if not chunk:
                        break
                    buffer.extend(chunk)
                data = bytes(buffer)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="download_failed",
                translation_placeholders={"url": url, "error": str(err) or "timed out"},
            ) from err
        if len(data) > MAX_PICTURE_BYTES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="download_failed",
                translation_placeholders={"url": url, "error": "larger than 10 MB"},
            )
        return data

    async def async_display_random_pixels(
        self,
        steps: int,
        duration: int,
        colors: int,
        block_size: int = 1,
        save_slot: int | None = None,
        hide_loading: bool = False,
    ) -> None:
        """Send a looping GIF of steps pictures of random-colour blocks."""
        options: dict[str, Any] = self._entry.options
        try:
            frames = await self.hass.async_add_executor_job(
                partial(
                    encode_random_pixels,
                    int(options.get(CONF_WIDTH, DEFAULT_WIDTH)),
                    int(options.get(CONF_HEIGHT, DEFAULT_HEIGHT)),
                    steps,
                    duration,
                    colors,
                    int(options.get(CONF_SAVE_SLOT, DEFAULT_SAVE_SLOT) if save_slot is None else save_slot),
                    block_size=block_size,
                )
            )
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._device.async_send_frames(
            frames, self._connect_via(), hide_loading=hide_loading
        )

    async def async_draw_pixels(
        self,
        points: list[list[int]],
        rectangles: list[list[int]],
        clear: bool = False,
        color: tuple[int, int, int] | None = None,
    ) -> None:
        """Set single pixels live, without sending a whole picture.

        Puts the panel in its drawing mode, clearing the screen first if
        clear is set, then colours each point and filled rectangle.
        """
        options: dict[str, Any] = self._entry.options
        try:
            pixels = draw_points(
                int(options.get(CONF_WIDTH, DEFAULT_WIDTH)),
                int(options.get(CONF_HEIGHT, DEFAULT_HEIGHT)),
                points,
                rectangles,
            )
            commands = [build_diy_mode(DIY_ENTER_CLEAR if clear else DIY_ENTER_KEEP)]
            commands += build_diy_pixels(
                tuple(int(c) for c in color or options.get(CONF_COLOR, DEFAULT_COLOR)),
                pixels,
            )
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._device.async_send_commands(commands, self._connect_via())

    async def async_draw_frame(
        self,
        layers: list[dict[str, Any]],
        background_color: tuple[int, int, int] | None = None,
        save_slot: int | None = None,
        hide_loading: bool = True,
        live: bool = False,
    ) -> None:
        """Paint coloured layers into one picture and send it in one go.

        Unlike draw_pixels (one colour per call, drawn on the panel bit by
        bit), the whole picture is built here and replaces what is shown at
        once. Saved to a slot as a PNG, or with live shown as a live frame.
        """
        options: dict[str, Any] = self._entry.options
        try:
            draw_layers = [
                DrawLayer(
                    color=tuple(layer[ATTR_COLOR]),
                    points=tuple(tuple(p) for p in layer.get(ATTR_POINTS, [])),
                    rectangles=tuple(tuple(r) for r in layer.get(ATTR_RECTANGLES, [])),
                    text=layer.get(ATTR_TEXT) or None,
                    x=int(layer.get(ATTR_X, 0)),
                    y=int(layer.get(ATTR_Y, 0)),
                    size=layer.get(ATTR_SIZE),
                    anchor=layer.get(ATTR_ANCHOR, "la"),
                )
                for layer in layers
            ]
            frames = await self.hass.async_add_executor_job(
                partial(
                    encode_frame,
                    int(options.get(CONF_WIDTH, DEFAULT_WIDTH)),
                    int(options.get(CONF_HEIGHT, DEFAULT_HEIGHT)),
                    draw_layers,
                    tuple(background_color) if background_color else (0, 0, 0),
                    int(options.get(CONF_SAVE_SLOT, DEFAULT_SAVE_SLOT) if save_slot is None else save_slot),
                    live,
                )
            )
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._device.async_send_frames(
            frames, self._connect_via(), hide_loading=hide_loading and not live, strict=not live
        )

    async def async_show_clock(
        self, style: int, use_24h: bool = True, show_date: bool = True
    ) -> None:
        """Set the matrix's time, then switch it to its built-in clock."""
        now = dt_util.now()
        try:
            command = build_clock_mode(style, use_24h, show_date, now)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._device.async_sync_time(now, self._connect_via())
        await self._async_command(command)

    async def async_countdown(
        self, command: str, minutes: int = 0, seconds: int = 0
    ) -> None:
        """Start, pause, resume or reset the matrix's built-in countdown."""
        try:
            message = build_countdown(TimerAction[command.upper()], minutes, seconds)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._async_command(message)

    async def async_stopwatch(self, command: str) -> None:
        """Start, pause, resume or reset the matrix's built-in stopwatch."""
        await self._async_command(build_stopwatch(TimerAction[command.upper()]))

    async def async_delete_slots(self, slots: list[int]) -> None:
        """Delete saved programs from the given slots."""
        try:
            command = build_delete_slots(sorted(set(slots)))
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._async_command(command)

    async def async_delete_all(self) -> None:
        """Delete every saved program."""
        await self._async_command(build_delete_all())
