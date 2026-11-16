"""Live coordinator for Doorcy scenes.

The scene list is fetched over REST once at setup and again after every
(re)connect of the websocket; in between the websocket pushes every change.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DoorcyAccessDeniedError,
    DoorcyAuthError,
    DoorcyClient,
    DoorcyConnectionError,
    SceneStatus,
    parse_scene_status,
)
from .const import (
    DOMAIN,
    MIN_CONNECTION_SECONDS,
    PING_INTERVAL,
    RECONNECT_DELAY_MAX,
    RECONNECT_DELAY_MIN,
    TOKEN_RENEW_MARGIN,
)

_LOGGER = logging.getLogger(__name__)


def is_active(value: Any) -> bool:
    """The poll sends "true"/"false" as strings, the socket real booleans."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def scene_started_signal(entry_id: str) -> str:
    return f"{DOMAIN}_scene_started_{entry_id}"


class DoorcyCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Scenes of every Doorcy the account may see, keyed by scene guid.

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
        oauth_session: config_entry_oauth2_flow.OAuth2Session,
    ) -> None:
        # No update_interval: the websocket is the update channel.
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry)
        self.client = client
        self.oauth_session = oauth_session
        self.devices: dict[str, str] = {}  # device_id -> label
        self._scene_guid_by_id: dict[str, str] = {}
        # Newest live message seen per scene. Start and stop of a short pulse
        # run as separate tasks on the server and may arrive in reverse order;
        # the state follows the timestamp, not the arrival order.
        self._last_seen: dict[str, datetime] = {}

    async def _async_setup(self) -> None:
        """Fetch the device list once, before the first refresh."""
        await self._async_load_devices()

    async def _async_load_devices(self) -> None:
        try:
            devices = await self.client.async_get_devices()
        except DoorcyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (DoorcyConnectionError, DoorcyAccessDeniedError) as err:
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
        """Poll the current state (setup and after every (re)connect)."""
        if not self.devices:
            await self._async_load_devices()
        try:
            batches = await asyncio.gather(
                *(self.client.async_get_scenes(code) for code in self.devices)
            )
        except DoorcyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (DoorcyConnectionError, DoorcyAccessDeniedError) as err:
            raise UpdateFailed(str(err)) from err

        scenes = {
            scene["guid"]: {**scene, "active": is_active(scene.get("active"))}
            for batch in batches
            for scene in batch or []
            if scene.get("guid")
        }
        self._scene_guid_by_id = {
            str(scene["id"]): guid for guid, scene in scenes.items() if "id" in scene
        }
        # A poll is the truth at this moment; older live messages must not
        # overwrite it, newer ones do.
        self._last_seen = {}
        _LOGGER.debug(
            "Doorcy: %d scene(s) across %d device(s)", len(scenes), len(self.devices)
        )
        return scenes

    # -- live updates -----------------------------------------------------

    def handle_scene_status(self, status: SceneStatus) -> None:
        """Apply one live message."""
        guid = self._scene_guid_by_id.get(status.scene_id)
        if guid is None or not self.data or guid not in self.data:
            # A scene we have not seen yet: fetch the list again.
            self.hass.async_create_task(self.async_request_refresh())
            return

        if status.active:
            # Every start is an event, also when its stop was already seen.
            async_dispatcher_send(
                self.hass,
                scene_started_signal(self.config_entry.entry_id),
                guid,
                status,
            )

        last = self._last_seen.get(guid)
        if last is not None and status.timestamp < last:
            return  # an older message that arrived late
        self._last_seen[guid] = status.timestamp
        if self.data[guid]["active"] == status.active:
            return
        self.async_set_updated_data(
            {**self.data, guid: {**self.data[guid], "active": status.active}}
        )

    async def async_run_live(self) -> None:
        """Keep the websocket open; runs as a background task of the entry."""
        delay = RECONNECT_DELAY_MIN
        while True:
            try:
                ws = await self.client.async_connect_live()
            except DoorcyAuthError:
                _LOGGER.warning("Doorcy login is no longer valid, asking to sign in")
                self.config_entry.async_start_reauth(self.hass)
                return
            except DoorcyConnectionError as err:
                _LOGGER.debug("Doorcy live connection failed: %s", err)
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_DELAY_MAX)
                continue

            delay = RECONNECT_DELAY_MIN
            connected_at = time.monotonic()
            try:
                # Subscribed before accepted, so polling now loses nothing.
                await self.async_refresh()
                renewed = await self._async_read(ws)
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Doorcy live connection dropped: %s", err)
                renewed = False
            finally:
                await ws.close()
            # A planned reconnect for a fresh token needs no pause, unless the
            # connection was so short that it would turn into a hot loop.
            if not renewed or time.monotonic() - connected_at < MIN_CONNECTION_SECONDS:
                await asyncio.sleep(delay)

    async def _async_read(self, ws: aiohttp.ClientWebSocketResponse) -> bool:
        """Read until the socket closes or the token is about to expire.

        Returns True when we stop to reconnect with a fresh token.
        """
        expires_at = float(self.oauth_session.token.get("expires_at", 0))
        while True:
            remaining = expires_at - time.time() - TOKEN_RENEW_MARGIN
            if remaining <= 0:
                return True
            try:
                msg = await ws.receive(timeout=min(PING_INTERVAL, remaining))
            except TimeoutError:
                await ws.send_json({"type": "ping"})
                continue
            if msg.type == aiohttp.WSMsgType.TEXT:
                status = parse_scene_status(msg.data)
                if status is not None:
                    self.handle_scene_status(status)
            elif msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                return False
