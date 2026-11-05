"""Roadmap v1.1: re-import into an existing collection, upsert by key.

No data loss: existing rows are matched by the key entity field and updated
in place; blank cells never overwrite stored values; new keys are appended.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_xlsx


def _upload(client, data):
    r = client.post(
        "/api/import/upload",
        files={"file": ("orders.xlsx", data,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200
    return r.json()["upload_id"]


def _reimport(client, cid, data, **body):
    return client.post(
        f"/api/collections/{cid}/reimport",
        json={"upload_id": _upload(client, data), **body},
    )


@pytest.fixture()
def delta_xlsx():
    """Second export of the same process: one row changed, one brand new."""
    rows = [
        {"Товар": "Кава 1кг", "К-сть": 99, "Статус": "в роботі", "Хто": "Оля",
         "Термін": date.today() + timedelta(days=2), "Ціна": 480},
        {"Товар": "Мед 0.5кг", "К-сть": 5, "Статус": "нове", "Хто": "Іван",
         "Термін": None, "Ціна": 300},
    ]
    return make_xlsx(rows)


def test_reimport_updates_existing_and_inserts_new(client, imported_collection, delta_xlsx):
    r = _reimport(client, imported_collection, delta_xlsx)
    assert r.status_code == 200
    d = r.json()
    assert d["inserted"] == 1 and d["updated"] == 1 and d["skipped"] == 0
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    assert len(rows) == 5  # 4 original + 1 new, no duplicates
    by_item = {row["item"]: row for row in rows}
    assert by_item["Кава 1кг"]["quantity"] == 99
    assert by_item["Кава 1кг"]["amount"] == 480
    assert by_item["Мед 0.5кг"]["quantity"] == 5
    assert by_item["Мед 0.5кг"]["status"] == "нове"  # status is stored verbatim


def test_reimport_blank_cells_do_not_overwrite(client, imported_collection):
    """Partial re-export: only item + quantity filled — the rest is kept."""
    partial = make_xlsx([
        {"Товар": "Кава 1кг", "К-сть": 7, "Статус": None, "Хто": None,
         "Термін": None, "Ціна": None},
    ])
    r = _reimport(client, imported_collection, partial)
    assert r.status_code == 200 and r.json()["updated"] == 1
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    kava = next(row for row in rows if row["item"] == "Кава 1кг")
    assert kava["quantity"] == 7
    assert kava["amount"] == 450.5          # kept — blank cell is not data
    assert kava["status"] == "нове"          # status untouched
    assert kava["assignee"] == "Оля"


def test_reimport_is_audited(client, imported_collection, delta_xlsx):
    _reimport(client, imported_collection, delta_xlsx)
    events = client.get(f"/api/collections/{imported_collection}/audit").json()
    assert any(e["action"] == "collection.reimported" and "upsert by item" in e["new_value"]
               for e in events)
    updates = [e for e in events if e["action"] == "row.updated" and e["field"] == "quantity"]
    assert any(e["old_value"] == "10" and e["new_value"] == "99" for e in updates)


def test_reimport_key_must_be_mapped(client, imported_collection, delta_xlsx):
    r = _reimport(client, imported_collection, delta_xlsx, key="bogus")
    assert r.status_code == 422
    assert "not mapped" in r.json()["detail"]


def test_reimport_unknown_columns_rejected(client, imported_collection):
    bad = make_xlsx([{"Назвка": "x", "К-сть": 1, "Статус": "нове", "Хто": "a",
                      "Термін": None, "Ціна": None}])
    r = _reimport(client, imported_collection, bad)
    assert r.status_code == 422  # file does not match the collection's mapping


def test_reimport_404s(client, delta_xlsx):
    assert client.post("/api/collections/999/reimport",
                       json={"upload_id": "x"}).status_code == 404
    uid = _upload(client, delta_xlsx)
    assert client.post("/api/collections/999/reimport",
                       json={"upload_id": uid}).status_code == 404
    assert client.post("/api/collections/1/reimport",
                       json={"upload_id": "missing"}).status_code == 404


def test_worker_cannot_reimport(client, imported_collection, delta_xlsx):
    client.post("/api/users", json={"username": "petro", "password": "pw1", "role": "worker"})
    c = TestClient(app)
    r = c.post("/api/login", json={"username": "petro", "password": "pw1"})
    c.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    uid = _upload(client, delta_xlsx)
    assert c.post(f"/api/collections/{imported_collection}/reimport",
                  json={"upload_id": uid}).status_code == 403
