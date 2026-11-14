"""OAuth config flow, reauth and the migration off the password."""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow

from custom_components.doorcy.const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN

from .common import API, DOMAIN, add_credentials, settle

CLIENT_ID = "client-id"
REDIRECT = "https://example.com/auth/external/callback"


async def run_oauth(hass, hass_client_no_auth, aioclient_mock, result):
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"].startswith(OAUTH2_AUTHORIZE)
    assert f"client_id={CLIENT_ID}" in result["url"]
    assert "scope=full" in result["url"]

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    return result


async def test_user_flow_creates_an_entry_without_a_password(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host,
) -> None:
    await add_credentials(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    if result["type"] is FlowResultType.FORM:  # implementation picker
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"implementation": "doorcy-cred"}
        )
    await run_oauth(hass, hass_client_no_auth, aioclient_mock, result)

    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "refresh_token": "mock-refresh",
            "access_token": "mock-access",
            "type": "Bearer",
            "expires_in": 3600,
            "scope": "full",
        },
    )
    aioclient_mock.get(
        f"{API}/account/me", json={"uuid": "uuid-1", "email": "joep@example.com"}
    )
    with patch("custom_components.doorcy.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == "uuid-1"
    assert entry.title == "joep@example.com"
    assert entry.data["token"]["access_token"] == "mock-access"
    assert "password" not in entry.data and "username" not in entry.data
    token_call = [c for c in aioclient_mock.mock_calls if c[1].path == "/oauth/token/"][0]
    assert token_call[2]["client_id"] == CLIENT_ID


async def test_migration_drops_the_stored_password_and_asks_for_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await add_credentials(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="joep@example.com",
        data={"username": "joep@example.com", "password": "s3cret"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)

    assert entry.version == 2
    assert entry.data == {}
    assert "s3cret" not in str(entry.as_dict())
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_reauth_replaces_the_old_entry_data(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host,
) -> None:
    await add_credentials(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="joep@example.com",
        data={},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    if result["type"] is FlowResultType.FORM:  # implementation picker
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"implementation": "doorcy-cred"}
        )
    await run_oauth(hass, hass_client_no_auth, aioclient_mock, result)

    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "refresh_token": "r2",
            "access_token": "a2",
            "type": "Bearer",
            "expires_in": 3600,
        },
    )
    aioclient_mock.get(
        f"{API}/account/me", json={"uuid": "uuid-1", "email": "joep@example.com"}
    )
    with patch("custom_components.doorcy.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["token"]["access_token"] == "a2"
    assert entry.unique_id == "uuid-1"
    assert "password" not in entry.data


async def test_application_credentials_description_has_the_redirect_uri(
    hass: HomeAssistant,
) -> None:
    from custom_components.doorcy.application_credentials import (
        async_get_description_placeholders,
    )

    placeholders = await async_get_description_placeholders(hass)
    assert placeholders["redirect_uri"] == "https://my.home-assistant.io/redirect/oauth"
