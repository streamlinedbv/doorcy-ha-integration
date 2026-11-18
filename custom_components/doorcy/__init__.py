"""The Doorcy integration."""

from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    DoorcyAccessDeniedError,
    DoorcyAuthError,
    DoorcyClient,
    DoorcyConnectionError,
)
from .const import DOMAIN, TOKEN_RENEW_MARGIN
from .coordinator import DoorcyCoordinator
from .oauth import async_register_built_in

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.EVENT]

type DoorcyConfigEntry = ConfigEntry[DoorcyCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the built-in sign-in (public client, PKCE).

    Application credentials a user entered earlier stay available next to
    it, so entries made with them keep loading and refreshing.
    """
    async_register_built_in(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Version 1 stored the Doorcy username and password; drop them.

    The entry then has no login at all and asks the user to sign in again
    through OAuth (reauth).
    """
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, data={}, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DoorcyConfigEntry) -> bool:
    """Set up Doorcy from a config entry."""
    if "token" not in entry.data or "auth_implementation" not in entry.data:
        # Set up by an older version with a password: sign in again.
        raise ConfigEntryAuthFailed("Sign in to Doorcy again")

    try:
        implementation = (
            await config_entry_oauth2_flow.async_get_config_entry_implementation(
                hass, entry
            )
        )
    except config_entry_oauth2_flow.ImplementationUnavailableError as err:
        raise ConfigEntryNotReady(
            "OAuth application credentials are not available yet"
        ) from err

    oauth_session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    refresh_lock = asyncio.Lock()

    async def _async_access_token() -> str:
        async with refresh_lock:
            # Home Assistant only renews a token in its last 20 seconds. The
            # websocket is reconnected TOKEN_RENEW_MARGIN seconds before the
            # expiry, so renew from there on, or that reconnect would reuse
            # the old token.
            if (
                float(oauth_session.token.get("expires_at", 0)) - time.time()
                < TOKEN_RENEW_MARGIN + 30
            ):
                new_token = await implementation.async_refresh_token(
                    oauth_session.token
                )
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "token": new_token}
                )
            return oauth_session.token["access_token"]

    client = DoorcyClient(async_get_clientsession(hass), _async_access_token)
    coordinator = DoorcyCoordinator(hass, entry, client, oauth_session)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except (DoorcyAuthError,) as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except DoorcyAccessDeniedError as err:
        raise ConfigEntryError(str(err)) from err
    except DoorcyConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # The websocket lives and dies with the entry.
    entry.async_create_background_task(
        hass, coordinator.async_run_live(), f"{DOMAIN}_live"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DoorcyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
