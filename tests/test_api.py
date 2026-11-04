"""API tests: import flow, filters, status changes, audit log, CSV round-trip."""
import csv
import io
from datetime import date, timedelta

from app import db as db_mod


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_login_wrong_password(client):
    r = client.post("/api/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401


def test_upload_returns_columns(client, sample_xlsx):
    r = client.post(
        "/api/import/upload",
        files={"file": ("orders.xlsx", sample_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    d = r.json()
    assert r.status_code == 200
    assert d["columns"][0] == "Товар"
    assert d["total_rows"] == 4
    assert set(d["entity_fields"]) == {"item", "quantity", "status", "assignee", "due_date", "amount"}


def test_map_rejects_invalid_mapping(client, sample_xlsx):
    r = client.post("/api/import/upload", files={"file": ("o.xlsx", sample_xlsx, "application/x")})
    uid = r.json()["upload_id"]
    r = client.post("/api/import/map", json={"upload_id": uid, "name": "x", "mapping": {"Товар": "bogus"}})
    assert r.status_code == 422


def test_import_creates_collection_and_rows(client, imported_collection):
    cols = client.get("/api/collections").json()
    assert len(cols) == 1 and cols[0]["row_count"] == 4 and cols[0]["name"] == "Замовлення"
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    assert len(rows) == 4
    by_item = {r["item"]: r for r in rows}
    assert by_item["Кава 1кг"]["quantity"] == 10
    assert by_item["Чай 0.5кг"]["amount"] == 120.5
    assert by_item["Цукор"]["quantity"] is None          # invalid -> None, row still imported


def test_overdue_filter_and_flag(client, imported_collection):
    overdue_rows = client.get(f"/api/collections/{imported_collection}/rows", params={"overdue": "1"}).json()
    # only 'Чай 0.5кг' has a past due_date and status != done
    assert [r["item"] for r in overdue_rows] == ["Чай 0.5кг"]
    all_rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    flagged = {r["item"]: r["overdue"] for r in all_rows}
    assert flagged["Чай 0.5кг"] is True
    assert flagged["Кава 1кг"] is False
    assert flagged["Сіль"] is False                      # done is never overdue


def test_status_change_is_audited(client, imported_collection):
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    row_id = rows[0]["id"]
    r = client.patch(f"/api/rows/{row_id}", json={"field": "status", "value": "done"})
    assert r.status_code == 200 and r.json()["value"] == "done"
    events = client.get(f"/api/collections/{imported_collection}/audit").json()
    change = [e for e in events if e["action"] == "row.updated"]
    assert len(change) == 1
    e = change[0]
    assert e["field"] == "status" and e["old_value"] == "нове" and e["new_value"] == "done"
    assert e["user"] == "admin" and e["row_id"] == row_id


def test_every_row_change_writes_audit_event(client, imported_collection):
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    rid = rows[0]["id"]
    client.patch(f"/api/rows/{rid}", json={"field": "assignee", "value": "Марія"})
    client.patch(f"/api/rows/{rid}", json={"field": "assignee", "value": "Петро"})
    events = [e for e in client.get(f"/api/collections/{imported_collection}/audit").json()
              if e["action"] == "row.updated"]
    events.sort(key=lambda e: e["id"])
    assert [(e["old_value"], e["new_value"]) for e in events] == [("Оля", "Марія"), ("Марія", "Петро")]


def test_collection_creation_is_audited(client, imported_collection):
    events = client.get(f"/api/collections/{imported_collection}/audit").json()
    assert any(e["action"] == "collection.created" and "4 rows imported" in (e["new_value"] or "") for e in events)


def test_patch_rejects_bad_field_and_bad_value(client, imported_collection):
    rid = client.get(f"/api/collections/{imported_collection}/rows").json()[0]["id"]
    assert client.patch(f"/api/rows/{rid}", json={"field": "hacker", "value": "x"}).status_code == 422
    assert client.patch(f"/api/rows/{rid}", json={"field": "quantity", "value": "abc"}).status_code == 422


def test_filters(client, imported_collection):
    rows = client.get(f"/api/collections/{imported_collection}/rows", params={"assignee": "Оля"}).json()
    assert {r["item"] for r in rows} == {"Кава 1кг", "Цукор"}
    rows = client.get(f"/api/collections/{imported_collection}/rows", params={"status": "done"}).json()
    assert [r["item"] for r in rows] == ["Сіль"]
    rows = client.get(f"/api/collections/{imported_collection}/rows", params={"q": "кава"}).json()
    assert [r["item"] for r in rows] == ["Кава 1кг"]  # case-insensitive LIKE


def test_csv_round_trip(client, imported_collection, sample_xlsx):
    """Export -> parse back as CSV -> values match the source workbook."""
    r = client.get(f"/api/collections/{imported_collection}/export.csv")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    data = io.StringIO(r.content.decode("utf-8-sig"))
    reader = csv.DictReader(data)
    out = list(reader)
    assert len(out) == 4
    assert reader.fieldnames == ["item", "quantity", "status", "assignee", "due_date", "amount"]
    by_item = {row["item"]: row for row in out}
    assert by_item["Кава 1кг"]["quantity"] == "10"
    assert by_item["Чай 0.5кг"]["amount"] == "120.5"
    assert by_item["Чай 0.5кг"]["due_date"] == (date.today() - timedelta(days=3)).isoformat()


def test_second_admin_login_does_not_duplicate_user(client, tmp_path):
    # admin already exists -> second ensure_admin is a no-op (first user = admin rule)
    with db_mod.get_conn() as conn:
        db_mod.ensure_admin(conn, "someoneelse", "pw")
    n = db_mod.get_conn().execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert n == 1
