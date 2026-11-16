"""Async client for the Doorcy API (api.doorcy.nl).

Login is OAuth (authorization code, same as the Homey app). Every call sends
`Authorization: Bearer <access token>`; the token comes from Home Assistant's
OAuth2 session, which refreshes it when it is about to expire. Live scene
updates come over the `ws/home-assistant` websocket.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

from homeassistant.util import dt as dt_util

from .const import API_BASE, WS_URL

_LOGGER = logging.getLogger(__name__)


class DoorcyAuthError(Exception):
    """The token was rejected or could not be renewed."""


class DoorcyAccessDeniedError(Exception):
    """The account may not use scenes (not an authentication problem)."""


class DoorcyConnectionError(Exception):
    """Doorcy could not be reached."""


@dataclass(frozen=True)
class SceneStatus:
    """One live scene_status message."""

    scene_id: str
    device_id: str
    active: bool
    timestamp: datetime


def parse_scene_status(text: str) -> SceneStatus | None:
    """Parse a websocket text frame; None for anything but a scene status."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("type") != "scene_status":
        return None
    timestamp = dt_util.parse_datetime(str(data.get("timestamp")))
    if data.get("scene_id") is None or timestamp is None:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt_util.UTC)
    return SceneStatus(
        scene_id=str(data["scene_id"]),
        device_id=str(data.get("device_id")),
        active=bool(data.get("active")),
        timestamp=timestamp,
    )


class DoorcyClient:
    """Minimal client: account, list scenes, switch scenes, live socket."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        async_get_access_token: Callable[[], Awaitable[str]],
    ) -> None:
        self._session = session
        self._async_get_access_token = async_get_access_token

    async def _async_token(self) -> str:
        try:
            return await self._async_get_access_token()
        except aiohttp.ClientResponseError as err:
            # The refresh token was refused: the link was revoked or expired.
            if err.status in (400, 401):
                raise DoorcyAuthError("Doorcy refused to renew the token") from err
            raise DoorcyConnectionError(str(err)) from err
        except aiohttp.ClientError as err:
            raise DoorcyConnectionError(str(err)) from err

    async def _async_request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = await self._async_token()
        try:
            resp = await self._session.request(
                method,
                f"{API_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
        except aiohttp.ClientError as err:
            raise DoorcyConnectionError(str(err)) from err

        if resp.status == 401:
            raise DoorcyAuthError("Doorcy rejected the access token")
        if resp.status == 403:
            raise DoorcyAccessDeniedError("This Doorcy account may not use scenes")
        try:
            resp.raise_for_status()
        except aiohttp.ClientError as err:
            raise DoorcyConnectionError(str(err)) from err
        if resp.status == 204:
            return None
        # Do NOT gate on resp.content_length: it is None for chunked or
        # gzipped responses, which would silently discard a valid body.
        text = await resp.text()
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError:
            _LOGGER.warning("Non-JSON response from %s: %.200s", path, text)
            return None

    async def async_get_account(self) -> dict[str, Any]:
        """GET /account/me -- the signed-in account."""
        return await self._async_request("GET", "/account/me") or {}

    async def async_get_devices(self) -> Any:
        """GET /watch-info/devices -- compact device list."""
        return await self._async_request("GET", "/watch-info/devices")

    async def async_get_scenes(self, device: str) -> list[dict[str, Any]]:
        """GET /watch-info/scenes?device=<code|favorites>."""
        return (
            await self._async_request(
                "GET", "/watch-info/scenes", params={"device": device}
            )
            or []
        )

    async def async_set_scene(self, code: str, scene_uuid: str, on: bool) -> None:
        """PUT /doorcy-relay/<code>/scene/<uuid>/status/<on|off>."""
        state = "on" if on else "off"
        await self._async_request(
            "PUT", f"/doorcy-relay/{code}/scene/{scene_uuid}/status/{state}"
        )

    async def async_connect_live(self) -> aiohttp.ClientWebSocketResponse:
        """Open the live websocket; scene changes arrive as scene_status."""
        token = await self._async_token()
        try:
            return await self._session.ws_connect(
                WS_URL, headers={"Authorization": f"Bearer {token}"}, heartbeat=30
            )
        except aiohttp.WSServerHandshakeError as err:
            # The server closes before accepting when the token is not good.
            if err.status in (401, 403):
                raise DoorcyAuthError("Doorcy refused the live connection") from err
            raise DoorcyConnectionError(str(err)) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DoorcyConnectionError(str(err)) from err
