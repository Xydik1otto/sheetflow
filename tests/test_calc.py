"""Tests for calculated (derived) columns: formulas like =quantity*amount."""
import pytest

from app import calc


def test_validate_formula_accepts_arithmetic_over_fields():
    available = calc.available_fields({})
    assert calc.validate_formula("=quantity*amount", available) is None
    assert calc.validate_formula("=(quantity + 1) * 2", available) is None
    assert calc.validate_formula("=amount/quantity", available) is None


def test_validate_formula_rejects_unknown_field_and_syntax():
    available = calc.available_fields({})
    assert "unknown field" in calc.validate_formula("=quantity*unknown", available)
    assert "illegal character" in calc.validate_formula("=quantity; DROP TABLE rows", available)
    assert calc.validate_formula("=os.system('x')", available) is not None  # '.' is illegal
    assert "empty" in calc.validate_formula("=", available)


def test_evaluate_formula_basic_arithmetic():
    row = {"quantity": 10, "amount": 450.5}
    assert calc.evaluate_formula("=quantity*amount", row) == 4505.0
    assert calc.evaluate_formula("=quantity+1", row) == 11.0
    assert calc.evaluate_formula("=amount/quantity", row) == 45.05


def test_evaluate_formula_none_and_division_by_zero():
    assert calc.evaluate_formula("=quantity*amount", {"quantity": None, "amount": 5}) is None
    assert calc.evaluate_formula("=amount/quantity", {"quantity": 0, "amount": 5}) is None
    assert calc.evaluate_formula("=quantity*2", {"quantity": "abc"}) is None


def test_evaluate_row_supports_calc_referencing_calc():
    formulas = {"total": "=quantity*amount", "with_vat": "=total*1.2"}
    row = {"quantity": 10, "amount": 100}
    out = calc.evaluate_row(formulas, row)
    assert out == {"total": 1000.0, "with_vat": 1200.0}


def test_evaluate_row_cycle_yields_none():
    out = calc.evaluate_row({"a": "=b+1", "b": "=a+1"}, {"quantity": 1})
    assert out["a"] is None and out["b"] is None


def test_put_formulas_and_rows_return_derived_field(client, imported_collection):
    r = client.put(f"/api/collections/{imported_collection}/formulas",
                   json={"formulas": {"total": "=quantity*amount"}})
    assert r.status_code == 200
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    by_item = {r["item"]: r for r in rows}
    assert by_item["Кава 1кг"]["total"] == pytest.approx(10 * 450.5)
    assert by_item["Чай 0.5кг"]["total"] == pytest.approx(7 * 120.5)
    assert by_item["Цукор"]["total"] is None          # quantity invalid -> None
    # GET echoes the saved formulas
    assert client.get(f"/api/collections/{imported_collection}/formulas").json() == {
        "formulas": {"total": "=quantity*amount"}
    }


def test_put_formulas_rejects_bad_names_and_formulas(client, imported_collection):
    cid = imported_collection
    assert client.put(f"/api/collections/{cid}/formulas",
                      json={"formulas": {"total": "=quantity*nope"}}).status_code == 422
    assert client.put(f"/api/collections/{cid}/formulas",
                      json={"formulas": {"status": "=1"}}).status_code == 422  # entity name reserved


def test_formula_change_is_audited(client, imported_collection):
    client.put(f"/api/collections/{imported_collection}/formulas",
               json={"formulas": {"total": "=quantity*amount"}})
    events = client.get(f"/api/collections/{imported_collection}/audit").json()
    assert any(e["action"] == "collection.formulas_updated" and "total" in (e["new_value"] or "")
               for e in events)


def test_derived_field_follows_inline_edit(client, imported_collection):
    cid = imported_collection
    client.put(f"/api/collections/{cid}/formulas", json={"formulas": {"total": "=quantity*amount"}})
    rid = next(r for r in client.get(f"/api/collections/{cid}/rows").json() if r["item"] == "Кава 1кг")["id"]
    client.put(f"/api/rows/{rid}", json={"fields": {"quantity": 20}})
    row = next(r for r in client.get(f"/api/collections/{cid}/rows").json() if r["id"] == rid)
    assert row["total"] == pytest.approx(20 * 450.5)


def test_collections_schema_has_calc_json():
    from app import db as db_mod
    cols = {r[1] for r in db_mod.get_conn().execute("PRAGMA table_info(collections)")}
    assert "calc_json" in cols
