"""WSGI entry point for PythonAnywhere (and any classic WSGI host).

PythonAnywhere does not run `python app.py`; it imports a WSGI callable. In the
PythonAnywhere dashboard, open the "WSGI configuration file" link for your web
app and replace its whole contents with this file (update PROJECT_DIR below to
match your paths).

Local usage is unaffected: `python app.py` and the gunicorn Procfile still work.
"""
import os
import sys

# 1) Point this at the folder that contains app.py.
PROJECT_DIR = os.path.expanduser("~/PULSE_ROOM_COMPLETE_REBUILD")
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# 2) Optional overrides. PythonAnywhere's filesystem is persistent, so the SQLite
#    database and the auto-generated session secret survive restarts by default.
# os.environ.setdefault("PULSE_DB_PATH", os.path.join(PROJECT_DIR, "pulse_users.db"))
# os.environ.setdefault("SECRET_KEY", "paste-a-long-random-string-here")

# 3) Expose the Flask application as `application`.
from app import app as application  # noqa: E402,F401
