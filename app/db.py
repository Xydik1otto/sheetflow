"""SQLite database layer for SheetFlow.

Schema-first, stdlib sqlite3 — no ORM, keeps the MVP small and auditable.
"""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get(
    "SHEETFLOW_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sheetflow.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_file TEXT NOT NULL,
    mapping_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    item TEXT,
    quantity INTEGER,
    status TEXT NOT NULL DEFAULT 'new',
    assignee TEXT,
    due_date TEXT,
    amount REAL,
    extra_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user TEXT NOT NULL,
    collection_id INTEGER,
    row_id INTEGER,
    action TEXT NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT
);

CREATE TABLE IF NOT EXISTS reminder_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    collection_id INTEGER,
    row_id INTEGER,
    due_date TEXT,
    recipient TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    sent_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_rows_collection ON rows(collection_id);
CREATE INDEX IF NOT EXISTS idx_audit_collection ON audit_events(collection_id);
CREATE INDEX IF NOT EXISTS idx_audit_row ON audit_events(row_id);
CREATE INDEX IF NOT EXISTS idx_outbox_row ON reminder_outbox(row_id, due_date);
"""

# Columns added after the initial MVP schema (checked/applied by init_db).
MIGRATIONS = {
    "collections": {"calc_json": "ALTER TABLE collections ADD COLUMN calc_json TEXT"},
}

DEFAULT_STATUSES = ["new", "in_progress", "done", "blocked"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def db():
    """FastAPI dependency: yields a sqlite3 connection, commits on success,
    rolls back on exception, always closes."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | None = None) -> None:
    """Create schema (and apply light migrations). Uses DB_PATH unless db_path is given."""
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, ddl in columns.items():
                if col not in existing:
                    conn.execute(ddl)


def ensure_admin(conn: sqlite3.Connection, username: str = "admin", password: str = "admin123") -> None:
    """First user = admin. Created only if the users table is empty."""
    import hashlib

    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
        (username, pw_hash, now_iso()),
    )


def audit(conn: sqlite3.Connection, user: str, action: str, collection_id: int | None = None,
          row_id: int | None = None, field: str | None = None,
          old_value: str | None = None, new_value: str | None = None) -> None:
    """Write one audit event. Every state change in SheetFlow goes through this."""
    conn.execute(
        "INSERT INTO audit_events (ts, user, collection_id, row_id, action, field, old_value, new_value) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), user, collection_id, row_id, action, field, old_value, new_value),
    )
