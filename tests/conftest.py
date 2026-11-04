"""Shared fixtures: a temp DB, an on-the-fly xlsx workbook, an API client."""
import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import db as db_mod
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh SQLite DB per test + admin user + logged-in TestClient."""
    test_db = str(tmp_path / "test.db")
    monkeypatch.setenv("SHEETFLOW_DB", test_db)
    db_mod.init_db(test_db)
    with db_mod.get_conn() as conn:
        db_mod.ensure_admin(conn, "admin", "admin123")
    c = TestClient(app)
    r = c.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    c.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return c


def make_xlsx(rows: list[dict], headers: list[str] | None = None) -> bytes:
    """Build an in-memory .xlsx fixture with openpyxl."""
    wb = Workbook()
    ws = wb.active
    ws.append(headers or list(rows[0].keys()))
    for r in rows:
        ws.append([r.get(h) for h in (headers or list(rows[0].keys()))])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


SAMPLE_ROWS = [
    {"Товар": "Кава 1кг", "К-сть": 10, "Статус": "нове", "Хто": "Оля", "Термін": date.today() + timedelta(days=5), "Ціна": 450.5},
    {"Товар": "Чай 0.5кг", "К-сть": "7", "Статус": "в роботі", "Хто": "Іван", "Термін": date.today() - timedelta(days=3), "Ціна": "120,50"},
    {"Товар": "Цукор", "К-сть": "abc", "Статус": "нове", "Хто": "Оля", "Термін": "31.12.2026", "Ціна": "не число"},
    {"Товар": "Сіль", "К-сть": 3, "Статус": "done", "Хто": None, "Термін": None, "Ціна": None},
]

SAMPLE_MAPPING = {
    "Товар": "item",
    "К-сть": "quantity",
    "Статус": "status",
    "Хто": "assignee",
    "Термін": "due_date",
    "Ціна": "amount",
}


@pytest.fixture()
def sample_xlsx() -> bytes:
    return make_xlsx(SAMPLE_ROWS)


@pytest.fixture()
def imported_collection(client, sample_xlsx) -> int:
    """Upload + map the sample file, return the collection id."""
    r = client.post("/api/import/upload", files={"file": ("orders.xlsx", sample_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    upload_id = r.json()["upload_id"]
    r = client.post("/api/import/map", json={"upload_id": upload_id, "name": "Замовлення", "mapping": SAMPLE_MAPPING})
    assert r.status_code == 200
    return r.json()["collection_id"]
