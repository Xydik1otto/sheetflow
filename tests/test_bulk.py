"""Bulk actions: mass status change / delete with per-row audit events."""
import sqlite3

from app import db
from tests.conftest import SAMPLE_MAPPING, SAMPLE_ROWS, make_xlsx


def make_collection(client, name="Замовлення"):
    r = client.post("/api/import/upload", files={"file": ("f.xlsx", make_xlsx(SAMPLE_ROWS))})
    upload_id = r.json()["upload_id"]
    r = client.post("/api/import/map", json={"upload_id": upload_id, "name": name, "mapping": SAMPLE_MAPPING})
    return r.json()["collection_id"]


def get_ids(client, cid):
    return [r["id"] for r in client.get(f"/api/collections/{cid}/rows").json()]


def test_bulk_status_change_audits_each_row(client):
    cid = make_collection(client)
    ids = get_ids(client, cid)
    r = client.post("/api/rows/bulk", json={"ids": ids, "fields": {"status": "in_progress"}})
    assert r.status_code == 200
    d = r.json()
    assert len(d["updated"]) == len(ids) and d["failed"] == []
    rows = client.get(f"/api/collections/{cid}/rows").json()
    assert all(x["status"] == "in_progress" for x in rows)
    # one audit event per row (plus the collection.created one from import)
    audit = client.get(f"/api/collections/{cid}/audit").json()
    row_events = [a for a in audit if a["action"] == "row.updated" and a["field"] == "status"]
    assert len(row_events) == len(ids)
    assert {a["row_id"] for a in row_events} == set(ids)
    assert all(a["old_value"] != "in_progress" or a["new_value"] == "in_progress" for a in row_events)


def test_bulk_empty_ids_and_bad_field_rejected(client):
    cid = make_collection(client)
    r = client.post("/api/rows/bulk", json={"ids": [], "fields": {"status": "done"}})
    assert r.status_code == 422
    ids = get_ids(client, cid)
    r = client.post("/api/rows/bulk", json={"ids": ids[:1], "fields": {"item": "x", "evil": "x"}})
    assert r.status_code == 422 and "evil" in r.json()["detail"]


def test_bulk_reports_missing_rows(client):
    cid = make_collection(client)
    ids = get_ids(client, cid)
    r = client.post("/api/rows/bulk", json={"ids": ids[:2] + [99999], "fields": {"status": "done"}})
    d = r.json()
    assert [f["id"] for f in d["failed"]] == [99999]
    assert len(d["updated"]) == 2
    # the two valid rows were still updated and audited
    audit = client.get(f"/api/collections/{cid}/audit").json()
    updated = {a["row_id"] for a in audit if a["action"] == "row.updated"}
    assert set(ids[:2]) <= updated


def test_bulk_delete_admin_only_and_audited(client):
    cid = make_collection(client)
    ids = get_ids(client, cid)
    # worker cannot bulk-delete
    client.post("/api/users", json={"username": "oksana", "password": "w123", "role": "worker"})
    wtoken = client.post("/api/login", json={"username": "oksana", "password": "w123"}).json()["token"]
    r = client.post("/api/rows/bulk-delete", json={"ids": ids[:1]},
                    headers={"Authorization": f"Bearer {wtoken}"})
    assert r.status_code == 403
    # admin can
    r = client.post("/api/rows/bulk-delete", json={"ids": ids[:2] + [424242]})
    d = r.json()
    assert d["deleted"] == ids[:2] and [f["id"] for f in d["failed"]] == [424242]
    assert len(get_ids(client, cid)) == len(ids) - 2
    audit = client.get(f"/api/collections/{cid}/audit").json()
    deleted_events = [a for a in audit if a["action"] == "row.deleted"]
    assert {a["row_id"] for a in deleted_events} == set(ids[:2])
    assert all(a["old_value"] for a in deleted_events)


def test_bulk_validation_error_per_row(client):
    cid = make_collection(client)
    ids = get_ids(client, cid)
    r = client.post("/api/rows/bulk", json={"ids": ids, "fields": {"quantity": "abc"}})
    assert r.status_code == 200
    d = r.json()
    assert len(d["failed"]) == len(ids)
    assert all("not an integer" in f["error"] for f in d["failed"])
