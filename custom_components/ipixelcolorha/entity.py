"""Base entity for iPIXELcolorHA."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from . import IPixelConfigEntry
from .const import CONF_CONNECT_VIA, CONNECT_VIA_AUTO


class IPixelEntity(Entity):
    """An entity of one matrix: shared device, availability and connection choice."""

    _attr_has_entity_name = True

    def __init__(self, entry: IPixelConfigEntry, key: str) -> None:
        """Initialise the entity."""
        self._entry = entry
        self._device = entry.runtime_data
        address = self._device.address
        self._attr_translation_key = key
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            name=entry.title,
            manufacturer="iPixel",
        )

    async def async_added_to_hass(self) -> None:
        """Follow the matrix's BLE presence."""
        await super().async_added_to_hass()
        address = self._device.address
        self._attr_available = self._device.connected or bluetooth.async_address_present(
            self.hass, address, connectable=True
        )
        self.async_on_remove(self._device.async_add_listener(self._async_link_changed))
        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._async_seen,
                bluetooth.BluetoothCallbackMatcher(address=address, connectable=True),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
        self.async_on_remove(
            bluetooth.async_track_unavailable(
                self.hass, self._async_gone, address, connectable=True
            )
        )

    @callback
    def _async_seen(
        self,
        _info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        if not self._attr_available:
            self._attr_available = True
            self.async_write_ha_state()

    @callback
    def _async_gone(self, _info: bluetooth.BluetoothServiceInfoBleak) -> None:
        # The matrix stops advertising while we hold a connection to it.
        if self._device.connected:
            return
        self._attr_available = False
        self.async_write_ha_state()

    @callback
    def _async_link_changed(self) -> None:
        available = self._device.connected or bluetooth.async_address_present(
            self.hass, self._device.address, connectable=True
        )
        if available != self._attr_available:
            self._attr_available = available
            self.async_write_ha_state()

    def _connect_via(self) -> str | None:
        """Return the adapter to connect through, or None for automatic."""
        connect_via = self._entry.options.get(CONF_CONNECT_VIA, CONNECT_VIA_AUTO)
        return None if connect_via == CONNECT_VIA_AUTO else connect_via

    async def _async_command(self, command: bytes) -> None:
        """Send one short command to the matrix."""
        await self._device.async_send_command(command, self._connect_via())
