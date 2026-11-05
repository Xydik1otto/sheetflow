"""SheetFlow FastAPI application.

Routes:
  UI      GET /                     — single-page UI (vanilla JS, no build step)
  Auth    POST /api/login           — sets session token (roles: admin, worker)
          GET  /api/me
          GET/POST /api/users       — user management (admin only)
  Import  POST /api/import/upload   — parse xlsx (admin)
          POST /api/import/map      — create collection from column mapping (admin)
  Data    GET  /api/collections
          GET  /api/collections/{id}/rows      — filters: status, assignee, overdue
          PATCH/PUT /api/rows/{id}            — edit fields (audited; workers may edit)
          GET  /api/collections/{id}/audit    — admin only
          GET  /api/collections/{id}/export.csv
  Calc    GET/PUT /api/collections/{id}/formulas   — calculated columns (admin writes)
  Fields  GET/POST /api/collections/{id}/fields    — custom fields text/number/date/select
          DELETE /api/collections/{id}/fields/{fid}
  Tmpl    GET  /api/templates
          POST /api/collections/from-template      — admin
  Remind  POST /api/reminders/run, GET /api/reminders/outbox, POST /api/reminders/flush
"""
import csv
import io
import json
import os
import sqlite3
import uuid
from datetime import date, timedelta

from fastapi import Depends, FastAPI, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import calc, db, importer, reminders, templates

app = FastAPI(title="SheetFlow", version="0.4.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# In-memory staging area for uploaded files awaiting mapping (MVP scope).
_uploads: dict[str, tuple[str, bytes, importer.SheetParse]] = {}


# ---------------------------------------------------------------- auth


def current_user_info(conn=Depends(db.db), authorization: str | None = Header(None)) -> dict:
    """Resolve the Bearer token to {username, role}. All API routes require it."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated: login via POST /api/login")
    user = db.get_user_by_token(conn, authorization[len("Bearer "):].strip())
    if user is None:
        raise HTTPException(401, "Invalid session token (login again)")
    return {"username": user["username"], "role": user["role"]}


def current_user(info: dict = Depends(current_user_info)) -> str:
    return info["username"]


def require_admin(info: dict = Depends(current_user_info)) -> str:
    """Admin-only operations: import, audit log, user management, reminders."""
    if info["role"] != "admin":
        raise HTTPException(403, "Admin role required")
    return info["username"]


@app.on_event("startup")
def startup() -> None:
    db.init_db()
    with db.get_conn() as conn:
        db.ensure_admin(conn)


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, conn=Depends(db.db)):
    row = conn.execute(
        "SELECT id, password_hash, role FROM users WHERE username = ?", (body.username,)
    ).fetchone()
    if row is None or not db.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid username or password")
    if db.is_legacy_hash(row["password_hash"]):
        # Transparent upgrade: legacy v0.3.0 sha256 hashes are re-hashed
        # with PBKDF2 on the first successful login.
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (db.hash_password(body.password), row["id"]),
        )
    token = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, row["id"], db.now_iso()),
    )
    conn.commit()
    return {"ok": True, "token": token, "username": body.username, "role": row["role"]}


@app.post("/api/logout")
def logout(conn=Depends(db.db), authorization: str | None = Header(None)):
    """Invalidate the current session token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization[len("Bearer "):].strip()
    if not db.delete_session(conn, token):
        raise HTTPException(401, "Invalid session token (login again)")
    conn.commit()
    return {"ok": True}


@app.get("/api/me")
def me(info: dict = Depends(current_user_info)):
    return {"user": info["username"], "role": info["role"], "statuses": db.DEFAULT_STATUSES}


# ---------------------------------------------------------- user management


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "worker"  # 'admin' | 'worker'


@app.get("/api/users")
def list_users(conn=Depends(db.db), user: str = Depends(require_admin)):
    rows = conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/users")
def add_user(body: UserIn, conn=Depends(db.db), user: str = Depends(require_admin)):
    try:
        new_id = db.create_user(conn, body.username, body.password, body.role)
    except ValueError as exc:
        raise HTTPException(409 if "already exists" in str(exc) else 422, str(exc))
    db.audit(conn, user, "user.created", new_value=f"{body.username} ({body.role})")
    conn.commit()
    return {"ok": True, "id": new_id, "username": body.username, "role": body.role}


# ---------------------------------------------------------------- import wizard


@app.post("/api/import/upload")
async def upload(file: UploadFile, header_row: int | None = Form(None),
                 user: str = Depends(require_admin)):
    """Parse the xlsx. header_row: 1-based manual header selection; omitted = auto-detect."""
    data = await file.read()
    try:
        parsed = importer.parse_sheet(data, header_row=header_row)
    except Exception as exc:  # openpyxl raises a zoo of exception types
        raise HTTPException(400, f"Cannot parse file: {exc}")
    upload_id = uuid.uuid4().hex
    _uploads[upload_id] = (file.filename or "upload.xlsx", data, parsed)
    return {
        "upload_id": upload_id,
        "columns": parsed.columns,
        "preview": parsed.preview,
        "total_rows": parsed.total_rows,
        "entity_fields": importer.ENTITY_FIELDS,
        "header_row": parsed.header_row + 1,  # echo back, 1-based as in the UI
        "source_format": parsed.source_format,
        "encoding": parsed.encoding,
        "delimiter": parsed.delimiter,
        # Pre-filled mapping proposal — user sees it and can correct any column.
        "suggested_mapping": importer.suggest_mapping(parsed.columns),
    }


class MapIn(BaseModel):
    upload_id: str
    name: str
    mapping: dict[str, str]
    header_row: int | None = None  # must match the header_row used at upload


@app.post("/api/import/map")
def map_columns(body: MapIn, conn=Depends(db.db), user: str = Depends(require_admin)):
    staged = _uploads.get(body.upload_id)
    if staged is None:
        raise HTTPException(404, "Unknown upload_id (re-upload the file)")
    filename, data, parsed = staged
    problems = importer.validate_mapping(parsed.columns, body.mapping)
    if problems:
        raise HTTPException(422, "; ".join(problems))

    cur = conn.execute(
        "INSERT INTO collections (name, source_file, mapping_json, calc_json, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (body.name, filename, importer.mapping_to_json(body.mapping), None, user, db.now_iso()),
    )
    collection_id = cur.lastrowid
    typed_rows, errors = importer.build_rows(data, body.mapping, header_row=body.header_row)
    for r in typed_rows:
        conn.execute(
            "INSERT INTO rows (collection_id, item, quantity, status, assignee, due_date, amount, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                collection_id, r["item"], r["quantity"],
                r["status"] or "new", r["assignee"], r["due_date"], r["amount"],
                db.now_iso(), db.now_iso(),
            ),
        )
    db.audit(
        conn, user, "collection.created", collection_id=collection_id,
        new_value=f"{len(typed_rows)} rows imported from {filename}",
    )
    conn.commit()
    del _uploads[body.upload_id]
    return {
        "collection_id": collection_id,
        "imported": len(typed_rows),
        "error_count": len(errors),
        "errors": [e.__dict__ for e in errors[:50]],
    }


# ---------------------------------------------------------------- collections / rows


@app.get("/api/collections")
def list_collections(conn=Depends(db.db), user: str = Depends(current_user)):
    rows = conn.execute(
        "SELECT c.id, c.name, c.source_file, c.created_at, c.created_by, "
        "(SELECT COUNT(*) FROM rows r WHERE r.collection_id = c.id) AS row_count "
        "FROM collections c ORDER BY c.id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/collections/{cid}/rows")
def list_rows(cid: int, status: str | None = None, assignee: str | None = None,
              overdue: bool = False, q: str | None = None, conn=Depends(db.db)):
    coll = conn.execute("SELECT calc_json FROM collections WHERE id = ?", (cid,)).fetchone()
    formulas = calc.calc_from_json(coll["calc_json"]) if coll is not None else {}
    custom_fields = db.list_custom_fields(conn, cid)
    sql = "SELECT * FROM rows WHERE collection_id = ?"
    params: list = [cid]
    if status:
        sql += " AND status = ?"
        params.append(status)
    if assignee:
        sql += " AND assignee = ?"
        params.append(assignee)
    if overdue:
        sql += " AND due_date IS NOT NULL AND due_date < ? AND status != 'done'"
        params.append(date.today().isoformat())
    rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    if q:
        # Python-side search: SQLite LIKE is ASCII-case-insensitive only,
        # so Cyrillic search needs casefold.
        needle = q.casefold()
        rows = [r for r in rows
                if needle in (r["item"] or "").casefold()
                or needle in (r["assignee"] or "").casefold()
                or needle in " ".join(
                    str(v) for v in (json.loads(r["extra_json"]).values() if r["extra_json"] else [])
                ).casefold()]
    today = date.today().isoformat()
    out = []
    for r in rows:
        d = dict(r)
        if r["extra_json"]:
            d.update(json.loads(r["extra_json"]))
        d["overdue"] = bool(r["due_date"] and r["due_date"] < today and r["status"] != "done")
        if formulas:
            values = {f: d.get(f) for f in importer.ENTITY_FIELDS}
            values.update({f["name"]: d.get(f["name"]) for f in custom_fields})
            d.update(calc.evaluate_row(formulas, values))
        out.append(d)
    return out


class RowPatch(BaseModel):
    field: str
    value: str | int | float | None


class RowUpdate(BaseModel):
    fields: dict[str, str | int | float | None]


EDITABLE = {"item", "quantity", "status", "assignee", "due_date", "amount"}


def _apply_row_update(conn, row_id: int, fields: dict, user: str, commit: bool = True) -> dict:
    """Validate and apply field changes to one row; one audit event per changed field.

    Entity fields live in dedicated columns; custom (user-defined) fields are
    stored as a JSON dict in rows.extra_json and validated by field type.
    """
    row = conn.execute("SELECT * FROM rows WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Row not found")
    custom = {f["name"]: f for f in db.list_custom_fields(conn, row["collection_id"])}
    unknown = set(fields) - EDITABLE - set(custom)
    if unknown:
        raise HTTPException(422, f"Fields not editable: {', '.join(sorted(unknown))}")
    changes: list[tuple[str, object, object]] = []
    coerced_values: dict[str, object] = {}
    for field, value in fields.items():
        if field in custom:
            f = custom[field]
            coerced, err = importer.coerce_custom_value(f["type"], value, f["options"])
        else:
            coerced, err = importer.VALIDATORS[field](value)
        if err:
            raise HTTPException(422, f"Invalid value for {field}: {err}")
        if field == "status" and coerced is None:
            coerced = "new"
        coerced_values[field] = coerced
        if field not in custom:
            if coerced != row[field]:
                changes.append((field, row[field], coerced))
        else:
            old_extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
            if coerced != old_extra.get(field):
                changes.append((field, old_extra.get(field), coerced))
    entity_changes = [c for c in changes if c[0] not in custom]
    custom_changes = [c for c in changes if c[0] in custom]
    for field, _old, coerced in entity_changes:
        conn.execute(
            f"UPDATE rows SET {field} = ?, updated_at = ? WHERE id = ?",
            (coerced, db.now_iso(), row_id),
        )
    if custom_changes:
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
        for field, _old, coerced in custom_changes:
            extra[field] = coerced
        conn.execute(
            "UPDATE rows SET extra_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(extra, ensure_ascii=False), db.now_iso(), row_id),
        )
    for field, old, coerced in changes:
        db.audit(
            conn, user, "row.updated", collection_id=row["collection_id"], row_id=row_id,
            field=field, old_value=str(old) if old is not None else None,
            new_value=str(coerced) if coerced is not None else None,
        )
    if commit:
        conn.commit()
    return {
        "ok": True,
        "updated": {f: new for f, _o, new in changes},
        "values": coerced_values,
    }


@app.patch("/api/rows/{row_id}")
def patch_row(row_id: int, body: RowPatch, conn=Depends(db.db), user: str = Depends(current_user)):
    result = _apply_row_update(conn, row_id, {body.field: body.value}, user)
    return {"ok": True, "field": body.field, "value": result["values"].get(body.field)}


@app.put("/api/rows/{row_id}")
def put_row(row_id: int, body: RowUpdate, conn=Depends(db.db), user: str = Depends(current_user)):
    """Inline edit: update any set of editable fields in one request."""
    if not body.fields:
        raise HTTPException(422, "Empty update: provide at least one field")
    return _apply_row_update(conn, row_id, body.fields, user)


# ---------------------------------------------------------------- bulk actions

BULK_LIMIT = 1000


class BulkIn(BaseModel):
    ids: list[int]
    fields: dict[str, str | int | float | None]


class BulkDeleteIn(BaseModel):
    ids: list[int]


@app.post("/api/rows/bulk")
def bulk_update(body: BulkIn, conn=Depends(db.db), user: str = Depends(current_user)):
    """Mass edit of selected rows (e.g. status change). One audit event per
    changed field on every row. Invalid rows are reported per id."""
    if not body.ids:
        raise HTTPException(422, "No rows selected")
    if len(body.ids) > BULK_LIMIT:
        raise HTTPException(422, f"Too many rows (max {BULK_LIMIT} per request)")
    # Unknown-field pre-check: entity fields + custom fields of any collection
    # the selected rows belong to. Per-row type validation happens in
    # _apply_row_update (a field valid in one collection is rejected elsewhere).
    coll_ids = {r["collection_id"] for r in conn.execute(
        f"SELECT DISTINCT collection_id FROM rows WHERE id IN ({','.join('?' * len(body.ids))})",
        body.ids,
    )}
    custom_names: set[str] = set()
    for c in coll_ids:
        custom_names |= {f["name"] for f in db.list_custom_fields(conn, c)}
    unknown = set(body.fields) - EDITABLE - custom_names
    if unknown:
        raise HTTPException(422, f"Fields not editable: {', '.join(sorted(unknown))}")
    updated, failed = [], []
    for row_id in body.ids:
        try:
            result = _apply_row_update(conn, row_id, body.fields, user, commit=False)
            updated.append({"id": row_id, "values": result["values"]})
        except HTTPException as exc:
            failed.append({"id": row_id, "error": exc.detail})
    conn.commit()
    db.audit(
        conn, user, "rows.bulk_updated", collection_id=None,
        new_value=f"{len(updated)} rows: {', '.join(body.fields)}",
    )
    conn.commit()
    return {"ok": True, "updated": updated, "failed": failed}


@app.post("/api/rows/bulk-delete")
def bulk_delete(body: BulkDeleteIn, conn=Depends(db.db), user: str = Depends(require_admin)):
    """Delete selected rows (admin only). One audit event per deleted row."""
    if not body.ids:
        raise HTTPException(422, "No rows selected")
    if len(body.ids) > BULK_LIMIT:
        raise HTTPException(422, f"Too many rows (max {BULK_LIMIT} per request)")
    deleted, failed = [], []
    for row_id in body.ids:
        row = conn.execute(
            "SELECT id, collection_id, item FROM rows WHERE id = ?", (row_id,)
        ).fetchone()
        if row is None:
            failed.append({"id": row_id, "error": "Row not found"})
            continue
        conn.execute("DELETE FROM rows WHERE id = ?", (row_id,))
        db.audit(conn, user, "row.deleted", collection_id=row["collection_id"],
                 row_id=row_id, old_value=row["item"])
        deleted.append(row_id)
    conn.commit()
    db.audit(conn, user, "rows.bulk_deleted", collection_id=None,
             new_value=f"{len(deleted)} rows deleted")
    conn.commit()
    return {"ok": True, "deleted": deleted, "failed": failed}


@app.get("/api/collections/{cid}/audit")
def audit_log(cid: int, limit: int = 200, conn=Depends(db.db), user: str = Depends(require_admin)):
    rows = conn.execute(
        "SELECT * FROM audit_events WHERE collection_id = ? ORDER BY id DESC LIMIT ?",
        (cid, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------- saved (named) filters

FILTER_KEYS = {"status", "assignee", "overdue", "q"}


class SavedFilterIn(BaseModel):
    name: str
    filters: dict[str, str | bool | int | None]


@app.get("/api/collections/{cid}/filters")
def list_filters(cid: int, conn=Depends(db.db), user: str = Depends(current_user)):
    rows = conn.execute(
        "SELECT id, name, filter_json, created_by, created_at FROM saved_filters "
        "WHERE collection_id = ? ORDER BY id",
        (cid,),
    ).fetchall()
    return [{**dict(r), "filters": json.loads(r["filter_json"])} for r in rows]


@app.post("/api/collections/{cid}/filters")
def save_filter(cid: int, body: SavedFilterIn, conn=Depends(db.db), user: str = Depends(current_user)):
    coll = conn.execute("SELECT id FROM collections WHERE id = ?", (cid,)).fetchone()
    if coll is None:
        raise HTTPException(404, "Collection not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Filter name must not be empty")
    clean = {k: v for k, v in body.filters.items() if k in FILTER_KEYS and v not in (None, "", False)}
    if not clean:
        raise HTTPException(422, "Filter is empty: set at least one of status/assignee/overdue/q")
    try:
        cur = conn.execute(
            "INSERT INTO saved_filters (collection_id, name, filter_json, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, name, json.dumps(clean, ensure_ascii=False), user, db.now_iso()),
        )
        fid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Filter {name!r} already exists for this collection")
    db.audit(conn, user, "filter.saved", collection_id=cid, new_value=f"{name}: {json.dumps(clean, ensure_ascii=False)}")
    conn.commit()
    return {"ok": True, "id": fid, "name": name, "filters": clean}


@app.delete("/api/filters/{fid}")
def delete_filter(fid: int, conn=Depends(db.db), info: dict = Depends(current_user_info)):
    row = conn.execute(
        "SELECT f.id, f.name, f.collection_id, f.created_by FROM saved_filters f WHERE f.id = ?", (fid,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Filter not found")
    if row["created_by"] != info["username"] and info["role"] != "admin":
        raise HTTPException(403, "Only the author or an admin can delete this filter")
    conn.execute("DELETE FROM saved_filters WHERE id = ?", (fid,))
    db.audit(conn, info["username"], "filter.deleted", collection_id=row["collection_id"],
             old_value=row["name"])
    conn.commit()
    return {"ok": True}


# ------------------------------------------------------- custom fields


class CustomFieldIn(BaseModel):
    name: str
    label: str
    type: str  # 'text' | 'number' | 'date' | 'select'
    options: list[str] = []  # select only


@app.get("/api/collections/{cid}/fields")
def get_fields(cid: int, conn=Depends(db.db), user: str = Depends(current_user)):
    if conn.execute("SELECT 1 FROM collections WHERE id = ?", (cid,)).fetchone() is None:
        raise HTTPException(404, "Collection not found")
    return db.list_custom_fields(conn, cid)


@app.post("/api/collections/{cid}/fields")
def add_field(cid: int, body: CustomFieldIn, conn=Depends(db.db), user: str = Depends(require_admin)):
    """Add a user-defined column (text/number/date/select) to a collection."""
    if conn.execute("SELECT 1 FROM collections WHERE id = ?", (cid,)).fetchone() is None:
        raise HTTPException(404, "Collection not found")
    name = body.name.strip()
    if not calc._IDENT.match(name):
        raise HTTPException(422, f"Invalid field name: {name!r} (use letters, digits, _)")
    if name in importer.ENTITY_FIELDS:
        raise HTTPException(422, f"Field name {name!r} is reserved")
    coll = conn.execute("SELECT calc_json FROM collections WHERE id = ?", (cid,)).fetchone()
    if name in calc.calc_from_json(coll["calc_json"]):
        raise HTTPException(409, f"Field name {name!r} collides with a calculated column")
    if body.type not in db.CUSTOM_FIELD_TYPES:
        raise HTTPException(422, f"Unknown field type {body.type!r}; "
                                 f"available: {', '.join(db.CUSTOM_FIELD_TYPES)}")
    options = [o.strip() for o in body.options if o.strip()]
    if body.type == "select" and not options:
        raise HTTPException(422, "Select field requires a non-empty options list")
    if body.type != "select" and options:
        raise HTTPException(422, "Only select fields take options")
    if db.get_custom_field(conn, cid, name) is not None:
        raise HTTPException(409, f"Field {name!r} already exists in this collection")
    position = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM custom_fields WHERE collection_id = ?", (cid,)
    ).fetchone()[0]
    fid = db.add_custom_field(conn, cid, name, body.label.strip() or name, body.type, options, position)
    db.audit(conn, user, "field.created", collection_id=cid,
             new_value=f"{name} ({body.type})" + (f" [{', '.join(options)}]" if options else ""))
    conn.commit()
    created = next(f for f in db.list_custom_fields(conn, cid) if f["id"] == fid)
    return {"ok": True, **created}


@app.delete("/api/collections/{cid}/fields/{fid}")
def delete_field(cid: int, fid: int, conn=Depends(db.db), user: str = Depends(require_admin)):
    row = conn.execute(
        "SELECT id, name FROM custom_fields WHERE id = ? AND collection_id = ?", (fid, cid)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Field not found")
    db.delete_custom_field(conn, fid)
    db.drop_custom_field_values(conn, cid, row["name"])
    db.audit(conn, user, "field.deleted", collection_id=cid, old_value=row["name"])
    conn.commit()
    return {"ok": True}


# ------------------------------------------------------- calculated columns


class FormulasIn(BaseModel):
    formulas: dict[str, str]


@app.get("/api/collections/{cid}/formulas")
def get_formulas(cid: int, conn=Depends(db.db)):
    coll = conn.execute("SELECT calc_json FROM collections WHERE id = ?", (cid,)).fetchone()
    if coll is None:
        raise HTTPException(404, "Collection not found")
    return {"formulas": calc.calc_from_json(coll["calc_json"])}


@app.put("/api/collections/{cid}/formulas")
def put_formulas(cid: int, body: FormulasIn, conn=Depends(db.db), user: str = Depends(require_admin)):
    """Define derived (calculated) columns, e.g. {"total": "=quantity*amount"}.

    Formulas may reference entity fields, custom fields of this collection and
    other calculated columns; cycles are rejected with 422.
    """
    coll = conn.execute("SELECT id FROM collections WHERE id = ?", (cid,)).fetchone()
    if coll is None:
        raise HTTPException(404, "Collection not found")
    custom_names = {f["name"] for f in db.list_custom_fields(conn, cid)}
    available = calc.available_fields(body.formulas) | custom_names
    problems = []
    for name, formula in body.formulas.items():
        if not calc._IDENT.match(name) or name in importer.ENTITY_FIELDS:
            problems.append(f"Invalid calculated column name: {name!r}")
        elif name in custom_names:
            problems.append(f"Calculated column {name!r} collides with a custom field")
        err = calc.validate_formula(formula, available)
        if err:
            problems.append(f"{name}: {err}")
    if not problems:
        for cycle in calc.detect_cycles(body.formulas):
            problems.append("cycle detected: " + " -> ".join(cycle))
    if problems:
        raise HTTPException(422, "; ".join(problems))
    conn.execute("UPDATE collections SET calc_json = ? WHERE id = ?",
                 (calc.calc_to_json(body.formulas) if body.formulas else None, cid))
    db.audit(
        conn, user, "collection.formulas_updated", collection_id=cid,
        new_value=", ".join(body.formulas) if body.formulas else "cleared",
    )
    conn.commit()
    return {"ok": True, "formulas": body.formulas}


@app.get("/api/collections/{cid}/export.csv")
def export_csv(cid: int, conn=Depends(db.db), user: str = Depends(current_user)):
    coll = conn.execute("SELECT * FROM collections WHERE id = ?", (cid,)).fetchone()
    if coll is None:
        raise HTTPException(404, "Collection not found")
    rows = conn.execute("SELECT * FROM rows WHERE collection_id = ? ORDER BY id", (cid,)).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["item", "quantity", "status", "assignee", "due_date", "amount"])
    for r in rows:
        writer.writerow([r["item"], r["quantity"], r["status"], r["assignee"], r["due_date"], r["amount"]])
    from urllib.parse import quote
    safe_name = quote(coll["name"])
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),  # BOM so Excel opens Cyrillic correctly
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="collection-{cid}.csv"; '
                f"filename*=UTF-8''{safe_name}.csv"
            )
        },
    )


@app.get("/api/health")
def health():
    return {"ok": True}


# ------------------------------------------------------------- reminders


class RemindersRunIn(BaseModel):
    days_before: int = 3


@app.post("/api/reminders/run")
def run(body: RemindersRunIn, conn=Depends(db.db), user: str = Depends(require_admin)):
    """Queue due-date reminders (overdue + within days_before; done excluded). Idempotent."""
    created = reminders.run_reminders(conn, days_before=body.days_before)
    return {"ok": True, "created": created}


@app.get("/api/reminders/outbox")
def outbox(status: str | None = None, conn=Depends(db.db)):
    sql = "SELECT * FROM reminder_outbox ORDER BY id DESC"
    params: list = []
    if status:
        sql = "SELECT * FROM reminder_outbox WHERE status = ? ORDER BY id DESC"
        params.append(status)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


@app.post("/api/reminders/flush")
def flush_outbox(conn=Depends(db.db), user: str = Depends(require_admin)):
    """Send queued reminders. Without SHEETFLOW_SMTP_* config they are marked failed."""
    result = reminders.flush(conn)
    return {"ok": True, **result}


# ------------------------------------------------------------- templates


class FromTemplateIn(BaseModel):
    template: str
    name: str | None = None  # optional collection name override


@app.get("/api/templates")
def list_templates():
    return [
        {"key": key, "name": t["name"], "columns": t["columns"], "mapping": t["mapping"]}
        for key, t in templates.TEMPLATES.items()
    ]


@app.post("/api/collections/from-template")
def from_template(body: FromTemplateIn, conn=Depends(db.db), user: str = Depends(require_admin)):
    """Create a collection from a classic template (orders/clients/inventory),
    pre-filled with its sample rows — one click, no file needed."""
    t = templates.TEMPLATES.get(body.template)
    if t is None:
        raise HTTPException(404, f"Unknown template {body.template!r}. "
                                 f"Available: {', '.join(templates.TEMPLATES)}")
    name = body.name or t["name"]
    problems = importer.validate_mapping(t["columns"], t["mapping"])
    assert not problems  # templates are static and always valid
    cur = conn.execute(
        "INSERT INTO collections (name, source_file, mapping_json, calc_json, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, f"template:{body.template}", importer.mapping_to_json(t["mapping"]), None,
         user, db.now_iso()),
    )
    collection_id = cur.lastrowid
    imported = 0
    for raw in t["sample_rows"]:
        typed = {f: None for f in importer.ENTITY_FIELDS}
        for col, ent in t["mapping"].items():
            value, _err = importer.VALIDATORS[ent](raw.get(col))
            typed[ent] = value
        conn.execute(
            "INSERT INTO rows (collection_id, item, quantity, status, assignee, due_date, amount, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                collection_id, typed["item"], typed["quantity"],
                typed["status"] or "new", typed["assignee"], typed["due_date"], typed["amount"],
                db.now_iso(), db.now_iso(),
            ),
        )
        imported += 1
    db.audit(
        conn, user, "collection.created", collection_id=collection_id,
        new_value=f"created from template '{body.template}' ({imported} sample rows)",
    )
    conn.commit()
    return {"ok": True, "collection_id": collection_id, "name": name, "imported": imported}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
