"""The built-in sign-in (public client, PKCE) next to older own credentials."""

from __future__ import annotations

import base64
import hashlib
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.setup import async_setup_component

from custom_components.doorcy.const import (
    OAUTH2_AUTHORIZE,
    OAUTH2_CLIENT_ID,
    OAUTH2_TOKEN,
)

from .common import API, DOMAIN, make_entry, settle
from .test_config_flow import REDIRECT
from .test_live import FakeWebSocket, setup as setup_old_entry

TOKEN_JSON = {
    "access_token": "access-2",
    "refresh_token": "refresh-2",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "full",
}


def form(call) -> dict:
    """The form fields Home Assistant posted to the token endpoint."""
    return dict(call[2])


async def test_built_in_implementation_is_registered_without_any_credentials(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})

    implementations = await config_entry_oauth2_flow.async_get_implementations(
        hass, DOMAIN
    )
    assert list(implementations) == [DOMAIN]
    impl = implementations[DOMAIN]
    assert impl.client_id == OAUTH2_CLIENT_ID
    assert impl.client_secret == ""
    assert impl.authorize_url == OAUTH2_AUTHORIZE
    assert impl.token_url == OAUTH2_TOKEN


async def test_user_flow_signs_in_without_credentials_and_with_pkce(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # No picker, no "add application credentials first" abort.
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    query = parse_qs(urlparse(result["url"]).query)
    assert result["url"].startswith(OAUTH2_AUTHORIZE)
    assert query["client_id"] == [OAUTH2_CLIENT_ID]
    assert query["scope"] == ["full"]
    assert query["code_challenge_method"] == ["S256"]
    challenge = query["code_challenge"][0]

    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT}
    )
    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200

    aioclient_mock.post(OAUTH2_TOKEN, json=TOKEN_JSON)
    aioclient_mock.get(
        f"{API}/account/me", json={"uuid": "uuid-1", "email": "joep@example.com"}
    )
    with patch("custom_components.doorcy.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data["auth_implementation"] == DOMAIN
    sent = form(
        [c for c in aioclient_mock.mock_calls if c[1].path == "/oauth/token/"][0]
    )
    assert sent["client_id"] == OAUTH2_CLIENT_ID
    assert not sent.get("client_secret")
    verifier = sent["code_verifier"]
    digest = hashlib.sha256(verifier.encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == challenge


async def test_entry_of_the_built_in_sign_in_refreshes_without_a_secret(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(OAUTH2_TOKEN, json=TOKEN_JSON)
    aioclient_mock.get(f"{API}/watch-info/devices", json=[])
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="uuid-1",
        title="joep@example.com",
        data={**make_entry(100).data, "auth_implementation": DOMAIN},
    )
    entry.add_to_hass(hass)
    ws = FakeWebSocket()

    async def _connect(self):
        await self._async_token()
        return ws

    with patch(
        "custom_components.doorcy.api.DoorcyClient.async_connect_live", _connect
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await settle(hass)

    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.data["token"]["access_token"] == "access-2"
    sent = form(
        [c for c in aioclient_mock.mock_calls if c[1].path == "/oauth/token/"][0]
    )
    assert sent["grant_type"] == "refresh_token"
    assert sent["client_id"] == OAUTH2_CLIENT_ID
    assert not sent.get("client_secret")


async def test_old_entry_with_own_credentials_still_loads_and_refreshes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Entry made before 1.3.0 with the user's own application credentials."""
    aioclient_mock.post(OAUTH2_TOKEN, json=TOKEN_JSON)
    entry, patcher = await setup_old_entry(
        hass, aioclient_mock, [FakeWebSocket()], expires_in=100
    )
    try:
        assert entry.data["auth_implementation"] == "doorcy-cred"
        assert entry.state is config_entries.ConfigEntryState.LOADED
        assert entry.data["token"]["access_token"] == "access-2"
        sent = form(
            [c for c in aioclient_mock.mock_calls if c[1].path == "/oauth/token/"][0]
        )
        # Still its own client, not the built-in public one.
        assert sent["client_id"] == "client-id"
        assert sent["client_secret"] == "client-secret"
        assert "code_verifier" not in sent
    finally:
        patcher.stop()


async def test_picker_offers_both_when_own_credentials_exist(
    hass: HomeAssistant,
) -> None:
    from .common import add_credentials

    await add_credentials(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick_implementation"
    options = result["data_schema"].schema["implementation"].container
    assert set(options) == {DOMAIN, "doorcy-cred"}
