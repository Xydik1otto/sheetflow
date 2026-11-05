"""Roadmap v1.2: Telegram notifications about overdue reminders.

Optional channel: SHEETFLOW_TG_TOKEN + SHEETFLOW_TG_CHAT_ID; a digest of the
queued reminders is sent via POST /api/reminders/flush-telegram (admin only).
"""
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app import reminders
from app.main import app


@pytest.fixture()
def queued_reminders(client, imported_collection):
    r = client.post("/api/reminders/run", json={"days_before": 3})
    assert r.status_code == 200
    assert r.json()["created"] > 0


def test_send_telegram_without_config_is_false(monkeypatch):
    monkeypatch.delenv("SHEETFLOW_TG_TOKEN", raising=False)
    monkeypatch.delenv("SHEETFLOW_TG_CHAT_ID", raising=False)
    assert reminders.send_telegram("test") is False


def test_flush_telegram_empty_queue(client, monkeypatch):
    monkeypatch.delenv("SHEETFLOW_TG_TOKEN", raising=False)
    r = client.post("/api/reminders/flush-telegram")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "sent": 0, "failed": 0, "queued": 0}


def test_flush_telegram_sends_digest(client, queued_reminders, monkeypatch):
    monkeypatch.setenv("SHEETFLOW_TG_TOKEN", "123:ABC")
    monkeypatch.setenv("SHEETFLOW_TG_CHAT_ID", "42")
    sent = {}

    def fake_urlopen(req, timeout=0):
        sent["url"] = req.full_url
        sent["payload"] = req.data.decode()

        class R:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    r = client.post("/api/reminders/flush-telegram")
    assert r.status_code == 200
    d = r.json()
    assert d["sent"] == 1 and d["failed"] == 0 and d["queued"] > 0
    assert "api.telegram.org/bot123:ABC/sendMessage" in sent["url"]
    assert "chat_id=42" in sent["payload"]
    from urllib.parse import unquote_plus
    text = unquote_plus(sent["payload"].replace("chat_id=42&text=", "", 1))
    assert "SheetFlow" in text and "Нагадування" in text and "Чай 0.5кг" in text


def test_flush_telegram_without_config_reports_failed(client, queued_reminders, monkeypatch):
    monkeypatch.delenv("SHEETFLOW_TG_TOKEN", raising=False)
    monkeypatch.delenv("SHEETFLOW_TG_CHAT_ID", raising=False)
    r = client.post("/api/reminders/flush-telegram")
    assert r.status_code == 200
    d = r.json()
    assert d["sent"] == 0 and d["failed"] == 1 and d["queued"] > 0


def test_telegram_digest_truncates_long_queues(client, queued_reminders, monkeypatch):
    # stuff the queue beyond the digest limit
    from app import db as db_mod
    with db_mod.get_conn() as conn:
        for i in range(30):
            conn.execute(
                "INSERT INTO reminder_outbox (created_at, collection_id, row_id, due_date, "
                "recipient, subject, body) VALUES (?, 1, NULL, NULL, NULL, ?, ?)",
                (db_mod.now_iso(), f"справа {i}", "текст"),
            )
        conn.commit()
    digest = reminders.telegram_digest(db_mod.get_conn())
    assert digest.count("•") == reminders.TELEGRAM_DIGEST_LIMIT
    assert "і ще 11" in digest  # 31 queued = 20 shown + 11 in the tail


def test_worker_cannot_flush_telegram(client, worker_client):
    assert worker_client.post("/api/reminders/flush-telegram").status_code == 403


@pytest.fixture()
def worker_client(client):
    client.post("/api/users", json={"username": "oksana", "password": "w123", "role": "worker"})
    c = TestClient(app)
    r = c.post("/api/login", json={"username": "oksana", "password": "w123"})
    c.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return c
