"""First-run demo collection (opt-in button)."""


def test_demo_creates_collection_with_fields_and_formula(client):
    r = client.post("/api/demo")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"].startswith("Демо ·") and d["imported"] == 2
    cid = d["collection_id"]
    rows = client.get(f"/api/collections/{cid}/rows").json()
    assert len(rows) == 2
    # showcase custom fields
    fields = {f["name"]: f["type"] for f in client.get(f"/api/collections/{cid}/fields").json()}
    assert fields == {"channel": "select", "paid": "number"}
    # showcase formulas
    assert client.get(f"/api/collections/{cid}/formulas").json()["formulas"] == {"total": "=quantity*amount"}
    first = rows[0]
    assert first["total"] == first["quantity"] * first["amount"]


def test_demo_is_opt_in_and_not_duplicated(client):
    r1 = client.post("/api/demo")
    assert r1.status_code == 200
    r2 = client.post("/api/demo")
    assert r2.status_code == 409 and "already exists" in r2.json()["detail"]
    names = [c["name"] for c in client.get("/api/collections").json()]
    assert len([n for n in names if n.startswith("Демо")]) == 1


def test_demo_audited(client):
    cid = client.post("/api/demo").json()["collection_id"]
    events = client.get(f"/api/collections/{cid}/audit").json()
    assert any(e["action"] == "collection.created" and "demo collection" in (e["new_value"] or "")
               for e in events)


def test_demo_button_in_ui(client):
    html = client.get("/").text
    assert "loadDemo()" in html and 'data-i18n="demo_btn"' in html
