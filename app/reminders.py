"""Automatic due-date reminders via an email outbox.

Outbox pattern: `run_reminders` scans rows whose due_date is overdue or
within `days_before` days (status != done) and queues one reminder per
(row, due_date) — idempotent, so a nightly cron can re-run safely.
`flush` drains the queue: real SMTP when SHEETFLOW_SMTP_HOST is configured,
otherwise entries stay queued (tests monkeypatch the sender).
"""
import os
import smtplib
import urllib.parse
import urllib.request
from datetime import date, timedelta
from email.message import EmailMessage

from . import db


def run_reminders(conn, days_before: int = 3, today: str | None = None) -> int:
    """Queue reminders for overdue / soon-due, not-done rows. Returns created count."""
    today = today or db.now_iso()[:10]
    horizon = (date.fromisoformat(today) + timedelta(days=days_before)).isoformat()
    due_rows = conn.execute(
        "SELECT id, collection_id, item, assignee, due_date FROM rows "
        "WHERE status != 'done' AND due_date IS NOT NULL AND due_date <= ? "
        "ORDER BY due_date",
        (horizon,),
    ).fetchall()
    created = 0
    for r in due_rows:
        already = conn.execute(
            "SELECT 1 FROM reminder_outbox WHERE row_id = ? AND due_date = ?",
            (r["id"], r["due_date"]),
        ).fetchone()
        if already:
            continue
        conn.execute(
            "INSERT INTO reminder_outbox "
            "(created_at, collection_id, row_id, due_date, recipient, subject, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                db.now_iso(), r["collection_id"], r["id"], r["due_date"],
                r["assignee"],
                f"Нагадування: {r['item']} — дедлайн {r['due_date']}",
                f"Завдання «{r['item']}» має дедлайн {r['due_date']}. "
                f"Виконавець: {r['assignee'] or 'не призначено'}.",
            ),
        )
        created += 1
    conn.commit()
    return created


def send_email(recipient: str | None, subject: str, body: str) -> bool:
    """Send one email via SMTP env config. False = SMTP not configured / failed."""
    host = os.environ.get("SHEETFLOW_SMTP_HOST")
    sender = os.environ.get("SHEETFLOW_SMTP_FROM")
    if not host or not sender or not recipient:
        return False
    try:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, recipient, subject
        msg.set_content(body)
        port = int(os.environ.get("SHEETFLOW_SMTP_PORT", "25"))
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.send_message(msg)
        return True
    except Exception:
        return False


def flush(conn, sender=None) -> dict:
    """Drain the outbox. Returns {"sent": n, "failed": m}."""
    sender = sender or send_email
    queued = conn.execute(
        "SELECT id, recipient, subject, body FROM reminder_outbox "
        "WHERE status = 'queued' ORDER BY id"
    ).fetchall()
    sent = failed = 0
    for m in queued:
        if sender(m["recipient"], m["subject"], m["body"]):
            conn.execute(
                "UPDATE reminder_outbox SET status = 'sent', sent_at = ? WHERE id = ?",
                (db.now_iso(), m["id"]),
            )
            sent += 1
        else:
            conn.execute("UPDATE reminder_outbox SET status = 'failed' WHERE id = ?", (m["id"],))
            failed += 1
    conn.commit()
    return {"sent": sent, "failed": failed}


# ---------------------------------------------------------- telegram channel

TELEGRAM_DIGEST_LIMIT = 20  # max lines per digest message


def send_telegram(text: str) -> bool:
    """Send one message to the configured Telegram chat (stdlib urllib).

    Config: SHEETFLOW_TG_TOKEN (bot token) + SHEETFLOW_TG_CHAT_ID.
    False = not configured or send failed — Telegram is optional, the email
    outbox keeps working without it.
    """
    token = os.environ.get("SHEETFLOW_TG_TOKEN")
    chat_id = os.environ.get("SHEETFLOW_TG_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def telegram_digest(conn) -> str | None:
    """Human-readable digest of the queued reminders (None = queue empty)."""
    queued = conn.execute(
        "SELECT recipient, subject FROM reminder_outbox WHERE status = 'queued' ORDER BY id"
    ).fetchall()
    if not queued:
        return None
    lines = [f"• {m['subject']} ({m['recipient'] or 'виконавця не призначено'})"
             for m in queued[:TELEGRAM_DIGEST_LIMIT]]
    more = len(queued) - TELEGRAM_DIGEST_LIMIT
    if more > 0:
        lines.append(f"… і ще {more}")
    return f"SheetFlow: {len(queued)} нагадувань у черзі:\n" + "\n".join(lines)


def flush_telegram(conn, sender=None) -> dict:
    """Send the digest of queued reminders to Telegram. Returns {"sent", "failed", "queued"}.

    Unlike the email outbox this is informational: outbox statuses belong to
    the SMTP channel and are not changed here.
    """
    text = telegram_digest(conn)
    if text is None:
        return {"sent": 0, "failed": 0, "queued": 0}
    ok = (sender or send_telegram)(text)
    return {"sent": 1 if ok else 0, "failed": 0 if ok else 1, "queued": len(conn.execute(
        "SELECT 1 FROM reminder_outbox WHERE status = 'queued'").fetchall())}
