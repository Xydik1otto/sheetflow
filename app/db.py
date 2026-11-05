"""SQLite database layer for SheetFlow.

Schema-first, stdlib sqlite3 — no ORM, keeps the MVP small and auditable.
"""
import hashlib
import hmac
import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.environ.get(
    "SHEETFLOW_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sheetflow.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
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

CREATE TABLE IF NOT EXISTS saved_filters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    filter_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(collection_id, name)
);

CREATE INDEX IF NOT EXISTS idx_rows_collection ON rows(collection_id);
CREATE INDEX IF NOT EXISTS idx_audit_collection ON audit_events(collection_id);
CREATE INDEX IF NOT EXISTS idx_audit_row ON audit_events(row_id);
CREATE INDEX IF NOT EXISTS idx_outbox_row ON reminder_outbox(row_id, due_date);
"""

# Columns added after the initial MVP schema (checked/applied by init_db).
MIGRATIONS = {
    "collections": {"calc_json": "ALTER TABLE collections ADD COLUMN calc_json TEXT"},
    "users": {"role": "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'"},
}

DEFAULT_STATUSES = ["new", "in_progress", "done", "blocked"]


SESSION_TTL_SECONDS = 24 * 3600  # sessions expire after 24 hours
PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random per-user salt (stdlib hashlib).

    Format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    """
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def is_legacy_hash(stored: str) -> bool:
    """Old v0.3.0 hashes were bare unsalted sha256 hex digests."""
    return len(stored) == 64 and all(c in "0123456789abcdef" for c in stored)


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a PBKDF2 (or legacy sha256) hash."""
    if is_legacy_hash(stored):
        return hmac.compare_digest(stored, hashlib.sha256(password.encode()).hexdigest())
    try:
        _scheme, iterations, salt, digest = stored.split("$", 3)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        ).hex()
        return hmac.compare_digest(digest, candidate)
    except (ValueError, TypeError):
        return False


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
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return
    conn.execute(
        "INSERT INTO users (username, password_hash, role, is_admin, created_at) VALUES (?, ?, 'admin', 1, ?)",
        (username, hash_password(password), now_iso()),
    )


def create_user(conn: sqlite3.Connection, username: str, password: str, role: str = "worker") -> int:
    """Create a user with a role ('admin' | 'worker'). Raises ValueError on duplicates/bad role."""
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}; available: {', '.join(ROLES)}")
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        raise ValueError(f"User {username!r} already exists")
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, role, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
        (username, hash_password(password), role, 1 if role == "admin" else 0, now_iso()),
    )
    return cur.lastrowid


def get_user_by_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    """Resolve a session bearer token to its user row.

    Sessions expire after SESSION_TTL_SECONDS (24h); expired sessions are
    purged from the table on every lookup.
    """
    cutoff = (datetime.now() - timedelta(seconds=SESSION_TTL_SECONDS)).isoformat(timespec="seconds")
    conn.execute("DELETE FROM sessions WHERE created_at < ?", (cutoff,))
    conn.commit()
    return conn.execute(
        "SELECT u.id, u.username, u.role FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ? AND s.created_at >= ?",
        (token, cutoff),
    ).fetchone()


def delete_session(conn: sqlite3.Connection, token: str) -> bool:
    """Remove one session (logout). Returns True if it existed."""
    cur = conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    return cur.rowcount > 0


ROLES = ("admin", "worker")


def audit(conn: sqlite3.Connection, user: str, action: str, collection_id: int | None = None,
          row_id: int | None = None, field: str | None = None,
          old_value: str | None = None, new_value: str | None = None) -> None:
    """Write one audit event. Every state change in SheetFlow goes through this."""
    conn.execute(
        "INSERT INTO audit_events (ts, user, collection_id, row_id, action, field, old_value, new_value) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), user, collection_id, row_id, action, field, old_value, new_value),
    )
