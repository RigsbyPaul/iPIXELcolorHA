"""Diagnostics download for support requests."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import IPixelConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IPixelConfigEntry
) -> dict[str, Any]:
    """Return the settings and what the panel has reported."""
    device = entry.runtime_data
    return {
        "options": dict(entry.options),
        "connected": device.connected,
        "keep_connected": device.keep_connected,
        "firmware": asdict(device.firmware) if device.firmware else None,
        "panel": asdict(device.panel_info) if device.panel_info else None,
    }
