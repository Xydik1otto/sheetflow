"""Security: PBKDF2 password hashing, 24h session TTL, logout."""
import sqlite3
from datetime import datetime, timedelta

from app import db


def test_hash_password_format_and_verify():
    h = db.hash_password("secret")
    assert h.startswith("pbkdf2_sha256$200000$")
    parts = h.split("$")
    assert len(parts) == 4 and len(parts[2]) == 32 and len(parts[3]) == 64
    assert db.verify_password("secret", h)
    assert not db.verify_password("wrong", h)


def test_hashes_are_salted():
    assert db.hash_password("same") != db.hash_password("same")


def test_verify_legacy_sha256_hash():
    import hashlib
    legacy = hashlib.sha256(b"oldpass").hexdigest()
    assert db.is_legacy_hash(legacy)
    assert db.verify_password("oldpass", legacy)
    assert not db.is_legacy_hash(db.hash_password("x"))


def test_new_users_get_pbkdf2_hashes(client):
    client.post("/api/users", json={"username": "bob", "password": "pw123", "role": "worker"})
    conn = sqlite3.connect(db.DB_PATH)
    stored = conn.execute("SELECT password_hash FROM users WHERE username='bob'").fetchone()[0]
    conn.close()
    assert stored.startswith("pbkdf2_sha256$")
    # and the password works
    r = client.post("/api/login", json={"username": "bob", "password": "pw123"})
    assert r.status_code == 200


def test_legacy_hash_upgraded_on_login(client):
    conn = sqlite3.connect(db.DB_PATH)
    import hashlib
    conn.execute("UPDATE users SET password_hash = ? WHERE username='admin'",
                 (hashlib.sha256(b"admin123").hexdigest(),))
    conn.commit()
    conn.close()
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    conn = sqlite3.connect(db.DB_PATH)
    stored = conn.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
    conn.close()
    assert stored.startswith("pbkdf2_sha256$")


def test_logout_invalidates_token(client):
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    token = r.json()["token"]
    r = client.post("/api/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # the token is now dead
    r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    # logging out twice with the same token fails
    r = client.post("/api/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_expired_session_rejected_and_purged(client):
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    token = r.json()["token"]
    stale = (datetime.now() - timedelta(seconds=db.SESSION_TTL_SECONDS + 60)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("UPDATE sessions SET created_at = ? WHERE token = ?", (stale, token))
    conn.commit()
    conn.close()
    r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    conn = sqlite3.connect(db.DB_PATH)
    left = conn.execute("SELECT COUNT(*) FROM sessions WHERE token = ?", (token,)).fetchone()[0]
    conn.close()
    assert left == 0
