"""Config flow for Doorcy (username / password)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DoorcyAuthError, DoorcyClient, DoorcyConnectionError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class DoorcyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Doorcy config flow."""

    VERSION = 1

    async def _async_validate(self, data: Mapping[str, Any]) -> dict[str, str]:
        """Try the credentials, return a dict of form errors (empty if fine)."""
        client = DoorcyClient(
            async_get_clientsession(self.hass),
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
        try:
            await client.async_login()
        except DoorcyAuthError:
            return {"base": "invalid_auth"}
        except DoorcyConnectionError:
            return {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Doorcy credentials")
            return {"base": "unknown"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()

            errors = await self._async_validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered when the stored password stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            new_data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            errors = await self._async_validate(new_data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=new_data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
            errors=errors,
        )
