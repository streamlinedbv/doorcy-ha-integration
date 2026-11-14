"""Helpers for the Doorcy tests."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "doorcy"
API = "https://api.doorcy.nl/v1"
T0 = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)


def token(expires_in: int = 3600) -> dict[str, Any]:
    return {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "token_type": "Bearer",
        "expires_in": expires_in,
        "expires_at": time.time() + expires_in,
        "scope": "full",
    }


def scene(sid: str, device: str, label: str, active: str = "false") -> dict[str, Any]:
    return {
        "label": label,
        "id": sid,
        "active": active,
        "guid": f"guid-{sid}",
        "device": device,
    }


def live(scene_id: int, active: bool, seconds: float, device: str = "dev-a") -> str:
    return json.dumps(
        {
            "type": "scene_status",
            "scene_id": scene_id,
            "device_id": device,
            "active": active,
            "timestamp": (T0 + timedelta(seconds=seconds)).isoformat(),
        }
    )


class FakeWebSocket:
    """Stands in for aiohttp's ClientWebSocketResponse."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.sent: list[Any] = []
        self.closed = False

    def push_text(self, text: str) -> None:
        self.queue.put_nowait(aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, text, None))

    def push_close(self) -> None:
        self.queue.put_nowait(aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE, 4401, None))

    async def receive(self, timeout: float | None = None) -> aiohttp.WSMessage:
        return await asyncio.wait_for(self.queue.get(), timeout)

    async def send_json(self, data: Any) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


async def settle(hass: HomeAssistant, rounds: int = 20) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)
    await hass.async_block_till_done()


async def add_credentials(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential("client-id", "client-secret"), "doorcy-cred"
    )


def make_entry(expires_in: int = 3600) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="uuid-1",
        title="joep@example.com",
        data={"auth_implementation": "doorcy-cred", "token": token(expires_in)},
    )
