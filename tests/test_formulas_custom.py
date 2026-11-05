"""Formulas over entity + custom fields; cycle validation on write."""
from tests.conftest import SAMPLE_MAPPING, SAMPLE_ROWS, make_xlsx

from app import calc


def make_collection(client, name="Замовлення"):
    r = client.post("/api/import/upload", files={"file": ("f.xlsx", make_xlsx(SAMPLE_ROWS))})
    upload_id = r.json()["upload_id"]
    r = client.post("/api/import/map", json={"upload_id": upload_id, "name": name, "mapping": SAMPLE_MAPPING})
    return r.json()["collection_id"]


def test_formula_over_custom_number_field(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/fields", json={"name": "price", "label": "Ціна", "type": "number"})
    rows = client.get(f"/api/collections/{cid}/rows").json()
    rid = rows[0]["id"]
    client.put(f"/api/rows/{rid}", json={"fields": {"quantity": 2, "price": 100.5}})
    r = client.put(f"/api/collections/{cid}/formulas", json={"formulas": {"total": "=quantity*price"}})
    assert r.status_code == 200, r.text
    row = next(x for x in client.get(f"/api/collections/{cid}/rows").json() if x["id"] == rid)
    assert row["total"] == 201.0


def test_formula_chain_entity_plus_custom(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/fields", json={"name": "discount", "label": "Знижка", "type": "number"})
    rows = client.get(f"/api/collections/{cid}/rows").json()
    rid = rows[0]["id"]
    client.put(f"/api/rows/{rid}", json={"fields": {"quantity": 3, "amount": 100, "discount": 10}})
    r = client.put(f"/api/collections/{cid}/formulas",
                   json={"formulas": {"gross": "=quantity*amount", "net": "=gross-discount"}})
    assert r.status_code == 200
    row = next(x for x in client.get(f"/api/collections/{cid}/rows").json() if x["id"] == rid)
    assert row["gross"] == 300 and row["net"] == 290


def test_direct_cycle_rejected(client):
    cid = make_collection(client)
    r = client.put(f"/api/collections/{cid}/formulas",
                   json={"formulas": {"a": "=b+1", "b": "=a*2"}})
    assert r.status_code == 422
    assert "cycle" in r.json()["detail"]
    # nothing was saved
    assert client.get(f"/api/collections/{cid}/formulas").json()["formulas"] == {}


def test_self_reference_rejected(client):
    cid = make_collection(client)
    r = client.put(f"/api/collections/{cid}/formulas", json={"formulas": {"a": "=a+1"}})
    assert r.status_code == 422 and "cycle" in r.json()["detail"]


def test_long_cycle_rejected_valid_chain_accepted(client):
    cid = make_collection(client)
    # a -> b -> c -> a is a cycle
    r = client.put(f"/api/collections/{cid}/formulas",
                   json={"formulas": {"a": "=b+1", "b": "=c+1", "c": "=a+1"}})
    assert r.status_code == 422 and "cycle" in r.json()["detail"]
    # a -> b -> c is a valid chain
    r = client.put(f"/api/collections/{cid}/formulas",
                   json={"formulas": {"c": "=quantity*2", "b": "=c+1", "a": "=b+1"}})
    assert r.status_code == 200
    rows = client.get(f"/api/collections/{cid}/rows").json()
    first = rows[0]
    q = first["quantity"] or 0
    assert first["a"] == q * 2 + 2


def test_calc_name_colliding_with_custom_field_rejected(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/fields", json={"name": "margin", "label": "m", "type": "number"})
    r = client.put(f"/api/collections/{cid}/formulas", json={"formulas": {"margin": "=amount*0.2"}})
    assert r.status_code == 422 and "collides" in r.json()["detail"]
    # and a custom field cannot shadow an existing calculated column
    client.put(f"/api/collections/{cid}/formulas", json={"formulas": {"total": "=amount"}})
    r = client.post(f"/api/collections/{cid}/fields", json={"name": "total", "label": "t", "type": "text"})
    assert r.status_code == 409 and "collides" in r.json()["detail"]


def test_unknown_reference_still_rejected(client):
    cid = make_collection(client)
    r = client.put(f"/api/collections/{cid}/formulas", json={"formulas": {"x": "=no_such_field+1"}})
    assert r.status_code == 422 and "unknown field" in r.json()["detail"]


def test_non_numeric_custom_field_yields_none(client):
    cid = make_collection(client)
    client.post(f"/api/collections/{cid}/fields", json={"name": "tag", "label": "t", "type": "text"})
    client.put(f"/api/collections/{cid}/formulas", json={"formulas": {"x": "=tag*2"}})
    rows = client.get(f"/api/collections/{cid}/rows").json()
    assert all(r["x"] is None for r in rows)


def test_detect_cycles_unit():
    assert calc.detect_cycles({"a": "=quantity*2"}) == []
    assert calc.detect_cycles({"a": "=b", "b": "=a"}) == [["a", "b", "a"]]
    assert calc.detect_cycles({"a": "=a"}) == [["a", "a"]]
    assert calc.detect_cycles({"a": "=b", "b": "=quantity", "c": "=a"}) == []
