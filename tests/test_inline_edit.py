"""Tests for full-field inline editing: PUT /api/rows/{id} + audit per change."""
from app import db as db_mod


def _row_ids(client, cid):
    return {r["item"]: r["id"] for r in client.get(f"/api/collections/{cid}/rows").json()}


def test_put_updates_single_field(client, imported_collection):
    rid = _row_ids(client, imported_collection)["Кава 1кг"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"assignee": "Марія"}})
    assert r.status_code == 200
    assert r.json()["updated"] == {"assignee": "Марія"}
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    assert next(r for r in rows if r["id"] == rid)["assignee"] == "Марія"


def test_put_updates_multiple_fields_at_once(client, imported_collection):
    rid = _row_ids(client, imported_collection)["Кава 1кг"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {
        "item": "Кава 3кг", "quantity": 25, "due_date": "2026-12-31", "amount": 999.99,
    }})
    assert r.status_code == 200
    assert r.json()["updated"] == {"item": "Кава 3кг", "quantity": 25, "due_date": "2026-12-31", "amount": 999.99}
    row = next(r for r in client.get(f"/api/collections/{imported_collection}/rows").json() if r["id"] == rid)
    assert (row["item"], row["quantity"], row["due_date"], row["amount"]) == ("Кава 3кг", 25, "2026-12-31", 999.99)


def test_put_writes_one_audit_event_per_changed_field(client, imported_collection):
    rid = _row_ids(client, imported_collection)["Кава 1кг"]
    client.put(f"/api/rows/{rid}", json={"fields": {"assignee": "Марія", "quantity": 12}})
    events = [e for e in client.get(f"/api/collections/{imported_collection}/audit").json()
              if e["action"] == "row.updated" and e["row_id"] == rid]
    events.sort(key=lambda e: e["id"])
    assert [(e["field"], e["old_value"], e["new_value"]) for e in events] == [
        ("assignee", "Оля", "Марія"),
        ("quantity", "10", "12"),
    ]


def test_put_unchanged_fields_write_no_audit(client, imported_collection):
    rid = _row_ids(client, imported_collection)["Кава 1кг"]
    before = [e for e in client.get(f"/api/collections/{imported_collection}/audit").json()
              if e["action"] == "row.updated"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"assignee": "Оля"}})  # same value
    assert r.status_code == 200 and r.json()["updated"] == {}
    after = [e for e in client.get(f"/api/collections/{imported_collection}/audit").json()
             if e["action"] == "row.updated"]
    assert len(after) == len(before) == 0


def test_put_coerces_types_like_import(client, imported_collection):
    rid = _row_ids(client, imported_collection)["Кава 1кг"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"quantity": "7", "amount": "120,50"}})
    assert r.json()["updated"] == {"quantity": 7, "amount": 120.5}


def test_put_rejects_unknown_field_and_bad_value(client, imported_collection):
    rid = _row_ids(client, imported_collection)["Кава 1кг"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"hacker": "x"}})
    assert r.status_code == 422 and "not editable" in r.json()["detail"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"due_date": "завтра"}})
    assert r.status_code == 422 and "due_date" in r.json()["detail"]


def test_put_empty_body_is_rejected(client, imported_collection):
    rid = _row_ids(client, imported_collection)["Кава 1кг"]
    assert client.put(f"/api/rows/{rid}", json={"fields": {}}).status_code == 422


def test_put_clearing_a_field_sets_null_and_audits(client, imported_collection):
    rid = _row_ids(client, imported_collection)["Кава 1кг"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"due_date": None}})
    assert r.status_code == 200 and r.json()["updated"] == {"due_date": None}
    events = [e for e in client.get(f"/api/collections/{imported_collection}/audit").json()
              if e["row_id"] == rid and e["field"] == "due_date"]
    assert events[0]["old_value"] and events[0]["new_value"] is None


def test_put_missing_row_is_404(client, imported_collection):
    assert client.put("/api/rows/999999", json={"fields": {"item": "x"}}).status_code == 404


def test_patch_endpoint_keeps_old_contract(client, imported_collection):
    """PATCH (used by the status dropdown) still answers field/value."""
    rid = _row_ids(client, imported_collection)["Сіль"]
    r = client.patch(f"/api/rows/{rid}", json={"field": "status", "value": "blocked"})
    assert r.status_code == 200 and r.json() == {"ok": True, "field": "status", "value": "blocked"}


def test_inline_edit_touches_updated_at(client, imported_collection):
    rid = _row_ids(client, imported_collection)["Кава 1кг"]
    row_before = next(r for r in client.get(f"/api/collections/{imported_collection}/rows").json() if r["id"] == rid)
    client.put(f"/api/rows/{rid}", json={"fields": {"amount": 1.5}})
    row_after = next(r for r in client.get(f"/api/collections/{imported_collection}/rows").json() if r["id"] == rid)
    assert row_after["updated_at"] >= row_before["created_at"]
    assert row_after["amount"] == 1.5
