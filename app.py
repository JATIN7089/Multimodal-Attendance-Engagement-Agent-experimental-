"""PULSE//ROOM — privacy-first classroom attendance and engagement demo."""
from __future__ import annotations

import csv
import io
import json
import os
import random
import secrets
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session, redirect, url_for, flash
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, render_template, request

import db

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = db.SQLITE_PATH


def _load_secret_key() -> str:
    """Return a session secret shared by every instance and every restart.

    A hard-coded fallback lets anyone forge session cookies; a purely random key
    differs per process, which logs users out whenever a request lands on a
    different worker or serverless instance. So ``SECRET_KEY`` wins when set and
    otherwise the key is generated once and stored in the database.
    """
    env_secret = os.environ.get("SECRET_KEY", "").strip()
    if env_secret:
        return env_secret
    return db.session_secret(lambda: secrets.token_hex(32))


db.init_schema()
app.secret_key = _load_secret_key()


def _db():
    """Backwards-compatible alias for the storage layer's connection factory."""
    return db.connect()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication_required"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    if not session.get("user_id"):
        return None
    with _db() as conn:
        row = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        return dict(row) if row else None

def _json_body() -> dict:
    """Always hand back a dict, even when the client sends null/list/scalar JSON.

    Without this guard a body such as ``[]`` or ``"text"`` makes every
    ``incoming.get(...)`` call raise and the API answers 500 instead of a
    readable 400.
    """
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


_RNG = random.Random(7089)

STUDENT_SEED = [
    ("Aanya Sharma", "AS", "present", 91, 8),
    ("Aarav Mehta", "AM", "present", 86, 6),
    ("Aditi Rao", "AR", "present", 82, 5),
    ("Aditya Singh", "AD", "late", 63, 2),
    ("Ananya Iyer", "AI", "present", 94, 9),
    ("Arjun Verma", "AV", "present", 76, 4),
    ("Diya Kapoor", "DK", "present", 88, 7),
    ("Ishaan Patel", "IP", "present", 72, 3),
    ("Kabir Nair", "KN", "absent", 0, 0),
    ("Kavya Joshi", "KJ", "present", 81, 5),
    ("Meera Das", "MD", "present", 93, 8),
    ("Neel Shah", "NS", "present", 69, 2),
    ("Nisha Gupta", "NG", "present", 78, 4),
    ("Pranav Bose", "PB", "present", 84, 6),
    ("Riya Jain", "RJ", "present", 87, 7),
    ("Rohan Kumar", "RK", "late", 58, 1),
    ("Saanvi Roy", "SR", "present", 90, 8),
    ("Samarth Kulkarni", "SK", "present", 75, 3),
    ("Sara Ali", "SA", "present", 85, 6),
    ("Shaurya Mishra", "SM", "present", 71, 3),
    ("Tanvi Reddy", "TR", "present", 92, 8),
    ("Vihaan Sethi", "VS", "present", 66, 2),
    ("Yash Malhotra", "YM", "absent", 0, 0),
    ("Zoya Khan", "ZK", "absent", 0, 0),
]


def _new_session() -> dict:
    now = datetime.now(timezone.utc)
    students = [
        {
            "id": i + 1,
            "name": name,
            "initials": initials,
            "status": status,
            "engagement": engagement,
            "interactions": interactions,
            "lastSeen": "Now" if status != "absent" else "—",
        }
        for i, (name, initials, status, engagement, interactions) in enumerate(STUDENT_SEED)
    ]
    values = [74, 76, 73, 79, 81, 78, 82, 77, 75, 80, 79, 78]
    return {
        "id": "DS-A-204",
        "title": "Data Science Fundamentals",
        "cohort": "Batch A",
        "room": "Room 204",
        "instructor": "Jatin",
        "startedAt": now.isoformat(),
        "elapsed": 46 * 60 + 18,
        "running": True,
        "mode": "Demo mode",
        "students": students,
        "timeline": [
            {"label": f"{9 + (i * 5 + 55) // 60}:{(i * 5 + 55) % 60:02d}", "value": value}
            for i, value in enumerate(values)
        ],
        "audioLevel": 36,
        "events": [
            {
                "id": 1,
                "time": "09:55",
                "type": "system",
                "title": "Session started",
                "detail": "Vision and audio signal layers initialized locally.",
            },
            {
                "id": 2,
                "time": "10:14",
                "type": "poll",
                "title": "Confidence pulse completed",
                "detail": "18 responses · 72% selected confident or very confident.",
            },
            {
                "id": 3,
                "time": "10:28",
                "type": "alert",
                "title": "Room momentum dipped",
                "detail": "Recovered after switching to an interactive example.",
            },
        ],
        "poll": {
            "active": False,
            "question": "",
            "options": [],
            "responses": 0,
            "startedAt": None,
        },
        "updatedAt": now.isoformat(),
    }


def _read_session() -> dict:
    """Read the demo session document without taking a write lock.

    The document lives in the database (not module memory) so every instance of
    a serverless deployment sees the same polls, ticks and timeline.
    """
    with _db() as conn:
        row = conn.execute(
            "SELECT data FROM session_state WHERE id = ?", (db.SESSION_ID,)
        ).fetchone()
    if row:
        return json.loads(row["data"])
    with db.session_document(_new_session) as document:
        return json.loads(json.dumps(document))


def _reset_session_document() -> dict:
    """Replace the stored session with a pristine one and return it."""
    with db.session_document(_new_session) as document:
        document.clear()
        document.update(_new_session())
        return json.loads(json.dumps(document))


def _summary(session_doc: dict) -> dict:
    present_students = [s for s in session_doc["students"] if s["status"] != "absent"]
    engaged = [s["engagement"] for s in present_students]
    engagement = round(sum(engaged) / max(len(engaged), 1))
    interactions = sum(s["interactions"] for s in present_students)
    # Eight meaningful interactions per learner is treated as full participation
    # for this demo session, keeping the score transparent and explainable.
    participation = min(100, round(100 * interactions / max(len(present_students) * 8, 1)))
    low = [s for s in present_students if s["engagement"] < 68]
    late = [s for s in present_students if s["status"] == "late"]
    return {
        "present": len(present_students),
        "total": len(session_doc["students"]),
        "absent": len(session_doc["students"]) - len(present_students),
        "late": len(late),
        "engagement": engagement,
        "participation": participation,
        "interactions": interactions,
        "lowAttention": len(low),
    }


def _suggestions(session_doc: dict, summary: dict) -> list[dict]:
    suggestions = []
    if summary["engagement"] <= 82:
        suggestions.append(
            {
                "type": "action",
                "icon": "spark",
                "title": "Try a 2-minute knowledge check",
                "body": "Attention has softened over the last 8 minutes. A quick poll can re-engage the room.",
                "cta": "Start quick poll",
            }
        )
    if summary["lowAttention"]:
        suggestions.append(
            {
                "type": "insight",
                "icon": "trend",
                "title": f"{summary['lowAttention']} learners may need support",
                "body": "Low visual activity was sustained—not inferred from a single frame. Consider changing pace.",
                "cta": "View learners",
            }
        )
    suggestions.append(
        {
            "type": "positive",
            "icon": "check",
            "title": "Participation is evenly distributed",
            "body": f"{summary['participation']}% of present learners have contributed during this session.",
            "cta": "See participation",
        }
    )
    return suggestions[:3]


def _payload(session_doc: dict | None = None) -> dict:
    document = _read_session() if session_doc is None else session_doc
    summary = _summary(document)
    return {**document, "summary": summary, "suggestions": _suggestions(document, summary)}


@app.after_request
def browser_permissions(response: Response) -> Response:
    """Allow this origin to use sensors while keeping camera data client-side."""
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self)"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def index():
    # Always show the new public landing page, even when the user is signed in.
    # The workspace is available explicitly at /dashboard.
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with _db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            next_path = request.args.get("next", "")
            # Only allow local absolute paths; never redirect to an external host.
            if not next_path.startswith("/") or next_path.startswith("//") or "\\" in next_path:
                next_path = url_for("dashboard")
            return redirect(next_path)
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if len(name) < 2:
            flash("Enter your full name.", "error")
        elif "@" not in email or "." not in email.split("@")[-1]:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
        else:
            try:
                with _db() as conn:
                    user_id = conn.insert_id(
                        "INSERT INTO users(name,email,password_hash) VALUES(?,?,?)",
                        (name, email, generate_password_hash(password)),
                    )
                    conn.execute("INSERT INTO preferences(user_id) VALUES(?)", (user_id,))
                session.clear()
                session["user_id"] = user_id
                session["user_name"] = name
                return redirect(url_for("dashboard"))
            except db.integrity_errors():
                flash("An account with this email already exists. Sign in instead.", "error")
    return render_template("auth.html", mode="signup")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.get("/dashboard")
@login_required
def dashboard():
    return render_template("index.html", user=current_user(), active_page="dashboard")


@app.get("/live")
@login_required
def live_room():
    return render_template("index.html", user=current_user(), active_page="live", focus_live=True)


@app.get("/attendance")
@login_required
def attendance_page():
    payload = _payload(_read_session())
    return render_template("section.html", user=current_user(), active_page="attendance", page="attendance", payload=payload)


@app.get("/insights")
@login_required
def insights_page():
    payload = _payload(_read_session())
    return render_template("section.html", user=current_user(), active_page="insights", page="insights", payload=payload)


@app.get("/moments")
@login_required
def moments_page():
    payload = _payload(_read_session())
    return render_template("section.html", user=current_user(), active_page="moments", page="moments", payload=payload)


@app.get("/reports")
@login_required
def reports_page():
    payload = _payload(_read_session())
    return render_template("section.html", user=current_user(), active_page="reports", page="reports", payload=payload)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    user = current_user()
    if not user:
        # Stale cookie after a database reset: send the visitor back to login.
        session.clear()
        return redirect(url_for("login"))
    if request.method == "POST":
        institution = request.form.get("institution", "").strip()[:100] or "PULSE//ROOM Academy"
        default_room = request.form.get("default_room", "").strip()[:60] or "Room 204"
        notifications = 1 if request.form.get("notifications") == "on" else 0
        privacy_mode = 1 if request.form.get("privacy_mode") == "on" else 0
        with _db() as conn:
            conn.execute("""INSERT INTO preferences(user_id,institution,default_room,notifications,privacy_mode)
                VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET institution=excluded.institution,
                default_room=excluded.default_room, notifications=excluded.notifications, privacy_mode=excluded.privacy_mode""",
                (user["id"], institution, default_room, notifications, privacy_mode))
        flash("Settings saved.", "success")
        return redirect(url_for("settings_page"))
    with _db() as conn:
        prefs = conn.execute("SELECT * FROM preferences WHERE user_id=?", (user["id"],)).fetchone()
    if not prefs:
        prefs = {"institution": "PULSE//ROOM Academy", "default_room": "Room 204", "notifications": 1, "privacy_mode": 1}
    return render_template("section.html", user=user, active_page="settings", page="settings", prefs=dict(prefs))


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/session")
@login_required
def get_session():
    return jsonify(_payload(_read_session()))


@app.post("/api/session/tick")
@login_required
def tick_session():
    incoming = _json_body()
    raw_seconds = incoming.get("seconds", 4)
    try:
        seconds = max(1, min(int(raw_seconds), 30))
    except (TypeError, ValueError):
        return jsonify({"error": "seconds must be an integer between 1 and 30"}), 400
    raw_audio = incoming.get("audioLevel")
    if raw_audio is None:
        audio_level = _RNG.randint(24, 58)
    else:
        try:
            audio_level = max(8, min(int(raw_audio), 100))
        except (TypeError, ValueError):
            return jsonify({"error": "audioLevel must be an integer between 8 and 100"}), 400
    with db.session_document(_new_session) as session_doc:
        if session_doc["running"]:
            session_doc["elapsed"] += seconds
            session_doc["audioLevel"] = audio_level
            poll = session_doc["poll"]
            if poll["active"] and poll["responses"] < 21 and poll["options"]:
                burst = min(_RNG.randint(1, 3), 21 - poll["responses"])
                weights = [2 + index for index in range(len(poll["options"]))]
                for _ in range(burst):
                    option = _RNG.choices(poll["options"], weights=weights, k=1)[0]
                    option["votes"] += 1
                    poll["responses"] += 1
            candidates = [s for s in session_doc["students"] if s["status"] != "absent"]
            for student in _RNG.sample(candidates, k=min(5, len(candidates))):
                student["engagement"] = max(38, min(99, student["engagement"] + _RNG.choice([-2, -1, 0, 1, 1, 2])))
                student["lastSeen"] = "Now"
            if _RNG.random() > 0.65:
                _RNG.choice(candidates)["interactions"] += 1
            avg = _summary(session_doc)["engagement"]
            if not session_doc["timeline"] or session_doc["elapsed"] % 12 < 5:
                session_doc["timeline"].append({"label": "Now", "value": avg})
                session_doc["timeline"] = session_doc["timeline"][-14:]
                for point in session_doc["timeline"][:-1]:
                    if point["label"] == "Now":
                        point["label"] = "Recent"
            session_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
        payload = _payload(session_doc)
    return jsonify(payload)


@app.post("/api/session/control")
@login_required
def control_session():
    incoming = _json_body()
    action = incoming.get("action")
    if action not in ("start", "stop"):
        return jsonify({"error": "action must be start or stop"}), 400
    with db.session_document(_new_session) as session_doc:
        session_doc["running"] = action == "start"
        session_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
        payload = _payload(session_doc)
    return jsonify(payload)


@app.post("/api/session/reset")
@login_required
def reset_session():
    return jsonify(_payload(_reset_session_document()))


def _session_clock(session_doc: dict) -> str:
    total_minutes = (9 * 60 + 55 + session_doc["elapsed"] // 60) % (24 * 60)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


@app.post("/api/session/checkpoint")
@login_required
def add_checkpoint():
    incoming = _json_body()
    note = str(incoming.get("note", "")).strip()
    if not 3 <= len(note) <= 180:
        return jsonify({"error": "note must be between 3 and 180 characters"}), 400
    with db.session_document(_new_session) as session_doc:
        event = {
            "id": max((item["id"] for item in session_doc["events"]), default=0) + 1,
            "time": _session_clock(session_doc),
            "type": "note",
            "title": "Teaching moment marked",
            "detail": note,
        }
        session_doc["events"].append(event)
        session_doc["events"] = session_doc["events"][-20:]
        session_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
        payload = _payload(session_doc)
    return jsonify(payload), 201


@app.post("/api/poll/start")
@login_required
def start_poll():
    incoming = _json_body()
    question = str(incoming.get("question", "")).strip()
    labels = incoming.get("options") or ["Lost", "Getting there", "Confident", "Ready to explain"]
    if not 5 <= len(question) <= 120:
        return jsonify({"error": "question must be between 5 and 120 characters"}), 400
    if not isinstance(labels, list) or not 2 <= len(labels) <= 4:
        return jsonify({"error": "options must contain 2 to 4 labels"}), 400
    labels = [str(label).strip()[:40] for label in labels]
    if any(not label for label in labels):
        return jsonify({"error": "poll options cannot be empty"}), 400
    with db.session_document(_new_session) as session_doc:
        session_doc["poll"] = {
            "active": True,
            "question": question,
            "options": [{"label": label, "votes": 0} for label in labels],
            "responses": 0,
            "startedAt": datetime.now(timezone.utc).isoformat(),
        }
        session_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
        payload = _payload(session_doc)
    return jsonify(payload), 201


@app.post("/api/poll/close")
@login_required
def close_poll():
    conflict = False
    with db.session_document(_new_session) as session_doc:
        poll = session_doc["poll"]
        if not poll["active"]:
            conflict = True
        else:
            poll["active"] = False
            leading = max(poll["options"], key=lambda option: option["votes"], default={"label": "No response", "votes": 0})
            event = {
                "id": max((item["id"] for item in session_doc["events"]), default=0) + 1,
                "time": _session_clock(session_doc),
                "type": "poll",
                "title": "Pulse poll completed",
                "detail": f"{poll['responses']} responses · top signal: {leading['label']} ({leading['votes']}).",
            }
            session_doc["events"].append(event)
            session_doc["events"] = session_doc["events"][-20:]
            session_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
            payload = _payload(session_doc)
    if conflict:
        return jsonify({"error": "no active poll"}), 409
    return jsonify(payload)


@app.get("/api/session/report.json")
@login_required
def export_json_report():
    session_doc = _read_session()
    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "privacy": "No camera frames, face descriptors, or biometric templates are included.",
        "session": {
            "id": session_doc["id"],
            "title": session_doc["title"],
            "cohort": session_doc["cohort"],
            "room": session_doc["room"],
            "elapsedSeconds": session_doc["elapsed"],
        },
        "summary": _summary(session_doc),
        "students": session_doc["students"],
        "timeline": session_doc["timeline"],
        "events": session_doc["events"],
        "latestPoll": session_doc["poll"],
    }
    filename = f"session-report-{datetime.now().date().isoformat()}.json"
    return Response(
        json.dumps(report, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/session/export.csv")
@login_required
def export_csv():
    session_doc = _read_session()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student", "Status", "Engagement", "Interactions", "Last seen"])
    for student in session_doc["students"]:
        writer.writerow(
            [
                student["name"],
                student["status"].title(),
                f"{student['engagement']}%" if student["status"] != "absent" else "—",
                student["interactions"],
                student["lastSeen"],
            ]
        )
    filename = f"attendance-{datetime.now().date().isoformat()}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5050")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
