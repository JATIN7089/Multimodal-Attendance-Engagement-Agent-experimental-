# Deploying PULSE//ROOM

The app runs unchanged on any Python host. Pick one row from the table and follow
that section.

| Host | Storage | Ready to go |
|---|---|---|
| **Vercel** | PostgreSQL via `DATABASE_URL` (Neon) | `vercel.json` + `api/index.py` included |
| Render | PostgreSQL or SQLite | `render.yaml` included |
| Railway | PostgreSQL or SQLite on a volume | `Procfile` included |
| Fly.io / Docker | PostgreSQL or SQLite on a volume | `Dockerfile` included |
| PythonAnywhere / VPS | SQLite on disk | `pythonanywhere_wsgi.py` included |
| Local laptop | SQLite file | `python run app.py` |

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | On Vercel/serverless | PostgreSQL connection string. When set, all state (accounts **and** the live classroom session) is stored there. |
| `SECRET_KEY` | Recommended | Signs session cookies. If omitted, a key is generated once and stored in the database, so every instance and restart shares it. |
| `PULSE_DB_PATH` | Optional | SQLite file when `DATABASE_URL` is absent. Defaults to `pulse_users.db` next to `app.py`. |
| `PORT` | Set by host | Port to bind. Defaults to `5050`. |

The app picks its backend automatically: **PostgreSQL if `DATABASE_URL` starts with
`postgres://` or `postgresql://`, SQLite otherwise**.

## Option 1 — Vercel (needs a free Postgres)

Vercel functions have a **read-only, ephemeral filesystem**, so SQLite cannot be
used there. The repo ships everything else it needs (`api/index.py`, `vercel.json`),
and the app keeps accounts and the live session in Postgres.

**Step 1 — create the database (2 minutes)**

1. Sign up at https://neon.com (free, no card) → **Create project**.
2. Copy the connection string; it looks like
   `postgresql://user:password@ep-xxx.aws.neon.tech/neondb?sslmode=require`.

**Step 2 — import the repo on Vercel**

1. https://vercel.com → **Add New… → Project** → import this repository.
2. Framework preset: **Other** (leave build/output settings empty — `vercel.json` handles it).
3. **Environment Variables** → add:
   - `DATABASE_URL` = the Neon string from step 1
   - `SECRET_KEY` = any long random value (e.g. `python -c "import secrets;print(secrets.token_hex(32))"`)
4. **Deploy**. The first request creates the tables automatically.

**Step 3 — verify**

```bash
curl -s https://YOUR-APP.vercel.app/api/health     # {"status":"ok"}
```

Open the URL: the landing page shows, **Get started** creates an account, and the
dashboard, live room, attendance, insights, moments, reports and settings pages all
work. Run `vercel --prod` from the repo root if you prefer the CLI.

> Everything routes through one Python function, including `/static/*`, so the
> camera model files are served by Flask from the bundle (`includeFiles` in
> `vercel.json` keeps `templates/` and `static/` with the function). No extra
> static hosting is required.

## Option 2 — Render

`render.yaml` is included, so this is one click.

1. **New → Blueprint** → pick this repo → **Apply**. Render creates the
   `pulse-room` service (gunicorn start command, `/api/health` health check,
   auto-generated `SECRET_KEY`).
2. Add `DATABASE_URL` (Neon/Render Postgres, free tier available) for durable
   storage; without it the app uses SQLite and accounts reset on every deploy
   because the free filesystem is ephemeral.

Manual setup instead of the blueprint:

- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60`
- Health check path: `/api/health`

The free instance sleeps after ~15 minutes idle (first request afterwards takes
30-60s). Keep it warm with a free pinger (cron-job.org or UptimeRobot) hitting
`https://YOUR-APP.onrender.com/api/health` every 10 minutes.

## Option 3 — Railway

1. **New Project → Deploy from GitHub repo**; Railway reads the `Procfile`.
2. Add `SECRET_KEY`, and `DATABASE_URL` (Railway Postgres) or a volume mounted at
   `/data` with `PULSE_DB_PATH=/data/pulse_users.db`.

## Option 4 — Fly.io / Docker

```bash
docker build -t pulse-room .
docker run -p 8000:8000 -e SECRET_KEY=dev-secret-change-me pulse-room
# open http://127.0.0.1:8000
```

The image sets `PULSE_DB_PATH=/data/pulse_users.db`; mount a volume at `/data` for
persistence, or pass `DATABASE_URL` to use Postgres instead. For Fly:

```bash
fly launch --no-deploy
fly volumes create pulse_data --size 1     # then mount it at /data in fly.toml
fly secrets set SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
fly deploy
```

## Option 5 — PythonAnywhere / any WSGI host

PythonAnywhere runs WSGI apps on an always-on server with a persistent disk (free
tier included), so SQLite survives and the site never sleeps.

1. **Bash console**:
   ```bash
   git clone https://github.com/JATIN7089/Multimodal-Attendance-Engagement-Agent-experimental-.git ~/PULSE_ROOM_COMPLETE_REBUILD
   cd ~/PULSE_ROOM_COMPLETE_REBUILD
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Web → Add a new web app → Manual configuration → Python 3.10**.
3. Source code / working directory: `/home/YOUR_USER/PULSE_ROOM_COMPLETE_REBUILD`
   Virtualenv: `/home/YOUR_USER/PULSE_ROOM_COMPLETE_REBUILD/.venv`
4. Replace the **WSGI configuration file** contents with `pythonanywhere_wsgi.py`
   from this repo, updating `PROJECT_DIR`.
5. **Reload**; the site is at `https://YOUR_USER.pythonanywhere.com`.

Free-tier note: a free web app must be extended from the dashboard **once a month**
(login → Web → Extend), otherwise it expires.

## Pre-deploy checklist

- [ ] `DATABASE_URL` set on any serverless host (Vercel, or Render/Railway without a disk).
- [ ] `SECRET_KEY` set to a long random value (optional — otherwise stored in the database).
- [ ] HTTPS enabled by the host (Vercel/Render/Railway/Fly do this automatically).
- [ ] `/api/health` returns `{"status":"ok"}`.
- [ ] Prototype limitations in the README still apply: demo roster data, no CSRF
      tokens or rate limiting, and face detection that is not identity recognition.
      Put real auth in front of it before exposing student data.

## Where state lives

| Data | Stored in |
|---|---|
| Accounts, password hashes, preferences | `users` / `preferences` tables |
| Live classroom session (poll, ticks, timeline, moments) | single row in `session_state` |
| Generated session secret | `app_settings` |

The session row is read-modify-written inside a database transaction
(`SELECT … FOR UPDATE` on Postgres, `BEGIN IMMEDIATE` on SQLite), so multiple
serverless instances or gunicorn workers stay consistent instead of losing polls
and progress.

## Running the test suite

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q                  # SQLite backend (default)
PULSE_TEST_DATABASE_URL=postgresql://... python -m pytest tests -q   # PostgreSQL backend
```

Tests always use a throwaway database — they never touch a deployment database.
