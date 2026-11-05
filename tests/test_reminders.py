"""Tests for due-date reminders and the email outbox."""
from datetime import date, timedelta

import pytest

from app import reminders
from tests.conftest import SAMPLE_ROWS


def _items(client, cid):
    return {r["item"]: r for r in client.get(f"/api/collections/{cid}/rows").json()}


def test_run_queues_overdue_and_upcoming(client, imported_collection):
    today = date.today()
    overdue = (today - timedelta(days=3)).isoformat()      # Чай 0.5кг
    upcoming = (today + timedelta(days=5)).isoformat()     # Кава 1кг
    r = client.post("/api/reminders/run", json={"days_before": 7})
    assert r.json()["created"] == 2
    outbox = client.get("/api/reminders/outbox").json()
    by_subject = {m["subject"]: m for m in outbox}
    assert any(overdue in s for s in by_subject)
    assert any(upcoming in s for s in by_subject)
    assert all(m["status"] == "queued" for m in outbox)


def test_run_excludes_done_rows(client, imported_collection):
    rid = next(r for r in client.get(f"/api/collections/{imported_collection}/rows").json()
               if r["item"] == "Сіль")["id"]
    client.patch(f"/api/rows/{rid}", json={"field": "status", "value": "done"})
    r = client.post("/api/reminders/run", json={"days_before": 30})
    subjects = [m["subject"] for m in client.get("/api/reminders/outbox").json()]
    assert not any("Сіль" in s for s in subjects)


def test_run_is_idempotent(client, imported_collection):
    first = client.post("/api/reminders/run", json={"days_before": 7}).json()["created"]
    second = client.post("/api/reminders/run", json={"days_before": 7}).json()["created"]
    assert first > 0 and second == 0


def test_run_horizon_is_respected(client, imported_collection):
    """Кава 1кг is due in +5 days: inside a 3-day horizon it must NOT be queued."""
    r = client.post("/api/reminders/run", json={"days_before": 3})
    assert r.json()["created"] == 1  # only the overdue Чай 0.5кг
    subjects = [m["subject"] for m in client.get("/api/reminders/outbox").json()]
    assert not any("Кава" in s for s in subjects)


def test_outbox_status_filter(client, imported_collection):
    client.post("/api/reminders/run", json={"days_before": 7})
    assert client.get("/api/reminders/outbox", params={"status": "queued"}).json()
    assert client.get("/api/reminders/outbox", params={"status": "sent"}).json() == []


def test_flush_with_injected_sender_marks_sent(client, imported_collection):
    client.post("/api/reminders/run", json={"days_before": 7})
    sent_log = []

    def fake_sender(recipient, subject, body):
        sent_log.append((recipient, subject))
        return True

    # no SMTP configured -> the endpoint flush marks entries failed (nothing was really sent)
    r = client.post("/api/reminders/flush")
    assert r.json() == {"ok": True, "sent": 0, "failed": 2}
    assert all(m["status"] == "failed" for m in client.get("/api/reminders/outbox").json())

    # unit path: re-queue and flush with an injected sender -> sent + timestamped
    from app import db as db_mod
    with db_mod.get_conn() as conn:
        conn.execute("UPDATE reminder_outbox SET status = 'queued'")
        conn.commit()
        result = reminders.flush(conn, sender=fake_sender)
    assert result == {"sent": 2, "failed": 0}
    assert len(sent_log) == 2
    rows = db_mod.get_conn().execute("SELECT status, sent_at FROM reminder_outbox").fetchall()
    assert all(m["status"] == "sent" and m["sent_at"] for m in rows)


def test_send_email_without_smtp_config_is_false(monkeypatch):
    for var in ("SHEETFLOW_SMTP_HOST", "SHEETFLOW_SMTP_FROM"):
        monkeypatch.delenv(var, raising=False)
    assert reminders.send_email("x@example.com", "s", "b") is False


def test_reminder_body_contains_item_and_assignee(client, imported_collection):
    client.post("/api/reminders/run", json={"days_before": 7})
    m = client.get("/api/reminders/outbox").json()[0]
    assert m["recipient"] in {"Оля", "Іван"}
    assert m["body"] and m["collection_id"] == imported_collection and m["row_id"]
