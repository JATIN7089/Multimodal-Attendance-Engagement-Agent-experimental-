# PULSE//ROOM — Classroom Intelligence Prototype

A Flask-based classroom dashboard prototype with an opening page, account registration/sign-in, protected workspace pages, a local browser face-detection layer, session metrics, polls, teaching moments and report exports.

## Run locally

Requirements: Python 3.10+.

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5050`. This project deliberately uses port **5050** so it does not silently show an older copy already running on port 5000. Set `PORT` to change it. The `/` route always displays the public landing page; use **Get started** to create an account, then navigate to the workspace. There is no shared default password.

The user database is created automatically as `pulse_users.db` beside `app.py` on first run (it is git-ignored and is not shipped in the ZIP). Set `PULSE_DB_PATH` to use another database path and set `SECRET_KEY` to a long random secret before deploying.

## Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

The suite covers the public pages, signup/login/logout, protected routes, session/API validation, CSV and JSON exports, and the static camera assets. It creates its own temporary database, so it never touches your local `pulse_users.db`.

## Start on Windows

1. Stop any older server terminal with `Ctrl+C`.
2. Extract the ZIP into a new folder (do not merge it into an older project folder).
3. Double-click `run_windows.bat`, or run the commands above from that folder.
4. Open `http://127.0.0.1:5050` (not the old `:5000` address).

## Pages

- `/` — landing / product introduction
- `/signup`, `/login`, `/logout` — account access
- `/dashboard` — overview dashboard
- `/live` — live camera room
- `/attendance` — searchable roster and CSV/JSON exports
- `/insights` — session indicators and trend summary
- `/moments` — session event timeline
- `/reports` — report downloads
- `/settings` — saved workspace preferences

## Project layout

```
app.py                  Flask app, routes, session/demo state and exports
requirements.txt        runtime dependency (Flask)
requirements-dev.txt    adds pytest for the test suite
run_windows.bat         one-click Windows launcher (creates .venv, port 5050)
templates/              landing, auth, workspace and section pages
static/css, static/js   dashboard styling and client logic
static/models           face-api.js model weights served locally
static/vendor           vendored face-api.js build and license
tests/test_app.py       pytest suite
```

## Important prototype limitations

- User accounts use SQLite and Werkzeug password hashing. This is a local prototype, not production-ready identity infrastructure; add CSRF protection, rate limiting, secure deployment settings, and a proper user/session model before public deployment.
- Session/roster data is seeded demo data and shared by this single-process prototype; it is not yet isolated per account or persisted as real attendance records.
- Camera frames are processed in the browser and are not uploaded to Flask. Face detection is not identity recognition and does not automatically prove attendance.
- Engagement/participation values are demo signals and must not be treated as validated psychological measurements or official student records.
