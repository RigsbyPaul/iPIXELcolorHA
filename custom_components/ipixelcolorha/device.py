"""BLE connection to an iPixel LED matrix."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
import logging
import time

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

from .const import ACK_TIMEOUT, DOMAIN
from .protocol import (
    ACK_COMPLETE,
    ACK_INVALID_COMMAND,
    ACK_NEXT_FRAME,
    ACK_NO_SPACE,
    NOTIFY_CHARACTERISTIC,
    WRITE_CHARACTERISTIC,
    FirmwareInfo,
    PanelInfo,
    build_brightness,
    build_firmware_request,
    build_time_sync,
    parse_ack,
    parse_device_info,
    parse_firmware_info,
)

_LOGGER = logging.getLogger(__name__)

# Smallest ATT payload every BLE link supports.
MIN_WRITE_SIZE = 20
# Seconds to wait for an optional reply to a short command.
COMMAND_SETTLE_TIMEOUT = 2.0

type Write = Callable[[bytes], Awaitable[None]]
type Notifications = asyncio.Queue[bytes]


@dataclass
class _Link:
    """An open connection: the client, how to write, and the reply queue."""

    client: BleakClientWithServiceCache
    connect_via: str | None
    characteristic: BleakGATTCharacteristic
    with_response: bool
    chunk_size: int
    notifying: bool
    notifications: Notifications = field(default_factory=asyncio.Queue)

    async def write(self, data: bytes) -> None:
        for start in range(0, len(data), self.chunk_size):
            await self.client.write_gatt_char(
                self.characteristic,
                data[start : start + self.chunk_size],
                response=self.with_response,
            )

    async def run[T](
        self, work: Callable[[Write, Notifications | None], Awaitable[T]]
    ) -> T:
        # Replies that arrived between sends belong to nothing we are waiting for.
        while not self.notifications.empty():
            self.notifications.get_nowait()
        return await work(self.write, self.notifications if self.notifying else None)


class IPixelDevice:
    """Talks to one matrix.

    With keep_connected off it connects for each send and disconnects
    afterwards, so the phone app can reach the matrix between messages. With it
    on, the connection stays open (the matrix shows its Bluetooth icon only
    when it connects) until idle_disconnect seconds pass with nothing sent;
    0 never disconnects. A dropped connection is reopened on the next send.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str,
        *,
        keep_connected: bool = False,
        idle_disconnect: float = 0,
    ) -> None:
        """Initialise the device."""
        self.hass = hass
        self.address = address
        self.name = name
        self.keep_connected = keep_connected
        self.idle_disconnect = idle_disconnect
        self._lock = asyncio.Lock()
        self._link: _Link | None = None
        self._last_used = 0.0
        self._cancel_idle: CALLBACK_TYPE | None = None
        self._listeners: set[Callable[[], None]] = set()
        # Last brightness set from Home Assistant (0-100), restored after a
        # send that hides the panel's loading animation.
        self.brightness_percent = 100
        # Firmware versions, read once per run on the first connection.
        self.firmware: FirmwareInfo | None = None
        self.panel_info: PanelInfo | None = None
        self.on_firmware: Callable[[FirmwareInfo], None] | None = None

    @property
    def connected(self) -> bool:
        """Return True while a kept connection is open.

        The matrix stops advertising while connected, so entities use this to
        stay available.
        """
        return self._link is not None and self._link.client.is_connected

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call listener when the connection opens or closes."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @callback
    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def async_configure(self, keep_connected: bool, idle_disconnect: float) -> None:
        """Apply changed connection options."""
        self.keep_connected = keep_connected
        self.idle_disconnect = idle_disconnect
        async with self._lock:
            self._stop_idle_timer()
            if self._link is None:
                return
            if keep_connected:
                self._start_idle_timer()
            else:
                await self._async_disconnect()

    async def async_shutdown(self) -> None:
        """Close the connection, if any."""
        self._stop_idle_timer()
        async with self._lock:
            await self._async_disconnect()

    def _ble_device(self, connect_via: str | None) -> BLEDevice:
        """Return the matrix as seen by the chosen adapter, or the best one."""
        if connect_via:
            for seen in bluetooth.async_scanner_devices_by_address(
                self.hass, self.address, connectable=True
            ):
                if seen.scanner.source == connect_via:
                    return seen.ble_device
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_seen_by_adapter",
                translation_placeholders={
                    "address": self.address,
                    "adapter": connect_via,
                },
            )
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"address": self.address},
            )
        return ble_device

    async def async_send_frames(
        self,
        frames: list[bytes],
        connect_via: str | None = None,
        *,
        hide_loading: bool = False,
        strict: bool = True,
    ) -> None:
        """Write frames to the matrix, waiting for its acknowledgement after each.

        With strict off, "invalid" and "no space" replies are not errors; the
        app treats live frames that way.

        connect_via is the source of a Bluetooth adapter or proxy to use; None
        lets Home Assistant pick the adapter with the best signal. With
        hide_loading the brightness is set to 0 while the frames go out and
        then put back, so the panel's own loading animation is not seen.
        Switching the LEDs off instead makes the panel replay its built-in
        graphics when it comes back on.
        """

        async def work(write: Write, notifications: Notifications | None) -> None:
            if hide_loading:
                await write(build_brightness(0))
                await _async_settle(notifications)
            try:
                for index, frame in enumerate(frames, start=1):
                    await write(frame)
                    if notifications is not None:
                        await self._async_wait_for_ack(
                            notifications, index, len(frames), strict
                        )
                    else:
                        # No acknowledgements: give the matrix time to take the frame.
                        await asyncio.sleep(0.5)
            finally:
                if hide_loading:
                    await write(build_brightness(self.brightness_percent))
                    await _async_settle(notifications)

        await self._async_session(connect_via, work)

    async def async_send_command(
        self, command: bytes, connect_via: str | None = None
    ) -> None:
        """Send one short command, such as brightness or power."""
        await self.async_send_commands([command], connect_via)

    async def async_send_commands(
        self, commands: list[bytes], connect_via: str | None = None
    ) -> None:
        """Send short commands in order over one connection.

        Each is given time to be taken (or its reply) before the next.
        """

        async def work(write: Write, notifications: Notifications | None) -> None:
            for command in commands:
                await write(command)
                await _async_settle(notifications)

        await self._async_session(connect_via, work)

    async def async_sync_time(
        self, when: datetime, connect_via: str | None = None
    ) -> PanelInfo | None:
        """Set the panel's clock and return the device info it replies with."""

        async def work(
            write: Write, notifications: Notifications | None
        ) -> PanelInfo | None:
            await write(build_time_sync(when))
            if notifications is None:
                return None
            try:
                async with asyncio.timeout(ACK_TIMEOUT):
                    while (info := parse_device_info(await notifications.get())) is None:
                        pass
            except TimeoutError:
                return None
            return info

        info = await self._async_session(connect_via, work)
        if info is not None and info != self.panel_info:
            self.panel_info = info
            self._notify_listeners()
        return info

    async def async_read_firmware(
        self, connect_via: str | None = None
    ) -> FirmwareInfo | None:
        """Connect if needed and return the firmware versions.

        Connecting reads them, so this only asks again when an earlier
        connection got no answer.
        """

        async def work(
            write: Write, notifications: Notifications | None
        ) -> FirmwareInfo | None:
            if self.firmware is None:
                await self._async_query_firmware(write, notifications)
            return self.firmware

        return await self._async_session(connect_via, work)

    async def _async_query_firmware(
        self, write: Write, notifications: Notifications | None
    ) -> None:
        """Ask for the firmware versions; panels that do not answer are skipped."""
        if notifications is None:
            return
        await write(build_firmware_request())
        try:
            async with asyncio.timeout(COMMAND_SETTLE_TIMEOUT):
                while (info := parse_firmware_info(await notifications.get())) is None:
                    pass
        except TimeoutError:
            _LOGGER.debug("%s: no firmware version reply", self.name)
            return
        _LOGGER.debug("%s: firmware MCU %s, Bluetooth %s", self.name, info.mcu, info.bluetooth)
        self.firmware = info
        if self.on_firmware is not None:
            self.on_firmware(info)

    async def _async_session[T](
        self,
        connect_via: str | None,
        work: Callable[[Write, Notifications | None], Awaitable[T]],
    ) -> T:
        """Run work over the kept connection, or a new one."""
        async with self._lock:
            self._stop_idle_timer()
            try:
                return await self._async_run(connect_via, work)
            finally:
                self._last_used = time.monotonic()
                if self._link is not None:
                    if self.keep_connected:
                        self._start_idle_timer()
                    else:
                        await self._async_disconnect()

    async def _async_run[T](
        self,
        connect_via: str | None,
        work: Callable[[Write, Notifications | None], Awaitable[T]],
    ) -> T:
        link = self._link
        if link is not None and (
            link.connect_via != connect_via or not link.client.is_connected
        ):
            await self._async_disconnect()
            link = None
        reused = link is not None
        if link is None:
            link = await self._async_connect(connect_via)
        try:
            return await link.run(work)
        except (BleakError, TimeoutError) as err:
            await self._async_disconnect()
            if not reused:
                raise _write_failed(err) from err
            # The kept connection had gone stale; try once on a fresh one.
            _LOGGER.debug("%s: kept connection failed (%s), reconnecting", self.name, err)
        link = await self._async_connect(connect_via)
        try:
            return await link.run(work)
        except (BleakError, TimeoutError) as err:
            await self._async_disconnect()
            raise _write_failed(err) from err

    async def _async_connect(self, connect_via: str | None) -> _Link:
        """Connect, subscribe to replies, and remember the connection."""
        ble_device = self._ble_device(connect_via)
        _LOGGER.debug("%s: connecting via %s", self.name, connect_via or "best adapter")
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.name,
                disconnected_callback=self._on_disconnected,
                max_attempts=3,
                # Retries must stay on the same adapter.
                ble_device_callback=lambda: self._ble_device(connect_via),
            )
        except (BleakError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="connect_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        characteristic = client.services.get_characteristic(WRITE_CHARACTERISTIC)
        if characteristic is None:
            await _quiet_disconnect(client)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_an_ipixel"
            )
        link = _Link(
            client=client,
            connect_via=connect_via,
            characteristic=characteristic,
            with_response="write" in characteristic.properties,
            chunk_size=max(MIN_WRITE_SIZE, client.mtu_size - 3),
            notifying=False,
        )

        def on_notify(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            _LOGGER.debug("%s notification %s", self.name, data.hex())
            link.notifications.put_nowait(bytes(data))

        try:
            await client.start_notify(NOTIFY_CHARACTERISTIC, on_notify)
            link.notifying = True
        except BleakError as err:
            _LOGGER.warning("%s: cannot read replies: %s", self.name, err)
        self._link = link
        self._notify_listeners()
        if self.firmware is None and link.notifying:
            try:
                await self._async_query_firmware(link.write, link.notifications)
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("%s: firmware query failed: %s", self.name, err)
        return link

    async def _async_disconnect(self) -> None:
        """Close and forget the connection, if any."""
        link, self._link = self._link, None
        if link is None:
            return
        _LOGGER.debug("%s: disconnecting", self.name)
        await _quiet_disconnect(link.client)
        self._notify_listeners()

    @callback
    def _on_disconnected(self, client: BleakClientWithServiceCache) -> None:
        """Forget a connection the matrix or adapter dropped."""
        if self._link is not None and self._link.client is client:
            _LOGGER.debug("%s: connection dropped", self.name)
            self._link = None
            self._stop_idle_timer()
            self._notify_listeners()

    @callback
    def _start_idle_timer(self) -> None:
        self._stop_idle_timer()
        if self.idle_disconnect > 0:
            self._cancel_idle = async_call_later(
                self.hass, self.idle_disconnect, self._async_idle_expired
            )

    @callback
    def _stop_idle_timer(self) -> None:
        if self._cancel_idle is not None:
            self._cancel_idle()
            self._cancel_idle = None

    async def _async_idle_expired(self, _now: datetime) -> None:
        self._cancel_idle = None
        async with self._lock:
            # A send may have run while we waited for the lock.
            idle = time.monotonic() - self._last_used
            if self._link is not None and idle >= self.idle_disconnect - 1:
                _LOGGER.debug("%s: idle for %.0f s", self.name, idle)
                await self._async_disconnect()

    async def _async_wait_for_ack(
        self,
        notifications: Notifications,
        index: int,
        total: int,
        strict: bool = True,
    ) -> None:
        try:
            async with asyncio.timeout(ACK_TIMEOUT):
                while (status := parse_ack(await notifications.get())) not in (
                    ACK_NEXT_FRAME,
                    ACK_COMPLETE,
                ):
                    if not strict and status is not None:
                        # Live frames: the app logs these replies and carries
                        # on, as the panel still shows the frame.
                        _LOGGER.debug(
                            "%s: frame %s of %s answered %s", self.name, index, total, status
                        )
                        return
                    if status == ACK_NO_SPACE:
                        raise HomeAssistantError(
                            translation_domain=DOMAIN,
                            translation_key="no_space",
                        )
                    if status == ACK_INVALID_COMMAND:
                        raise HomeAssistantError(
                            translation_domain=DOMAIN,
                            translation_key="rejected",
                        )
        except TimeoutError:
            # Not every firmware acknowledges every frame, so carry on.
            _LOGGER.warning(
                "%s: no acknowledgement for frame %s of %s", self.name, index, total
            )


async def _async_settle(notifications: Notifications | None) -> None:
    """Give a short command time to be taken before anything else is sent.

    Waits briefly for the panel's reply; not every command gets one.
    """
    if notifications is None:
        await asyncio.sleep(0.5)
        return
    try:
        async with asyncio.timeout(COMMAND_SETTLE_TIMEOUT):
            await notifications.get()
    except TimeoutError:
        pass


def _write_failed(err: Exception) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="write_failed",
        translation_placeholders={"error": str(err)},
    )


async def _quiet_disconnect(client: BleakClientWithServiceCache) -> None:
    try:
        await client.disconnect()
    except BleakError as err:
        _LOGGER.debug("Disconnect failed: %s", err)
