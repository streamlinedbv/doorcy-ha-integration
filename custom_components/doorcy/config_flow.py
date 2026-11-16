"""Config flow for Doorcy (OAuth)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DoorcyAccessDeniedError, DoorcyAuthError, DoorcyClient, DoorcyConnectionError
from .const import DOMAIN, OAUTH2_SCOPE

_LOGGER = logging.getLogger(__name__)


class DoorcyConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle the Doorcy config flow."""

    DOMAIN = DOMAIN
    VERSION = 2

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        return {"scope": OAUTH2_SCOPE}

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Sign in again (password login of version 0.1.x, or a revoked link)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Name the entry after the account that just signed in."""
        access_token = data["token"]["access_token"]

        async def _token() -> str:
            return access_token

        client = DoorcyClient(async_get_clientsession(self.hass), _token)
        try:
            account = await client.async_get_account()
        except DoorcyAuthError:
            return self.async_abort(reason="oauth_failed")
        except (DoorcyConnectionError, DoorcyAccessDeniedError):
            return self.async_abort(reason="cannot_connect")

        unique_id = str(account.get("uuid") or account.get("id") or "")
        if not unique_id:
            return self.async_abort(reason="oauth_failed")
        title = account.get("email") or unique_id

        if self.source == SOURCE_REAUTH:
            # data= replaces the old username/password data completely.
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), unique_id=unique_id, title=title, data=data
            )

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=title, data=data)
