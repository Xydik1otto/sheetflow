"""Saved (named) filters: named views per collection with audit."""
import sqlite3

from app import db
from tests.conftest import SAMPLE_MAPPING


def make_collection(client, name="Замовлення"):
    from tests.conftest import make_xlsx, SAMPLE_ROWS
    r = client.post("/api/import/upload", files={"file": ("f.xlsx", make_xlsx(SAMPLE_ROWS))})
    upload_id = r.json()["upload_id"]
    r = client.post("/api/import/map", json={"upload_id": upload_id, "name": name, "mapping": SAMPLE_MAPPING})
    return r.json()["collection_id"]


def test_save_list_and_delete_filter(client):
    cid = make_collection(client)
    r = client.post(f"/api/collections/{cid}/filters",
                    json={"name": "Прострочені", "filters": {"overdue": True, "q": "кава"}})
    assert r.status_code == 200 and r.json()["ok"] is True
    lst = client.get(f"/api/collections/{cid}/filters").json()
    assert [f["name"] for f in lst] == ["Прострочені"]
    assert lst[0]["filters"] == {"overdue": True, "q": "кава"}
    fid = lst[0]["id"]
    r = client.delete(f"/api/filters/{fid}")
    assert r.status_code == 200
    assert client.get(f"/api/collections/{cid}/filters").json() == []


def test_empty_name_or_filters_rejected(client):
    cid = make_collection(client)
    assert client.post(f"/api/collections/{cid}/filters",
                       json={"name": "  ", "filters": {"status": "new"}}).status_code == 422
    assert client.post(f"/api/collections/{cid}/filters",
                       json={"name": "X", "filters": {"unknown": "v"}}).status_code == 422
    assert client.post(f"/api/collections/{cid}/filters",
                       json={"name": "X", "filters": {}}).status_code == 422


def test_duplicate_name_rejected(client):
    cid = make_collection(client)
    r = client.post(f"/api/collections/{cid}/filters",
                    json={"name": "Мій", "filters": {"status": "new"}})
    assert r.status_code == 200
    r = client.post(f"/api/collections/{cid}/filters",
                    json={"name": "Мій", "filters": {"status": "done"}})
    assert r.status_code == 409
    # same name in another collection is fine
    cid2 = make_collection(client, "Друга")
    r = client.post(f"/api/collections/{cid2}/filters",
                    json={"name": "Мій", "filters": {"status": "done"}})
    assert r.status_code == 200


def test_filters_audited(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/filters", json={"name": "F", "filters": {"status": "done"}})
    fid = client.get(f"/api/collections/{cid}/filters").json()[0]["id"]
    client.delete(f"/api/filters/{fid}")
    audit = client.get(f"/api/collections/{cid}/audit").json()
    actions = {a["action"] for a in audit}
    assert {"filter.saved", "filter.deleted"} <= actions


def test_worker_can_save_but_not_delete_anothers(client):
    cid = make_collection(client)
    r = client.post("/api/users", json={"username": "oksana", "password": "w123", "role": "worker"})
    wtoken = client.post("/api/login", json={"username": "oksana", "password": "w123"}).json()["token"]
    w = {"Authorization": f"Bearer {wtoken}"}
    r = client.post(f"/api/collections/{cid}/filters", json={"name": "W", "filters": {"q": "чай"}})
    assert r.status_code == 200  # workers may save views too
    fid = client.get(f"/api/collections/{cid}/filters").json()[0]["id"]
    r = client.delete(f"/api/filters/{fid}", headers=w)
    assert r.status_code == 403  # not the author
    r = client.delete(f"/api/filters/{fid}")
    assert r.status_code == 200  # admin can


def test_saved_filters_table_exists_in_schema():
    conn = sqlite3.connect(":memory:")
    from app import db as db_mod
    conn.executescript(db_mod.SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(saved_filters)")}
    assert {"id", "collection_id", "name", "filter_json", "created_by", "created_at"} <= cols
