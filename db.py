"""Storage layer for PULSE//ROOM.

One code path, two backends:

* **PostgreSQL** when ``DATABASE_URL`` is set (Vercel + Neon, Render, Railway,
  Fly, Supabase, ...). Serverless platforms hand every instance a read-only,
  ephemeral filesystem, so a hosted database is the only place state can live.
* **SQLite** otherwise (local ``python app.py``, PythonAnywhere, a VPS, Docker
  with a volume) — the original behaviour, unchanged.

The app writes ``?`` placeholders; they are translated for psycopg. The demo
session document is a single row that is only ever mutated inside a real
transaction (``SELECT ... FOR UPDATE`` on Postgres, ``BEGIN IMMEDIATE`` on
SQLite) so two instances cannot overwrite each other's work.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Iterator

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = os.environ.get(
    "PULSE_DB_PATH", os.path.join(BASE_DIR, "pulse_users.db")
)
IS_POSTGRES = DATABASE_URL.lower().startswith(("postgres://", "postgresql://"))
BACKEND = "postgresql" if IS_POSTGRES else "sqlite"
SESSION_ID = 1

_SECRET_SETTING = "session_secret"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pg_url() -> str:
    # Heroku/Render still hand out the legacy postgres:// scheme.
    if DATABASE_URL.startswith("postgres://"):
        return "postgresql://" + DATABASE_URL[len("postgres://"):]
    return DATABASE_URL


def _pg_connect():
    import psycopg
    from psycopg.rows import dict_row

    # prepare_threshold=None keeps us compatible with transaction-mode poolers
    # (Neon, Supabase, pgbouncer) that reject server-side prepared statements.
    return psycopg.connect(_pg_url(), row_factory=dict_row, prepare_threshold=None)


def integrity_errors() -> tuple:
    """Exception tuple for unique-constraint violations on the active backend."""
    errors: tuple = (sqlite3.IntegrityError,)
    if IS_POSTGRES:
        try:
            import psycopg

            errors = errors + (psycopg.IntegrityError,)
        except ImportError:  # pragma: no cover - psycopg missing
            pass
    return errors


class Result:
    """Small cursor stand-in that exposes rows as plain dicts."""

    __slots__ = ("_rows", "lastrowid")

    def __init__(self, rows: list[dict], lastrowid=None):
        self._rows = rows
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict]:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


class Connection:
    """Thin wrapper so both drivers accept the same ``?``-style calls."""

    def __init__(self, raw, is_postgres: bool):
        self._raw = raw
        self._is_postgres = is_postgres

    def execute(self, sql: str, params: tuple = ()) -> Result:
        if self._is_postgres:
            cur = self._raw.cursor()
            cur.execute(sql.replace("?", "%s"), params)
            rows = [dict(row) for row in cur.fetchall()] if cur.description else []
            return Result(rows)
        cur = self._raw.execute(sql, params)
        rows = [dict(row) for row in cur.fetchall()] if cur.description else []
        return Result(rows, cur.lastrowid)

    def insert_id(self, sql: str, params: tuple) -> int:
        """Run an INSERT and return the new primary key on either backend."""
        if self._is_postgres:
            row = self.execute(f"{sql} RETURNING id", params).fetchone()
            return row["id"]
        return self.execute(sql, params).lastrowid


@contextmanager
def connect() -> Iterator[Connection]:
    """Open a connection, commit on success and roll back on failure."""
    if IS_POSTGRES:
        conn = _pg_connect()
        try:
            yield Connection(conn, True)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        db_dir = os.path.dirname(os.path.abspath(SQLITE_PATH))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=15000")
            yield Connection(conn, False)
        finally:
            conn.close()


_SCHEMA_SQLITE = (
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS preferences (
        user_id INTEGER PRIMARY KEY,
        institution TEXT NOT NULL DEFAULT 'PULSE//ROOM Academy',
        default_room TEXT NOT NULL DEFAULT 'Room 204',
        notifications INTEGER NOT NULL DEFAULT 1,
        privacy_mode INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS session_state (
        id INTEGER PRIMARY KEY,
        data TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
)

_SCHEMA_POSTGRES = (
    """CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS preferences (
        user_id INTEGER PRIMARY KEY,
        institution TEXT NOT NULL DEFAULT 'PULSE//ROOM Academy',
        default_room TEXT NOT NULL DEFAULT 'Room 204',
        notifications INTEGER NOT NULL DEFAULT 1,
        privacy_mode INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS session_state (
        id INTEGER PRIMARY KEY,
        data TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
)


def init_schema() -> None:
    """Create the tables on first boot with an actionable error on failure."""
    statements = _SCHEMA_POSTGRES if IS_POSTGRES else _SCHEMA_SQLITE
    try:
        with connect() as conn:
            for statement in statements:
                conn.execute(statement)
            if not IS_POSTGRES:
                conn.execute("PRAGMA journal_mode=WAL")
    except Exception as exc:  # noqa: BLE001 - re-raised with guidance
        if IS_POSTGRES:
            raise RuntimeError(
                f"Cannot reach the PostgreSQL database from DATABASE_URL: {exc}. "
                "Check the connection string, and that the database accepts "
                "connections from your host."
            ) from exc
        raise RuntimeError(
            f"Cannot open the PULSE//ROOM database at {SQLITE_PATH!r}: {exc}. "
            "Point PULSE_DB_PATH at a writable location (for example a mounted "
            "volume such as /data/pulse_users.db), or set DATABASE_URL to use "
            "PostgreSQL instead."
        ) from exc


@contextmanager
def session_document(default_factory: Callable[[], dict]) -> Iterator[dict]:
    """Load, yield and save the single demo-session document atomically.

    The row is locked for the whole block, so concurrent instances (serverless
    functions, gunicorn workers) serialise instead of losing updates.
    """
    if IS_POSTGRES:
        conn = _pg_connect()
        try:
            with conn.transaction():
                row = conn.execute(
                    "SELECT data FROM session_state WHERE id = %s FOR UPDATE",
                    (SESSION_ID,),
                ).fetchone()
                if row is None:
                    document = default_factory()
                    conn.execute(
                        "INSERT INTO session_state(id, data, updated_at) "
                        "VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                        (SESSION_ID, json.dumps(document), _now()),
                    )
                    row = conn.execute(
                        "SELECT data FROM session_state WHERE id = %s FOR UPDATE",
                        (SESSION_ID,),
                    ).fetchone()
                document = json.loads(row["data"])
                yield document
                conn.execute(
                    "UPDATE session_state SET data = %s, updated_at = %s WHERE id = %s",
                    (json.dumps(document), _now(), SESSION_ID),
                )
        finally:
            conn.close()
        return

    db_dir = os.path.dirname(os.path.abspath(SQLITE_PATH))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    committed = False
    try:
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT data FROM session_state WHERE id = ?", (SESSION_ID,)
        ).fetchone()
        if row is None:
            document = default_factory()
            conn.execute(
                "INSERT INTO session_state(id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (id) DO NOTHING",
                (SESSION_ID, json.dumps(document), _now()),
            )
            row = conn.execute(
                "SELECT data FROM session_state WHERE id = ?", (SESSION_ID,)
            ).fetchone()
        document = json.loads(row["data"])
        yield document
        conn.execute(
            "UPDATE session_state SET data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(document), _now(), SESSION_ID),
        )
        conn.execute("COMMIT")
        committed = True
    finally:
        if not committed:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        conn.close()


def get_or_create_setting(key: str, factory: Callable[[], str]) -> str:
    """Read a value from app_settings, creating it once if it is missing.

    Used for the session secret: generated once and shared by every instance so
    a serverless deployment does not log users out between functions.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        if row:
            return row["value"]
        candidate = factory()
        conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO NOTHING",
            (key, candidate),
        )
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else candidate


def session_secret(factory: Callable[[], str]) -> str:
    """Return the persisted session secret for this database."""
    return get_or_create_setting(_SECRET_SETTING, factory)
