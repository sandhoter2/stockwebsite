# Telegram Trade Tracker — Django project

Multi-app Django + DRF project with a build-free React (CDN) + Bootstrap 5 frontend.
Replaces the old FastAPI tracker that ran on http://127.0.0.1:8000.

## Apps

| App           | Purpose                                                    |
|---------------|------------------------------------------------------------|
| `core`        | Page routes (login SPA, dashboard SPA, `/healthz/`)        |
| `accounts`    | Session + token authentication APIs                        |
| `traderacker` | Channels, trades, quotes, quantity rules, Telegram messages|

## Run

```bash
./.venv/bin/python manage.py runserver 0.0.0.0:8000   # or ./tunnel.sh (adds ngrok)
```

Login: username **admin** (see local secrets/password manager for the current
password — do not commit it here). Django admin at `/admin/`. DRF browsable
API at `/api/tracker/`.

## REST API (auth required — session cookie or `Authorization: Token <key>`)

- `POST /api/auth/login/` `{username, password}` → sets session, returns API token
- `POST /api/auth/logout/` · `GET /api/auth/me/`
- `GET /api/tracker/summary/` — headline totals
- `/api/tracker/channels/` · `/api/tracker/trades/?channel=&status=&q=` ·
  `/api/tracker/quotes/` · `/api/tracker/quantities/` · `/api/tracker/messages/?channel=&q=`
- CRUD is enabled on channels/trades/quantities (also manageable via Django admin).

## Re-sync data from the legacy tracker folder

```bash
./.venv/bin/python manage.py import_legacy_data            # idempotent upsert
./.venv/bin/python manage.py import_legacy_data --dir /path/to/telegram-trade-tracker
```

Reads `groups.json`, `ledger.xlsx`, `market.json`, `quantities.json`, `states/*.json`
(default source dir: `~/Downloads/Telegram/telegram-trade-tracker`, override via
`TT_LEGACY_DIR` env var).

## Public URL via ngrok

```bash
ngrok config add-authtoken <TOKEN>   # free token: https://dashboard.ngrok.com/get-started/your-authtoken
./tunnel.sh                          # starts Django (if down) + prints https://<id>.ngrok-free.app
```

`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` already accept ngrok domains.

> Security: the admin account ships with a placeholder password that must be
> rotated **before** the ngrok URL is shared with anyone — a public tunnel with a
> known/weak admin password gives full read/write access to all data and the
> Django admin panel to anyone with the link. Set your own admin password now:
> ```
> ./.venv/bin/python manage.py changepassword admin
> ```
> Store the new password in your own password manager / local secrets — never
> commit it to this repo or paste it into README.md, chat, or any tracked file.
