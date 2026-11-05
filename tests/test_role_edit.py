"""Roadmap v1.1: role management from the UI — PATCH /api/users/{id}.

Admin-only role changes, audited; the last remaining admin cannot be demoted.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def worker_id(client):
    r = client.post("/api/users", json={"username": "oksana", "password": "w123", "role": "worker"})
    assert r.status_code == 200
    return r.json()["id"]


def test_admin_can_promote_worker_to_admin(client, worker_id):
    r = client.patch(f"/api/users/{worker_id}", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["changed"] is True
    users = {u["username"]: u["role"] for u in client.get("/api/users").json()}
    assert users["oksana"] == "admin"
    events = [e for e in _audit_all(client) if e["action"] == "user.role_changed"]
    assert events and events[-1]["new_value"] == "oksana: worker -> admin"


def test_admin_can_demote_and_same_role_is_noop(client, worker_id):
    assert client.patch(f"/api/users/{worker_id}", json={"role": "worker"}).json()["changed"] is False
    users = {u["username"]: u["role"] for u in client.get("/api/users").json()}
    assert users["oksana"] == "worker"


def test_worker_cannot_change_roles(client, worker_id):
    c = TestClient(app)
    r = c.post("/api/login", json={"username": "oksana", "password": "w123"})
    c.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    assert c.patch(f"/api/users/{worker_id}", json={"role": "admin"}).status_code == 403


def test_unknown_role_and_unknown_user_rejected(client, worker_id):
    assert client.patch(f"/api/users/{worker_id}", json={"role": "superadmin"}).status_code == 422
    assert client.patch("/api/users/9999", json={"role": "worker"}).status_code == 404


def test_last_admin_cannot_be_demoted(client):
    admins = [u for u in client.get("/api/users").json() if u["role"] == "admin"]
    assert client.patch(f"/api/users/{admins[0]['id']}", json={"role": "worker"}).status_code == 409
    # after promoting a second admin, demotion works
    client.post("/api/users", json={"username": "boss2", "password": "pw2", "role": "admin"})
    assert client.patch(f"/api/users/{admins[0]['id']}", json={"role": "worker"}).status_code == 200


def test_role_change_is_not_visible_to_workers_via_users_list(client, worker_id):
    """The users panel stays admin-only (GET /api/users is guarded too)."""
    c = TestClient(app)
    r = c.post("/api/login", json={"username": "oksana", "password": "w123"})
    c.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    assert c.get("/api/users").status_code == 403


def test_ui_has_users_panel_with_role_select(client):
    html = client.get("/").text
    assert 'id="usersCard"' in html and "changeRole(" in html
    assert 'id="usersTable"' in html


def _audit_all(client):
    """Audit events are per-collection; a role change has collection_id NULL."""
    from app import db as db_mod
    with db_mod.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_events WHERE action = 'user.role_changed' ORDER BY id").fetchall()]
