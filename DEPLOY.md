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

## Option 4 — PythonAnywhere (best free long-term option)

PythonAnywhere runs WSGI apps on an always-on server with a **persistent disk**, so
the page loads instantly whenever someone opens it and accounts survive restarts.
Free tier is enough here because the camera/face work happens in the browser.

1. Sign up at https://www.pythonanywhere.com (free "Beginner" account).
2. Open a **Bash console** and get the code:
   ```bash
   git clone https://github.com/JATIN7089/Multimodal-Attendance-Engagement-Agent-experimental-.git ~/PULSE_ROOM_COMPLETE_REBUILD
   # or upload the ZIP and run: unzip PULSE_ROOM_COMPLETE_REBUILD.zip
   cd ~/PULSE_ROOM_COMPLETE_REBUILD
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Web** tab → **Add a new web app** → **Manual configuration** → **Python 3.10**
   (do not pick the "Flask" preset; manual gives you control).
4. Set **Source code** to `/home/YOUR_USER/PULSE_ROOM_COMPLETE_REBUILD` and
   **Working directory** to the same path.
5. **Virtualenv** field: `/home/YOUR_USER/PULSE_ROOM_COMPLETE_REBUILD/.venv`.
6. Click the **WSGI configuration file** link and replace its entire contents with
   the `pythonanywhere_wsgi.py` file from this repo. Update `PROJECT_DIR` to your
   path: `/home/YOUR_USER/PULSE_ROOM_COMPLETE_REBUILD`.
7. **Static files** (optional, faster): URL `/static/` → directory
   `/home/YOUR_USER/PULSE_ROOM_COMPLETE_REBUILD/static`. Flask also serves it, so
   this is only a speed-up.
8. **Reload** the web app. Your URL is `https://YOUR_USER.pythonanywhere.com`.

Free-tier caveats: log in once every 3 months to keep the app enabled, and the
daily CPU quota is plenty for this app. Because the disk persists, both the SQLite
database and the auto-generated `.pulse_secret_key` survive restarts — no extra
configuration needed.

## Which option should I use?

| Goal | Use | Sleep? | Accounts survive? |
|---|---|---|---|
| Someone may open the link at any time, months later, for free | **PythonAnywhere free** (Option 4) | No, always on | Yes, real disk |
| Live in 5 minutes, free, demo only | **Render free** (Option 1) | Yes, ~15 min idle | No, reset on redeploy |
| Always-on server, willing to pay ~$2-4/month | **Fly.io / Railway with a volume** | No | Yes, volume |

The app is a Python process plus a SQLite file, so serverless hosts are a poor fit:
Vercel functions have a read-only filesystem (SQLite cannot write there) and Netlify
Functions do not support Python at all. Both would need the storage layer and the
in-memory session state rewritten first.

### Keep a free Render service awake

Render free instances sleep after ~15 minutes idle, so a first click afterwards
takes 30-60s and can look broken to someone reviewing it. Keep it warm with a free
external pinger hitting the health endpoint every 10 minutes:

1. Create a free account at https://cron-job.org (or UptimeRobot).
2. New cron job → URL `https://YOUR-APP.onrender.com/api/health` → every 10 minutes.
3. Confirm the job reports HTTP 200 responses.

One always-on free service fits inside Render's 750 instance hours per month. The
free plan has no disk, though, so accounts still reset whenever you redeploy.

### Data durability

SQLite lives on the filesystem. It survives restarts wherever the filesystem is
persistent (PythonAnywhere free, a paid Render disk, a Fly/Railway volume) and is
wiped wherever it is ephemeral (free Render/Railway/Fly without a volume, Docker
without a mount). Point `PULSE_DB_PATH` at the mounted volume to opt in.

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
