"""Custom (user-defined) fields: text/number/date/select per collection."""
from tests.conftest import SAMPLE_MAPPING, SAMPLE_ROWS, make_xlsx


def make_collection(client, name="Замовлення"):
    r = client.post("/api/import/upload", files={"file": ("f.xlsx", make_xlsx(SAMPLE_ROWS))})
    upload_id = r.json()["upload_id"]
    r = client.post("/api/import/map", json={"upload_id": upload_id, "name": name, "mapping": SAMPLE_MAPPING})
    return r.json()["collection_id"]


def test_add_and_list_custom_fields(client):
    cid = make_collection(client)
    r = client.post(f"/api/collections/{cid}/fields",
                    json={"name": "contract_no", "label": "№ договору", "type": "text"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["name"] == "contract_no" and d["type"] == "text"
    fields = client.get(f"/api/collections/{cid}/fields").json()
    assert [f["name"] for f in fields] == ["contract_no"]
    assert fields[0]["label"] == "№ договору"


def test_field_types_all_four(client):
    cid = make_collection(client)
    for i, t in enumerate(["text", "number", "date", "select"]):
        body = {"name": f"f_{t}", "label": t, "type": t}
        if t == "select":
            body["options"] = ["A", "B"]
        assert client.post(f"/api/collections/{cid}/fields", json=body).status_code == 200
    fields = client.get(f"/api/collections/{cid}/fields").json()
    assert [f["type"] for f in fields] == ["text", "number", "date", "select"]


def test_field_validation_rules(client):
    cid = make_collection(client)
    # reserved entity name
    r = client.post(f"/api/collections/{cid}/fields",
                    json={"name": "item", "label": "x", "type": "text"})
    assert r.status_code == 422 and "reserved" in r.json()["detail"]
    # bad identifier
    r = client.post(f"/api/collections/{cid}/fields",
                    json={"name": "bad name!", "label": "x", "type": "text"})
    assert r.status_code == 422
    # unknown type
    r = client.post(f"/api/collections/{cid}/fields",
                    json={"name": "wtf", "label": "x", "type": "boolean"})
    assert r.status_code == 422 and "Unknown field type" in r.json()["detail"]
    # select without options
    r = client.post(f"/api/collections/{cid}/fields",
                    json={"name": "region", "label": "x", "type": "select"})
    assert r.status_code == 422 and "options" in r.json()["detail"]
    # options on a non-select field
    r = client.post(f"/api/collections/{cid}/fields",
                    json={"name": "note", "label": "x", "type": "text", "options": ["a"]})
    assert r.status_code == 422
    # duplicate name
    client.post(f"/api/collections/{cid}/fields", json={"name": "dup", "label": "x", "type": "text"})
    r = client.post(f"/api/collections/{cid}/fields", json={"name": "dup", "label": "y", "type": "text"})
    assert r.status_code == 409


def test_custom_field_values_roundtrip(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/fields",
                json={"name": "priority", "label": "Пріоритет", "type": "select",
                      "options": ["high", "low"]})
    client.post(f"/api/collections/{cid}/fields",
                json={"name": "checked_at", "label": "Перевірено", "type": "date"})
    rows = client.get(f"/api/collections/{cid}/rows").json()
    rid = rows[0]["id"]
    r = client.put(f"/api/rows/{rid}",
                   json={"fields": {"priority": "high", "checked_at": "31.12.2026"}})
    assert r.status_code == 200, r.text
    vals = r.json()["values"]
    assert vals["priority"] == "high" and vals["checked_at"] == "2026-12-31"
    # values visible in the row listing
    row = next(x for x in client.get(f"/api/collections/{cid}/rows").json() if x["id"] == rid)
    assert row["priority"] == "high" and row["checked_at"] == "2026-12-31"
    # empty value clears the field
    r = client.put(f"/api/rows/{rid}", json={"fields": {"priority": None}})
    assert r.status_code == 200 and r.json()["values"]["priority"] is None


def test_custom_field_type_errors_rejected(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/fields",
                json={"name": "budget", "label": "Бюджет", "type": "number"})
    client.post(f"/api/collections/{cid}/fields",
                json={"name": "stage", "label": "Етап", "type": "select", "options": ["todo", "done"]})
    rows = client.get(f"/api/collections/{cid}/rows").json()
    rid = rows[0]["id"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"budget": "не число"}})
    assert r.status_code == 422 and "not a number" in r.json()["detail"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"stage": "unknown"}})
    assert r.status_code == 422 and "must be one of" in r.json()["detail"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"checked_at": "someday"}})
    assert r.status_code == 422


def test_custom_fields_are_per_collection(client):
    """A field of collection A must not be editable in collection B."""
    a = make_collection(client, "A")
    b = make_collection(client, "B")
    client.post(f"/api/collections/{a}/fields", json={"name": "only_a", "label": "x", "type": "text"})
    rid_b = client.get(f"/api/collections/{b}/rows").json()[0]["id"]
    r = client.put(f"/api/rows/{rid_b}", json={"fields": {"only_a": "x"}})
    assert r.status_code == 422 and "not editable" in r.json()["detail"]


def test_bulk_update_with_custom_field(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/fields", json={"name": "zone", "label": "Зона", "type": "text"})
    ids = [r["id"] for r in client.get(f"/api/collections/{cid}/rows").json()]
    r = client.post("/api/rows/bulk", json={"ids": ids, "fields": {"zone": "склад-1"}})
    assert r.status_code == 200 and not r.json()["failed"]
    rows = client.get(f"/api/collections/{cid}/rows").json()
    assert all(x["zone"] == "склад-1" for x in rows)
    # truly unknown fields are still rejected with 422
    r = client.post("/api/rows/bulk", json={"ids": ids[:1], "fields": {"nope": "x"}})
    assert r.status_code == 422


def test_search_finds_custom_field_values(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/fields", json={"name": "zone", "label": "Зона", "type": "text"})
    rid = client.get(f"/api/collections/{cid}/rows").json()[0]["id"]
    client.put(f"/api/rows/{rid}", json={"fields": {"zone": "Львів-склад"}})
    hits = client.get(f"/api/collections/{cid}/rows", params={"q": "львів"}).json()
    assert [r["id"] for r in hits] == [rid]


def test_delete_field_removes_values_and_audits(client):
    cid = make_collection(client)
    f = client.post(f"/api/collections/{cid}/fields",
                    json={"name": "tmp", "label": "t", "type": "text"}).json()
    rid = client.get(f"/api/collections/{cid}/rows").json()[0]["id"]
    client.put(f"/api/rows/{rid}", json={"fields": {"tmp": "значення"}})
    r = client.delete(f"/api/collections/{cid}/fields/{f['id']}")
    assert r.status_code == 200
    row = next(x for x in client.get(f"/api/collections/{cid}/rows").json() if x["id"] == rid)
    assert "tmp" not in row
    audit = client.get(f"/api/collections/{cid}/audit").json()
    assert any(e["action"] == "field.created" for e in audit)
    assert any(e["action"] == "field.deleted" for e in audit)
    # unknown field id -> 404
    assert client.delete(f"/api/collections/{cid}/fields/{f['id']}").status_code == 404


def test_worker_can_edit_values_but_not_manage_fields(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/fields", json={"name": "note2", "label": "n", "type": "text"})
    client.post("/api/users", json={"username": "w", "password": "w123", "role": "worker"})
    wt = client.post("/api/login", json={"username": "w", "password": "w123"}).json()["token"]
    wh = {"Authorization": f"Bearer {wt}"}
    rid = client.get(f"/api/collections/{cid}/rows").json()[0]["id"]
    r = client.put(f"/api/rows/{rid}", json={"fields": {"note2": "ok"}}, headers=wh)
    assert r.status_code == 200
    r = client.post(f"/api/collections/{cid}/fields",
                    json={"name": "nope", "label": "n", "type": "text"}, headers=wh)
    assert r.status_code == 403
    assert client.get(f"/api/collections/{cid}/fields", headers=wh).status_code == 200


def test_fields_require_auth_and_collection_exists(client):
    assert client.get("/api/collections/999/fields").status_code == 404
    r = client.get("/api/collections/999/fields",
                   headers={"Authorization": "Bearer bogus"})
    assert r.status_code == 401


def test_ui_has_custom_fields_panel(client):
    html = client.get("/").text
    assert 'id="fieldsPanel"' in html
    assert "Додати поле" in html
    for t in ("text", "number", "date", "select"):
        assert f"<option>{t}</option>" in html
    assert "customFields" in html and "loadFields" in html
