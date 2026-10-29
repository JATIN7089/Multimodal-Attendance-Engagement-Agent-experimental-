# Deploying PULSE//ROOM

The app is a plain Flask app, so any Python host works. It reads `PORT` from the
environment and serves on `0.0.0.0`, so no code change is needed per platform.

Important: `python app.py` (the Flask dev server) is for local use only. In
production run it under **gunicorn**, which is already in `requirements.txt`.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | Recommended | Signs session cookies. If omitted, the app generates a key once and stores it in `.pulse_secret_key` beside the database so every worker shares it. Set it explicitly if the filesystem is read-only or reset on deploy. |
| `PULSE_DB_PATH` | Optional | SQLite file location. Defaults to `pulse_users.db` next to `app.py`. Point this at a mounted volume to keep accounts across redeploys. |
| `PORT` | Set by the host | Port to bind. Defaults to `5050`. |
| `FLASK_DEBUG` | Never in prod | `1` enables Flask debug mode. |

## Option 1 — Render (easiest, free tier)

The repo ships `render.yaml`, so this is one click after connecting the repo.

1. Push this branch and merge it to `main` (Render deploys from a branch you choose).
2. Render dashboard → **New** → **Blueprint** → select this repository.
3. Render reads `render.yaml` and creates the `pulse-room` web service:
   - build: `pip install -r requirements.txt`
   - start: `gunicorn app:app --bind 0.0.0.0:$PORT ...`
   - health check: `/api/health`
   - `SECRET_KEY` is generated automatically.
4. Click **Apply** and wait for the first build. The URL looks like
   `https://pulse-room.onrender.com`.

No `render.yaml` path? Use **New → Web Service** and fill in:

- Runtime: Python 3
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60`
- Health check path: `/api/health`

Note on the free plan: the service sleeps after ~15 minutes of inactivity (the
first request afterwards takes ~30s to wake), and the filesystem is reset on
every deploy, so **accounts are wiped on redeploy**. For persistence add a paid
disk and set `PULSE_DB_PATH` to a file on it, e.g. `/var/data/pulse_users.db`.

## Option 2 — Railway

1. Railway → **New Project** → **Deploy from GitHub repo** → pick this repository.
2. Railway detects the `Procfile` and runs gunicorn automatically.
3. Add variables: `SECRET_KEY` (any long random string) and optionally
   `PULSE_DB_PATH=/data/pulse_users.db`.
4. Add a **Volume** mounted at `/data` if you want accounts to survive redeploys.

## Option 3 — Fly.io / Docker (persistent volume)

The repo also has a `Dockerfile` for any container host (Fly, Koyeb, Cloud Run,
a VPS, `docker run`).

Local check:

```bash
docker build -t pulse-room .
docker run -p 8000:8000 -e SECRET_KEY=dev-secret-change-me pulse-room
# open http://127.0.0.1:8000
```

Fly.io:

```bash
fly launch --no-deploy          # accepts the existing Dockerfile
fly volumes create pulse_data --size 1
# in fly.toml set: [mounts] source = "pulse_data" destination = "/data"
fly secrets set SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
fly deploy
```

The Dockerfile already sets `PULSE_DB_PATH=/data/pulse_users.db`, so the volume
mount is all that is needed for persistence.

## Option 4 — PythonAnywhere

PythonAnywhere runs WSGI apps, not processes:

1. Upload/clone the repo, create a virtualenv, `pip install -r requirements.txt`.
2. Add a new **Flask** web app pointing at `app.py`; set the source dir to the repo root.
3. In the WSGI config file make sure the repo root is on `sys.path` and import
   `from app import app as application`.
4. Reload the web app. SQLite works there and persists on disk.

## Pre-deploy checklist

- [ ] `SECRET_KEY` set to a long random value (or a writable filesystem for the generated key).
- [ ] `PULSE_DB_PATH` points at persistent storage if accounts must survive redeploys.
- [ ] HTTPS enabled by the host (Render/Railway/Fly do this automatically).
- [ ] Health check `/api/health` returns `{"status":"ok"}`.
- [ ] Remember the prototype limitations in the README: demo roster data, no CSRF
      tokens or rate limiting, and face detection that is not identity recognition.
      Put auth in front of it before exposing it to real student data.

## Verify a deployment

```bash
curl -s https://YOUR-APP/api/health          # {"status":"ok"}
curl -sI https://YOUR-APP/ | head -1         # 200
```

Then open the URL: `/` shows the landing page, **Get started** creates an
account, and the workspace pages load behind the login.
