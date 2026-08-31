"""Polling coordinator for Doorcy scenes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DoorcyAuthError, DoorcyClient, DoorcyConnectionError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class DoorcyCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Discovers devices once, then polls every device's scenes.

    Confirmed payloads:
        GET /watch-info/devices
            [{"id": "haythem", "label": "haythem"}]
        GET /watch-info/scenes?device=haythem
            [{"label": ..., "id": "2845", "active": "false",
              "guid": "1882...", "device": "haythem"}]

    Note the device must be addressed by its `device_id`; passing the
    `device_guid` returns a 500 from the API.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DoorcyClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.devices: dict[str, str] = {}   # device_id -> label

    async def _async_setup(self) -> None:
        """Fetch the device list once, before the first refresh."""
        try:
            devices = await self.client.async_get_devices()
        except DoorcyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DoorcyConnectionError as err:
            raise UpdateFailed(str(err)) from err

        self.devices = {
            d["id"]: d.get("label") or d["id"]
            for d in devices or []
            if isinstance(d, dict) and d.get("id")
        }

        if not self.devices:
            _LOGGER.warning("No Doorcy devices returned: %s", devices)
        else:
            _LOGGER.debug("Doorcy devices: %s", self.devices)

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            batches = await asyncio.gather(
                *(self.client.async_get_scenes(code) for code in self.devices)
            )
        except DoorcyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DoorcyConnectionError as err:
            raise UpdateFailed(str(err)) from err

        scenes = {
            scene["guid"]: scene
            for batch in batches
            for scene in batch or []
            if scene.get("guid")
        }
        _LOGGER.debug("Doorcy: %d scene(s) across %d device(s)",
                      len(scenes), len(self.devices))
        return scenes
