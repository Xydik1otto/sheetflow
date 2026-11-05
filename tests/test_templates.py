"""Tests for one-click collection templates (orders / clients / inventory /
tasks / subscriptions)."""
from app import db as db_mod


def test_list_templates_returns_five_classics(client):
    tpls = client.get("/api/templates").json()
    assert {t["key"] for t in tpls} == {"orders", "clients", "inventory", "tasks", "subscriptions"}
    for t in tpls:
        assert t["name"] and t["columns"] and t["mapping"]


def test_create_from_template_imports_sample_rows(client):
    r = client.post("/api/collections/from-template", json={"template": "orders"})
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Замовлення" and d["imported"] == 2
    rows = client.get(f"/api/collections/{d['collection_id']}/rows").json()
    assert len(rows) == 2
    first = rows[0]
    assert first["item"] == "Замовлення №1001"
    assert first["quantity"] == 2 and first["status"] == "new"
    assert first["due_date"] == "2026-12-01" and first["amount"] == 1500


def test_template_mapping_is_stored_and_reusable_for_reimport(client):
    r = client.post("/api/collections/from-template", json={"template": "inventory"})
    cid = r.json()["collection_id"]
    coll = next(c for c in client.get("/api/collections").json() if c["id"] == cid)
    assert coll["source_file"] == "template:inventory"
    mapping = db_mod.get_conn().execute(
        "SELECT mapping_json FROM collections WHERE id = ?", (cid,)
    ).fetchone()[0]
    assert "Номенклатура" in mapping and "item" in mapping


def test_custom_name_override(client):
    r = client.post("/api/collections/from-template",
                    json={"template": "clients", "name": "Мої клієнти"})
    assert r.json()["name"] == "Мої клієнти"


def test_unknown_template_is_404(client):
    r = client.post("/api/collections/from-template", json={"template": "spaceships"})
    assert r.status_code == 404 and "Available" in r.json()["detail"]


def test_template_creation_is_audited(client):
    r = client.post("/api/collections/from-template", json={"template": "clients"})
    events = client.get(f"/api/collections/{r.json()['collection_id']}/audit").json()
    assert any(e["action"] == "collection.created" and "template 'clients'" in (e["new_value"] or "")
               for e in events)


def test_tasks_template_rows(client):
    r = client.post("/api/collections/from-template", json={"template": "tasks"})
    d = r.json()
    assert d["name"] == "Задачі" and d["imported"] == 2
    rows = client.get(f"/api/collections/{d['collection_id']}/rows").json()
    assert rows[0]["item"] == "Оновити сайт"
    assert rows[0]["quantity"] == 16 and rows[0]["amount"] == 8000
    assert rows[0]["due_date"] == "2026-12-15" and rows[0]["status"] == "new"


def test_subscriptions_template_rows(client):
    r = client.post("/api/collections/from-template", json={"template": "subscriptions"})
    d = r.json()
    assert d["name"] == "Підписки" and d["imported"] == 2
    rows = client.get(f"/api/collections/{d['collection_id']}/rows").json()
    assert rows[0]["item"] == "Microsoft 365"
    assert rows[0]["quantity"] == 12 and rows[0]["amount"] == 2900
    assert rows[1]["due_date"] == "2026-11-20"


def test_every_template_mapping_is_valid_and_complete(client):
    """Each template's mapping must pass the importer's validation as-is."""
    from app import importer, templates
    for key, t in templates.TEMPLATES.items():
        problems = importer.validate_mapping(t["columns"], t["mapping"])
        assert problems == [], f"template {key}: {problems}"
        assert len(t["sample_rows"]) >= 2, f"template {key}: too few sample rows"
