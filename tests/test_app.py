import csv
import io
import os
import tempfile
import uuid

import pytest

# Tests must never touch a real deployment database. By default they force the
# SQLite backend and point PULSE_DB_PATH at a throwaway file. Setting
# PULSE_TEST_DATABASE_URL runs the identical suite against PostgreSQL instead,
# which is how the serverless (Vercel/Neon) backend gets verified.
_TEST_DATABASE_URL = os.environ.get("PULSE_TEST_DATABASE_URL", "").strip()
if _TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
else:
    os.environ.pop("DATABASE_URL", None)
    _DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _DB_FILE.close()
    os.environ["PULSE_DB_PATH"] = _DB_FILE.name

import app as app_module  # noqa: E402
from app import app  # noqa: E402


@pytest.fixture
def client():
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def fresh_session():
    """Give every test a pristine demo session.

    The session document is stored in the database so that every serverless
    instance shares it, which means tests must reset the row instead of a
    module-level dict; otherwise the tick / control / poll tests leak state into
    each other and only pass in one particular order.
    """
    app_module._reset_session_document()
    yield
    app_module._reset_session_document()


@pytest.fixture
def logged_in(client):
    # A unique address per test keeps the shared temp database from rejecting
    # the second signup as a duplicate email (which silently left the client
    # logged out and made the suite order-dependent).
    email = f"test-user-{uuid.uuid4().hex[:12]}@example.com"
    response = client.post("/signup", data={
        "name": "Test User", "email": email, "password": "safe-password-123"
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Log out" in response.data
    return client


def test_public_pages_and_health(client):
    assert client.get("/").status_code == 200
    assert b"Create your workspace" in client.get("/").data
    assert client.get("/login").status_code == 200
    assert client.get("/signup").status_code == 200
    assert client.get("/api/health").get_json() == {"status": "ok"}


def test_signup_login_and_protected_pages(client):
    response = client.post("/signup", data={
        "name": "Test User", "email": "new-user@example.com", "password": "safe-password-123"
    })
    assert response.status_code == 302
    for path in ["/dashboard", "/live", "/attendance", "/insights", "/moments", "/reports", "/settings"]:
        assert client.get(path).status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/dashboard").status_code == 302
    assert client.post("/login", data={"email": "new-user@example.com", "password": "safe-password-123"}).status_code == 302


def test_api_requires_authentication(client):
    assert client.get("/api/session").status_code == 401
    assert client.post("/api/session/control", json={"action": "stop"}).status_code == 401


def test_session_has_summary_and_students(logged_in):
    data = logged_in.get("/api/session").get_json()
    assert len(data["students"]) == 24
    assert data["summary"]["present"] == 21
    assert data["summary"]["total"] == 24
    assert len(data["suggestions"]) == 3


def test_session_control_validation(logged_in):
    assert logged_in.post("/api/session/control", json={"action": "invalid"}).status_code == 400
    assert logged_in.post("/api/session/control", json={"action": "stop"}).get_json()["running"] is False
    assert logged_in.post("/api/session/control", json={"action": "start"}).get_json()["running"] is True


def test_tick_rejects_malformed_payloads(logged_in):
    """Bad client payloads must be a readable 400, never an unhandled 500."""
    for bad in [{"seconds": "abc"}, {"seconds": [1, 2]}, {"seconds": None}, {"audioLevel": "loud"}, {"audioLevel": [3]}]:
        response = logged_in.post("/api/session/tick", json=bad)
        assert response.status_code == 400, bad
        assert "error" in response.get_json()
    # An explicit null audio level falls back to a generated value instead of crashing.
    assert logged_in.post("/api/session/tick", json={"seconds": 2, "audioLevel": None}).status_code == 200
    # Non-object JSON bodies are treated as empty payloads.
    for body in [[], "text", 7]:
        response = logged_in.post("/api/session/tick", json=body)
        assert response.status_code == 200
    assert logged_in.post("/api/session/tick", data=b"not-json").status_code == 200


def test_export_csv(logged_in):
    response = logged_in.get("/api/session/export.csv")
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    assert response.status_code == 200
    assert rows[0][0] == "Student"
    assert len(rows) == 25


def test_camera_assets_and_no_frame_upload(logged_in):
    dashboard = logged_in.get("/dashboard")
    html = dashboard.get_data(as_text=True)
    assert dashboard.status_code == 200
    assert "vendor/face-api.min.js" in html
    assert "Activate vision" in html
    assert "PULSE//ROOM" in html
    for asset in [
        "/static/vendor/face-api.min.js",
        "/static/models/tiny_face_detector_model-weights_manifest.json",
        "/static/models/tiny_face_detector_model.bin",
        "/static/models/face_landmark_68_tiny_model-weights_manifest.json",
        "/static/models/face_landmark_68_tiny_model.bin",
    ]:
        response = logged_in.get(asset)
        assert response.status_code == 200
        assert len(response.data) > 100
    assert logged_in.post("/api/detect", data=b"camera-frame").status_code == 404


def test_moments_polls_and_json_report(logged_in):
    logged_in.post("/api/session/reset")
    assert logged_in.post("/api/session/checkpoint", json={"note": "x"}).status_code == 400
    checkpoint = logged_in.post("/api/session/checkpoint", json={
        "note": "Switched to a visual example and participation improved."
    })
    assert checkpoint.status_code == 201
    assert checkpoint.get_json()["events"][-1]["type"] == "note"
    poll = logged_in.post("/api/poll/start", json={
        "question": "How confident are you with this concept?",
        "options": ["Lost", "Getting there", "Confident"],
    })
    assert poll.status_code == 201
    assert poll.get_json()["poll"]["active"] is True
    tick = logged_in.post("/api/session/tick", json={"seconds": 1, "audioLevel": 20})
    assert tick.get_json()["poll"]["responses"] >= 1
    closed = logged_in.post("/api/poll/close", json={})
    assert closed.status_code == 200
    assert closed.get_json()["poll"]["active"] is False
    assert closed.get_json()["events"][-1]["type"] == "poll"
    assert logged_in.post("/api/poll/close", json={}).status_code == 409
    report = logged_in.get("/api/session/report.json")
    assert report.status_code == 200
    assert report.mimetype == "application/json"
    assert "No camera frames" in report.get_data(as_text=True)


def test_session_state_lives_in_the_database(logged_in):
    """The live session must survive process boundaries (serverless instances).

    It is stored in the database, not a module-level dict, so reading it back
    through the storage layer returns exactly what the API reported.
    """
    logged_in.post("/api/session/tick", json={"seconds": 7, "audioLevel": 21})
    api_elapsed = logged_in.get("/api/session").get_json()["elapsed"]
    from app import _read_session

    assert _read_session()["elapsed"] == api_elapsed
    assert _read_session()["audioLevel"] == 21


def test_health_reports_ok_and_backend_is_configured():
    from app import app as flask_app
    import db

    client = flask_app.test_client()
    assert client.get("/api/health").get_json() == {"status": "ok"}
    assert db.BACKEND in {"sqlite", "postgresql"}


def test_vercel_config_is_valid():
    """Guard the serverless config: Vercel rejects some shapes at validation.

    ``includeFiles`` must be a single glob string (an array fails the deploy with
    "should be string"), and it has to bundle the app module plus the templates
    and static assets the function serves at runtime.
    """
    import json
    import pathlib

    config = json.loads((pathlib.Path(__file__).parent.parent / "vercel.json").read_text())

    function = config["functions"]["api/index.py"]
    include = function["includeFiles"]
    assert isinstance(include, str), "includeFiles must be a single glob string"
    for needed in ("app.py", "db.py", "templates/**", "static/**"):
        assert needed in include, f"includeFiles must bundle {needed}"
    assert isinstance(function["maxDuration"], int)
    assert config["rewrites"][0]["destination"] == "/api/index"

    # The entry point must expose a WSGI callable named `app`.
    entry = (pathlib.Path(__file__).parent.parent / "api" / "index.py").read_text()
    assert "from app import app" in entry
