"""Data safety: one-click JSON export of everything, guarded collection delete."""
from tests.conftest import SAMPLE_MAPPING, SAMPLE_ROWS, make_xlsx


def make_collection(client, name="Замовлення"):
    r = client.post("/api/import/upload", files={"file": ("f.xlsx", make_xlsx(SAMPLE_ROWS))})
    upload_id = r.json()["upload_id"]
    r = client.post("/api/import/map", json={"upload_id": upload_id, "name": name, "mapping": SAMPLE_MAPPING})
    return r.json()["collection_id"]


def test_export_json_contains_everything(client):
    cid = make_collection(client, "Експорт-тест")
    client.post(f"/api/collections/{cid}/fields",
                json={"name": "zone", "label": "Зона", "type": "text"})
    rid = client.get(f"/api/collections/{cid}/rows").json()[0]["id"]
    client.put(f"/api/rows/{rid}", json={"fields": {"zone": "склад-1"}})
    client.post(f"/api/collections/{cid}/filters", json={"name": "прострочені", "filters": {"overdue": True}})
    client.put(f"/api/collections/{cid}/formulas", json={"formulas": {"total": "=quantity*amount"}})
    r = client.get("/api/export/json")
    assert r.status_code == 200
    assert "application/json" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["app"] == "sheetflow" and data["exported_at"]
    coll = next(c for c in data["collections"] if c["id"] == cid)
    assert coll["name"] == "Експорт-тест"
    assert len(coll["rows"]) == 4 and coll["rows"][0]["extra_json"] is not None
    assert {f["name"] for f in coll["custom_fields"]} == {"zone"}
    assert coll["formulas"] == {"total": "=quantity*amount"}
    assert coll["saved_filters"][0]["name"] == "прострочені"


def test_export_json_requires_auth(client):
    r = client.get("/api/export/json", headers={"Authorization": "Bearer bogus"})
    assert r.status_code == 401


def test_delete_collection_admin_only_and_audited(client):
    cid = make_collection(client, "На видалення")
    client.post("/api/users", json={"username": "w", "password": "w123", "role": "worker"})
    wt = client.post("/api/login", json={"username": "w", "password": "w123"}).json()["token"]
    r = client.delete(f"/api/collections/{cid}", headers={"Authorization": f"Bearer {wt}"})
    assert r.status_code == 403
    r = client.delete(f"/api/collections/{cid}")
    assert r.status_code == 200
    assert r.json()["deleted_rows"] == 4
    assert all(c["id"] != cid for c in client.get("/api/collections").json())
    # rows are gone
    assert client.get(f"/api/collections/{cid}/rows").json() == []
    # audit survives the delete (events reference the collection id)
    audit = client.get(f"/api/collections/{cid}/audit").json()
    assert any(e["action"] == "collection.deleted" for e in audit)
    assert any(e["action"] == "row.deleted" for e in audit)
    assert client.delete(f"/api/collections/{cid}").status_code == 404


def test_ui_has_export_json_button(client):
    html = client.get("/").text
    assert "exportAllJson()" in html and 'data-i18n="export_json_btn"' in html
    assert "deleteCollection(" in html  # guarded by a typed prompt in the UI
