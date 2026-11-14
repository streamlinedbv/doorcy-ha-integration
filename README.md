# Doorcy for Home Assistant

Custom integration exposing [Doorcy](https://doorcy.nl) scenes to Home
Assistant, live. Sign in with your Doorcy account (OAuth); each scene becomes a
switch you can turn on and off, plus an event that fires when the scene starts.

## Quick start

```bash
cd doorcy-ha
docker compose up -d
```

Open <http://localhost:8123>, create the local owner account (first run only),
then add the application credentials and **Add Integration → Doorcy** as
described under *Signing in*.

First boot takes 30–60 seconds while HA builds its database.

## Development loop

The integration directory is bind-mounted, so edit a `.py` on the host and
restart:

```bash
docker compose restart homeassistant
docker compose logs -f homeassistant | grep -i doorcy
```

Or via the Makefile: `make up`, `make restart`, `make logs`, `make reset`.

## Signing in

The integration signs in with OAuth, like the Doorcy Homey app. No password
is stored in Home Assistant, the access token expires and is renewed by Home
Assistant, and the link can be revoked in Doorcy.

1. In Home Assistant: **Settings → Devices & services → Application
   credentials → Add**, pick Doorcy and enter the client ID and client secret
   of the Doorcy OAuth application made for Home Assistant (redirect URI
   `https://my.home-assistant.io/redirect/oauth`, scope `full`).
2. **Add Integration → Doorcy**, sign in to Doorcy in the browser and allow
   access.

### Upgrading from 0.1.x

Version 0.1.x stored the Doorcy username and password. After the upgrade the
stored password is removed and Home Assistant asks you once to sign in again
(a *Reauthentication* notice on the integration). Add the application
credentials first (see above), then follow the notice.

## How it works

| Step | Call |
| --- | --- |
| Sign in | OAuth: `/oauth/authorize/` and `/oauth/token/`, scope `full` |
| List scenes | `GET /v1/watch-info/devices`, `GET /v1/watch-info/scenes?device=<id>` |
| Switch a scene | `PUT /v1/doorcy-relay/{code}/scene/{uuid}/status/{on\|off}` |
| Live updates | websocket `wss://api.doorcy.nl/ws/home-assistant` (`scene_status`) |

Every call sends `Authorization: Bearer <access token>`.

The scene list is fetched at setup and again after every (re)connect of the
websocket; in between there is no polling. The websocket is reconnected with a
renewed token shortly before the old one expires, and with a growing pause
when Doorcy cannot be reached. All Doorcy's the account may see are covered by
one connection.

## Entities

Per scene:

- a **switch** that shows the state and turns the scene on and off. Scenes are
  `switch` entities rather than `scene` entities because HA scenes are
  activate-only, while Doorcy supports both on and off.
- an **event** entity (`<scene> started`) that fires `scene_started` every time
  the scene starts, also for a short pulse that is over again a moment later.
  Use it as an automation trigger; the switch only shows the state.

The event data holds `scene_id`, `device_id` and `started_at` (the time Doorcy
registered the start).

## Installing via HACS

1. HACS → three-dot menu → **Custom repositories**
2. Add the repository URL, category **Integration**
3. Download, restart Home Assistant, add from Devices & Services

## Not implemented

Relays, Salto locks, access log, and call-module settings all exist in the
Doorcy API but are out of scope here.

## Tests

```bash
pip install pytest-homeassistant-custom-component
pytest
```
