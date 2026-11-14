"""API client and message parsing."""

import pytest

from custom_components.doorcy.api import (
    DoorcyAccessDeniedError,
    DoorcyAuthError,
    DoorcyClient,
    parse_scene_status,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .common import API, live


def test_parse_scene_status():
    status = parse_scene_status(live(7, True, 5))
    assert (status.scene_id, status.device_id, status.active) == ("7", "dev-a", True)
    assert status.timestamp.tzinfo is not None


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"type": "relay_status", "relay_id": 1, "timestamp": "2026-11-14T12:00:00Z"}',
        '{"type": "scene_status", "scene_id": 1}',
        '{"type": "scene_status", "timestamp": "2026-11-14T12:00:00Z"}',
        '{"type": "pong"}',
    ],
)
def test_parse_ignores_everything_but_a_complete_scene_status(text):
    assert parse_scene_status(text) is None


async def test_requests_use_the_bearer_token(hass, aioclient_mock):
    aioclient_mock.get(f"{API}/watch-info/devices", json=[])

    async def _token():
        return "abc"

    client = DoorcyClient(async_get_clientsession(hass), _token)
    await client.async_get_devices()
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer abc"


async def test_401_is_an_auth_error_and_403_is_not(hass, aioclient_mock):
    aioclient_mock.get(f"{API}/watch-info/devices", status=401)
    aioclient_mock.get(f"{API}/watch-info/scenes", status=403)

    async def _token():
        return "abc"

    client = DoorcyClient(async_get_clientsession(hass), _token)
    with pytest.raises(DoorcyAuthError):
        await client.async_get_devices()
    with pytest.raises(DoorcyAccessDeniedError):
        await client.async_get_scenes("dev-a")
