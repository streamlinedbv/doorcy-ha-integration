"""Constants for the Doorcy integration."""

DOMAIN = "doorcy"
API_BASE = "https://api.doorcy.nl/v1"
WS_URL = "wss://api.doorcy.nl/ws/home-assistant"

OAUTH2_AUTHORIZE = "https://api.doorcy.nl/oauth/authorize/"
OAUTH2_TOKEN = "https://api.doorcy.nl/oauth/token/"
OAUTH2_SCOPE = "full"

# Keep the websocket alive: the server drops group membership after 24 hours
# unless it hears from us, so ping well inside that.
PING_INTERVAL = 60
# Reconnect with a fresh token this long before the access token expires. The
# server checks the token again at every message and closes on an expired one,
# so a connection must never run into its expiry.
TOKEN_RENEW_MARGIN = 120
# A connection shorter than this is never followed by an instant reconnect.
MIN_CONNECTION_SECONDS = 5
RECONNECT_DELAY_MIN = 2
RECONNECT_DELAY_MAX = 300

EVENT_SCENE_STARTED = "scene_started"
