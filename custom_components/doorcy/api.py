"""Async client for the Doorcy API (api.doorcy.nl).

Auth is Django REST Framework style: POST username/password to
/account/login, then send `Authorization: Token <token>` on every call.
DRF tokens do not expire, so we only log in again if one is rejected.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)


class DoorcyAuthError(Exception):
    """Credentials or token were rejected."""


class DoorcyConnectionError(Exception):
    """Doorcy could not be reached."""


class DoorcyClient:
    """Minimal client: log in, list scenes, switch scenes."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None

    async def async_login(self) -> str:
        """Trade username/password for a token."""
        try:
            resp = await self._session.post(
                f"{API_BASE}/account/login",
                json={"username": self._username, "password": self._password},
            )
        except aiohttp.ClientError as err:
            raise DoorcyConnectionError(str(err)) from err

        if resp.status in (400, 401, 403):
            raise DoorcyAuthError("Doorcy rejected the username or password")
        resp.raise_for_status()

        data = await resp.json()
        token = data.get("token") or data.get("auth_token")
        if not token:
            raise DoorcyAuthError(f"No token in login response: {list(data)}")

        self._token = token
        return token

    async def _async_request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Call the API, logging in again once if the token is rejected."""
        if self._token is None:
            await self.async_login()

        for attempt in (1, 2):
            try:
                resp = await self._session.request(
                    method,
                    f"{API_BASE}{path}",
                    headers={"Authorization": f"Token {self._token}"},
                    **kwargs,
                )
            except aiohttp.ClientError as err:
                raise DoorcyConnectionError(str(err)) from err

            if resp.status in (401, 403):
                if attempt == 1:
                    _LOGGER.debug("Token rejected, logging in again")
                    self._token = None
                    await self.async_login()
                    continue
                raise DoorcyAuthError("Doorcy rejected the stored credentials")

            resp.raise_for_status()
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
                _LOGGER.warning(
                    "Non-JSON response from %s: %.200s", path, text)
                return None

        raise DoorcyConnectionError("Unreachable")

    async def async_get_devices(self) -> Any:
        """GET /watch-info/devices -- compact device list."""
        return await self._async_request("GET", "/watch-info/devices")

    async def async_get_scenes(self, device: str) -> list[dict[str, Any]]:
        """GET /watch-info/scenes?device=<code|favorites>."""
        return await self._async_request(
            "GET", "/watch-info/scenes", params={"device": device}
        ) or []

    async def async_set_scene(self, code: str, scene_uuid: str, on: bool) -> None:
        """PUT /doorcy-relay/<code>/scene/<uuid>/status/<on|off>."""
        state = "on" if on else "off"
        await self._async_request(
            "PUT", f"/doorcy-relay/{code}/scene/{scene_uuid}/status/{state}"
        )
