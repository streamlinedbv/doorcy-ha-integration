"""The built-in Doorcy sign-in: a public OAuth client with PKCE."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2ImplementationWithPkce,
)

from .const import DOMAIN, OAUTH2_AUTHORIZE, OAUTH2_CLIENT_ID, OAUTH2_TOKEN


class DoorcyOAuth2Implementation(LocalOAuth2ImplementationWithPkce):
    """Sign in with a Doorcy account, no client ID or secret to enter.

    Doorcy knows this client as a public client without a secret; PKCE (S256)
    protects the authorization code instead. Entries made with this
    implementation store ``auth_implementation: doorcy``.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            DOMAIN,
            OAUTH2_CLIENT_ID,
            OAUTH2_AUTHORIZE,
            OAUTH2_TOKEN,
            client_secret="",
        )

    @property
    def name(self) -> str:
        """Label in the implementation picker (shown next to own credentials)."""
        return "Doorcy account"


@callback
def async_register_built_in(hass: HomeAssistant) -> None:
    """Make the built-in sign-in available (safe to call more than once).

    Home Assistant runs a config flow before ``async_setup`` has run for an
    integration without entries, so the flow registers it too.
    """
    config_entry_oauth2_flow.async_register_implementation(
        hass, DOMAIN, DoorcyOAuth2Implementation(hass)
    )
