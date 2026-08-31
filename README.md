# Doorcy for Home Assistant

Custom integration exposing [Doorcy](https://doorcy.nl) scenes as Home
Assistant switches. Sign in with a Doorcy username and password; each scene
becomes a switch you can turn on and off.

## Quick start

```bash
cd doorcy-ha
docker compose up -d
```

Open <http://localhost:8123>, create the local owner account (first run only),
then **Settings → Devices & Services → Add Integration → Doorcy** and enter
your Doorcy credentials.

First boot takes 30–60 seconds while HA builds its database.

## Development loop

The integration directory is bind-mounted, so edit a `.py` on the host and
restart:

```bash
docker compose restart homeassistant
docker compose logs -f homeassistant | grep -i doorcy
```

Or via the Makefile: `make up`, `make restart`, `make logs`, `make reset`.

## How it works

| Step | Call |
| --- | --- |
| Sign in | `POST /v1/account/login` → `{"token": ...}` |
| List scenes | `GET /v1/watch-info/scenes?device=favorites` |
| Switch a scene | `PUT /v1/doorcy-relay/{code}/scene/{uuid}/status/{on\|off}` |

Auth is Django REST Framework style: `Authorization: Token <token>`, not
Bearer. Tokens don't expire, so the client only logs in again if one is
rejected.

Scenes are `switch` entities rather than `scene` entities because HA scenes
are activate-only, while Doorcy supports both on and off.

## Unconfirmed response shapes

Inferred from the Postman collection, which has no saved example responses.
The coordinator logs the raw scene payload at debug level on first refresh —
check `make logs` and adjust:

- **Login** assumed to return `{"token": ...}` (falls back to `auth_token`)
- **Scenes** assumed to carry `uuid`, `name`, and a device code under
  `device` (falls back to `code`, then `device_code` in `switch.py`)
- **Scene status** — if the payload has no `status` field, switches are
  marked `assumed_state`, so HA shows separate on/off buttons instead of a
  toggle that guesses

Also check whether `device=favorites` returns all scenes or only favourited
ones. If it's the latter, set `SCENES_DEVICE` in `const.py` to a device code.

## Tests

`tests/` runs the client and the full integration against a mock Doorcy
server, no credentials or network needed:

```bash
python3 -m venv .venv && .venv/bin/pip install homeassistant aiohttp
.venv/bin/python tests/run_tests.py          # API client
.venv/bin/python tests/integration_test.py   # config flow + entities
```

## Installing via HACS

1. HACS → three-dot menu → **Custom repositories**
2. Add the repository URL, category **Integration**
3. Download, restart Home Assistant, add from Devices & Services

## Not implemented

Relays, Salto locks, access log, and call-module settings all exist in the
Doorcy API but are out of scope here.
