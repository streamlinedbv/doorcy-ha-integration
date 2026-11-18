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
then **Add Integration → Doorcy** as described under *Signing in*.

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

1. In Home Assistant: **Settings → Devices & services → Add integration →
   Doorcy**.
2. Sign in to Doorcy in the browser and allow access.

There is no client ID or secret to enter. The integration signs in as the
public Doorcy OAuth client `doorcy-home-assistant` with PKCE (S256): there is
no secret that could leak from this public repository, and a stolen
authorization code is useless without the verifier that only your Home
Assistant holds.

### Own application credentials (optional, before 1.3.0 required)

Up to 1.2.0 you had to create credentials under **Application credentials**.
Entries made that way keep working unchanged and are not asked to sign in
again: the credentials stay registered and the entry refreshes with them. If
you still have such credentials, **Add integration** first asks which sign-in
to use; pick *Doorcy account* unless you want your own application (redirect
URI `https://my.home-assistant.io/redirect/oauth`, scope `full`).

### Upgrading from 0.1.x

Version 0.1.x stored the Doorcy username and password. After the upgrade the
stored password is removed and Home Assistant asks you once to sign in again
(a *Reauthentication* notice on the integration). Follow the notice and sign in.

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
