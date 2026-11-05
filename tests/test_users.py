"""Tests for multi-user roles: admin vs worker permissions."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def worker_client(client):
    """Admin creates a worker; returns a client authenticated as that worker."""
    r = client.post("/api/users", json={"username": "oksana", "password": "w123", "role": "worker"})
    assert r.status_code == 200
    c = TestClient(app)
    r = c.post("/api/login", json={"username": "oksana", "password": "w123"})
    assert r.status_code == 200 and r.json()["role"] == "worker"
    c.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return c


def test_worker_can_view_and_edit_rows(client, worker_client, imported_collection):
    rows = worker_client.get(f"/api/collections/{imported_collection}/rows").json()
    assert len(rows) == 4
    rid = rows[0]["id"]
    r = worker_client.put(f"/api/rows/{rid}", json={"fields": {"assignee": "Оксана"}})
    assert r.status_code == 200
    # the change is audited under the worker's own name
    events = client.get(f"/api/collections/{imported_collection}/audit").json()
    change = [e for e in events if e["action"] == "row.updated" and e["field"] == "assignee"]
    assert change and change[0]["user"] == "oksana"


def test_worker_cannot_read_audit_log(worker_client, imported_collection):
    r = worker_client.get(f"/api/collections/{imported_collection}/audit")
    assert r.status_code == 403


def test_worker_cannot_import_files(worker_client, sample_xlsx):
    r = worker_client.post("/api/import/upload",
                           files={"file": ("o.xlsx", sample_xlsx, "application/x")})
    assert r.status_code == 403


def test_worker_cannot_manage_users_or_run_reminders(worker_client, imported_collection):
    assert worker_client.get("/api/users").status_code == 403
    assert worker_client.post("/api/users", json={
        "username": "evil", "password": "x", "role": "admin"}).status_code == 403
    assert worker_client.post("/api/reminders/run", json={"days_before": 3}).status_code == 403
    assert worker_client.post("/api/collections/from-template",
                              json={"template": "orders"}).status_code == 403


def test_worker_can_view_collections_export_and_formulas(client, worker_client, imported_collection):
    assert worker_client.get("/api/collections").status_code == 200
    assert worker_client.get(
        f"/api/collections/{imported_collection}/export.csv").status_code == 200
    client.put(f"/api/collections/{imported_collection}/formulas",
               json={"formulas": {"total": "=quantity*amount"}})
    rows = worker_client.get(f"/api/collections/{imported_collection}/rows").json()
    assert "total" in rows[0]


def test_me_returns_role(client, worker_client):
    me_worker = worker_client.get("/api/me").json()
    assert me_worker["role"] == "worker"
    me_admin = client.get("/api/me").json()
    assert me_admin["role"] == "admin"


def test_admin_can_list_users(client, worker_client):
    users = client.get("/api/users").json()
    assert {u["username"] for u in users} >= {"admin", "oksana"}
    assert {u["role"] for u in users} == {"admin", "worker"}


def test_duplicate_user_and_bad_role_rejected(client):
    assert client.post("/api/users", json={
        "username": "admin", "password": "x"}).status_code == 409
    assert client.post("/api/users", json={
        "username": "boss", "password": "x", "role": "superadmin"}).status_code == 422


def test_missing_or_bogus_token_is_401(tmp_path, monkeypatch):
    from app import db as db_mod
    db_mod.init_db(str(tmp_path / "auth401.db"))
    c = TestClient(app)
    assert c.get("/api/collections").status_code == 401
    c.headers.update({"Authorization": "Bearer deadbeef"})
    assert c.get("/api/collections").status_code == 401
    assert c.get("/api/health").status_code == 200  # health needs no auth


def test_worker_password_is_hashed_not_stored(client, worker_client):
    from app import db as db_mod
    row = db_mod.get_conn().execute(
        "SELECT password_hash FROM users WHERE username = 'oksana'").fetchone()
    assert row["password_hash"] != "w123" and len(row["password_hash"]) == 64
