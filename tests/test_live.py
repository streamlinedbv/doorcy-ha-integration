"""Live updates: setup, ordering, reconnects, reauth."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from custom_components.doorcy.api import DoorcyAuthError, DoorcyConnectionError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from custom_components.doorcy.const import OAUTH2_TOKEN
from custom_components.doorcy.coordinator import scene_started_signal

from .common import (
    API,
    DOMAIN,
    FakeWebSocket,
    add_credentials,
    live,
    make_entry,
    scene,
    settle,
)

DEVICES = [{"id": "dev-a", "label": "Doorcy A"}, {"id": "dev-b", "label": "Doorcy B"}]


def mock_api(aioclient_mock):
    aioclient_mock.get(f"{API}/watch-info/devices", json=DEVICES)
    aioclient_mock.get(
        f"{API}/watch-info/scenes",
        json=[scene("7", "dev-a", "Gate")],
    )
    return aioclient_mock


def scenes_by_device(aioclient_mock):
    aioclient_mock.get(
        f"{API}/watch-info/scenes?device=dev-a",
        json=[scene("7", "dev-a", "Gate")],
    )
    aioclient_mock.get(
        f"{API}/watch-info/scenes?device=dev-b",
        json=[scene("9", "dev-b", "Door")],
    )
    aioclient_mock.get(f"{API}/watch-info/devices", json=DEVICES)


async def setup(hass, aioclient_mock, sockets, expires_in=3600):
    """Set the entry up; `sockets` are handed out per connect."""
    await add_credentials(hass)
    scenes_by_device(aioclient_mock)
    entry = make_entry(expires_in)
    entry.add_to_hass(hass)
    handed = iter(sockets)

    async def _connect(self):
        await self._async_token()  # as the real one does: renews the token
        nxt = next(handed)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    patcher = patch(
        "custom_components.doorcy.api.DoorcyClient.async_connect_live", _connect
    )
    patcher.start()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    return entry, patcher


def starts(hass, entry):
    seen = []
    async_dispatcher_connect(
        hass,
        scene_started_signal(entry.entry_id),
        lambda guid, status: seen.append((guid, status.active, status.timestamp)),
    )
    return seen


async def test_entities_for_every_doorcy(hass, aioclient_mock):
    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert sorted(e.unique_id for e in entries) == [
            "doorcy_scene_guid-7",
            "doorcy_scene_guid-9",
            "doorcy_scene_started_guid-7",
            "doorcy_scene_started_guid-9",
        ]
        assert entry.runtime_data.update_interval is None
        assert hass.states.get("switch.doorcy_a_gate").state == "off"
        assert hass.states.get("switch.doorcy_b_door").state == "off"
    finally:
        patcher.stop()


async def test_live_message_flips_the_switch_and_fires_the_event(hass, aioclient_mock):
    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        seen = starts(hass, entry)
        ws.push_text(live(7, True, 1))
        await settle(hass)
        assert hass.states.get("switch.doorcy_a_gate").state == "on"
        assert hass.states.get("switch.doorcy_b_door").state == "off"
        event = hass.states.get("event.doorcy_a_gate_started")
        assert event.attributes["event_type"] == "scene_started"
        assert event.attributes["scene_id"] == "7"
        assert [s[0] for s in seen] == ["guid-7"]
    finally:
        patcher.stop()


async def test_pulse_in_reverse_order_misses_no_start_and_ends_off(hass, aioclient_mock):
    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        seen = starts(hass, entry)
        # The stop (t=2) is handled before the start (t=1).
        ws.push_text(live(7, False, 2))
        ws.push_text(live(7, True, 1))
        await settle(hass)
        assert len(seen) == 1 and seen[0][1] is True  # the start is not lost
        assert hass.states.get("switch.doorcy_a_gate").state == "off"
        assert hass.states.get("event.doorcy_a_gate_started").attributes[
            "event_type"
        ] == "scene_started"
    finally:
        patcher.stop()


async def test_newest_timestamp_wins_in_both_orders(hass, aioclient_mock):
    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        ws.push_text(live(7, True, 5))
        ws.push_text(live(7, False, 3))  # older, arrives late
        await settle(hass)
        assert hass.states.get("switch.doorcy_a_gate").state == "on"
        ws.push_text(live(7, False, 6))
        await settle(hass)
        assert hass.states.get("switch.doorcy_a_gate").state == "off"
    finally:
        patcher.stop()


async def test_no_polling_after_setup_only_after_connect(hass, aioclient_mock):
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from homeassistant.util import dt as dt_util

    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        calls = aioclient_mock.call_count
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1))
        await settle(hass)
        # (a ping may be sent, but no REST poll)
        assert aioclient_mock.call_count == calls
    finally:
        patcher.stop()


async def test_reconnect_polls_again(hass, aioclient_mock):
    first, second = FakeWebSocket(), FakeWebSocket()
    with patch("custom_components.doorcy.coordinator.RECONNECT_DELAY_MIN", 0):
        entry, patcher = await setup(hass, aioclient_mock, [first, second])
        try:
            polls = [c for c in aioclient_mock.mock_calls if "watch-info/scenes" in str(c[1])]
            first.push_close()
            await settle(hass)
            after = [c for c in aioclient_mock.mock_calls if "watch-info/scenes" in str(c[1])]
            assert len(after) > len(polls)
            second.push_text(live(9, True, 1, "dev-b"))
            await settle(hass)
            assert hass.states.get("switch.doorcy_b_door").state == "on"
        finally:
            patcher.stop()


async def test_a_token_inside_the_renew_margin_is_renewed_before_connecting(
    hass, aioclient_mock
):
    # Home Assistant itself would keep a token that has 100 s left.
    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws], expires_in=100)
    try:
        assert entry.data["token"]["access_token"] == "access-2"
        assert not ws.closed  # the fresh token is not inside the margin
    finally:
        patcher.stop()


async def test_socket_is_dropped_when_its_token_gets_close_to_expiry(
    hass, aioclient_mock
):
    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        coordinator = entry.runtime_data
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                "token": {**entry.data["token"], "expires_at": time.time() + 100},
            },
        )
        # The server closes a socket on the first message after its token
        # expired, so the client must leave first.
        assert await coordinator._async_read(FakeWebSocket()) is True
    finally:
        patcher.stop()


async def test_idle_socket_gets_a_ping(hass, aioclient_mock):
    ws = FakeWebSocket()
    real_receive = ws.receive

    async def quick(timeout=None):
        return await real_receive(0.01)

    ws.receive = quick
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        import asyncio

        await asyncio.sleep(0.1)
        assert {"type": "ping"} in ws.sent
    finally:
        patcher.stop()


async def test_unknown_scene_triggers_a_refresh(hass, aioclient_mock):
    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        before = aioclient_mock.call_count
        ws.push_text(live(555, True, 1))
        await settle(hass)
        assert aioclient_mock.call_count > before
    finally:
        patcher.stop()


async def test_refused_connection_starts_reauth(hass, aioclient_mock):
    entry, patcher = await setup(hass, aioclient_mock, [DoorcyAuthError("no")])
    try:
        flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert [f["context"]["source"] for f in flows] == ["reauth"]
    finally:
        patcher.stop()


async def test_connection_error_keeps_retrying(hass, aioclient_mock):
    ws = FakeWebSocket()
    with patch("custom_components.doorcy.coordinator.RECONNECT_DELAY_MIN", 0):
        entry, patcher = await setup(
            hass, aioclient_mock, [DoorcyConnectionError("down"), ws]
        )
        try:
            ws.push_text(live(7, True, 1))
            await settle(hass)
            assert hass.states.get("switch.doorcy_a_gate").state == "on"
        finally:
            patcher.stop()


async def test_switch_sends_bearer_put(hass, aioclient_mock):
    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        aioclient_mock.put(f"{API}/doorcy-relay/dev-a/scene/guid-7/status/on", status=204)
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.doorcy_a_gate"}, blocking=True
        )
        put = [c for c in aioclient_mock.mock_calls if c[0] == "PUT"][0]
        assert put[3]["Authorization"] == "Bearer access-1"
        assert hass.states.get("switch.doorcy_a_gate").state == "on"
    finally:
        patcher.stop()


async def test_unload_stops_the_live_task(hass, aioclient_mock):
    ws = FakeWebSocket()
    entry, patcher = await setup(hass, aioclient_mock, [ws])
    try:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await settle(hass)
        assert entry.state is ConfigEntryState.NOT_LOADED
        assert ws.closed
    finally:
        patcher.stop()
