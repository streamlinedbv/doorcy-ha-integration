"""The Doorcy integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DoorcyAuthError, DoorcyClient, DoorcyConnectionError
from .coordinator import DoorcyCoordinator

PLATFORMS: list[Platform] = [Platform.SWITCH]

type DoorcyConfigEntry = ConfigEntry[DoorcyCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: DoorcyConfigEntry) -> bool:
    """Set up Doorcy from a config entry."""
    client = DoorcyClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    try:
        await client.async_login()
    except DoorcyAuthError as err:
        # Opens the reauth flow instead of just failing.
        raise ConfigEntryAuthFailed(str(err)) from err
    except DoorcyConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = DoorcyCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DoorcyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
