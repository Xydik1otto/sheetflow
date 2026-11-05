"""SheetFlow FastAPI application.

Routes:
  UI      GET /                     — single-page UI (vanilla JS, no build step)
  Auth    POST /api/login           — sets session cookie
          GET  /api/me
  Import  POST /api/import/upload   — parse xlsx, return columns + preview
          POST /api/import/map      — create collection from column mapping
  Data    GET  /api/collections
          GET  /api/collections/{id}/rows      — filters: status, assignee, overdue
          PATCH /api/rows/{id}                — change a field (audited)
          GET  /api/collections/{id}/audit
          GET  /api/collections/{id}/export.csv
"""
import csv
import io
import os
import uuid
from datetime import date, timedelta

from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import calc, db, importer

app = FastAPI(title="SheetFlow", version="0.1.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# In-memory staging area for uploaded files awaiting mapping (MVP scope).
_uploads: dict[str, tuple[str, bytes, importer.SheetParse]] = {}


# ---------------------------------------------------------------- auth


def current_user(conn=Depends(db.db)) -> str:
    return "admin"  # single-admin MVP: every action is attributed to the admin user


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
    import hashlib

    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = ?", (body.username,)
    ).fetchone()
    if row is None or row["password_hash"] != hashlib.sha256(body.password.encode()).hexdigest():
        raise HTTPException(401, "Invalid username or password")
    token = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, row["id"], db.now_iso()),
    )
    conn.commit()
    return {"ok": True, "token": token, "username": body.username}


@app.get("/api/me")
def me(user: str = Depends(current_user)):
    return {"user": user, "statuses": db.DEFAULT_STATUSES}


# ---------------------------------------------------------------- import wizard


@app.post("/api/import/upload")
async def upload(file: UploadFile, header_row: int | None = Form(None),
                 user: str = Depends(current_user)):
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
        # Pre-filled mapping proposal — user sees it and can correct any column.
        "suggested_mapping": importer.suggest_mapping(parsed.columns),
    }


class MapIn(BaseModel):
    upload_id: str
    name: str
    mapping: dict[str, str]
    header_row: int | None = None  # must match the header_row used at upload


@app.post("/api/import/map")
def map_columns(body: MapIn, conn=Depends(db.db), user: str = Depends(current_user)):
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
def list_collections(conn=Depends(db.db)):
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
                or needle in (r["assignee"] or "").casefold()]
    today = date.today().isoformat()
    out = []
    for r in rows:
        d = dict(r)
        d["overdue"] = bool(r["due_date"] and r["due_date"] < today and r["status"] != "done")
        if formulas:
            d.update(calc.evaluate_row(formulas, {f: d.get(f) for f in importer.ENTITY_FIELDS}))
        out.append(d)
    return out


class RowPatch(BaseModel):
    field: str
    value: str | int | float | None


class RowUpdate(BaseModel):
    fields: dict[str, str | int | float | None]


EDITABLE = {"item", "quantity", "status", "assignee", "due_date", "amount"}


def _apply_row_update(conn, row_id: int, fields: dict, user: str) -> dict:
    """Validate and apply field changes to one row; one audit event per changed field."""
    unknown = set(fields) - EDITABLE
    if unknown:
        raise HTTPException(422, f"Fields not editable: {', '.join(sorted(unknown))}")
    row = conn.execute("SELECT * FROM rows WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Row not found")
    changes: list[tuple[str, object, object]] = []
    coerced_values: dict[str, object] = {}
    for field, value in fields.items():
        coerced, err = importer.VALIDATORS[field](value)
        if err:
            raise HTTPException(422, f"Invalid value for {field}: {err}")
        if field == "status" and coerced is None:
            coerced = "new"
        coerced_values[field] = coerced
        if coerced != row[field]:
            changes.append((field, row[field], coerced))
    for field, _old, coerced in changes:
        conn.execute(
            f"UPDATE rows SET {field} = ?, updated_at = ? WHERE id = ?",
            (coerced, db.now_iso(), row_id),
        )
    for field, old, coerced in changes:
        db.audit(
            conn, user, "row.updated", collection_id=row["collection_id"], row_id=row_id,
            field=field, old_value=str(old) if old is not None else None,
            new_value=str(coerced) if coerced is not None else None,
        )
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


@app.get("/api/collections/{cid}/audit")
def audit_log(cid: int, limit: int = 200, conn=Depends(db.db)):
    rows = conn.execute(
        "SELECT * FROM audit_events WHERE collection_id = ? ORDER BY id DESC LIMIT ?",
        (cid, limit),
    ).fetchall()
    return [dict(r) for r in rows]


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
def put_formulas(cid: int, body: FormulasIn, conn=Depends(db.db), user: str = Depends(current_user)):
    """Define derived (calculated) columns, e.g. {"total": "=quantity*amount"}."""
    coll = conn.execute("SELECT id FROM collections WHERE id = ?", (cid,)).fetchone()
    if coll is None:
        raise HTTPException(404, "Collection not found")
    available = calc.available_fields(body.formulas)
    problems = []
    for name, formula in body.formulas.items():
        if not calc._IDENT.match(name) or name in importer.ENTITY_FIELDS:
            problems.append(f"Invalid calculated column name: {name!r}")
        err = calc.validate_formula(formula, available)
        if err:
            problems.append(f"{name}: {err}")
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
def export_csv(cid: int, conn=Depends(db.db)):
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


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
