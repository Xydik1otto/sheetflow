"""XLSX parsing, column mapping and type validation for SheetFlow.

Key idea: do not force users to change their process — import THEIR process.
The user uploads their existing .xlsx, maps its columns onto known entities
(item, quantity, status, assignee, due_date, amount) and SheetFlow creates a
validated collection from it.
"""
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime

from openpyxl import load_workbook

ENTITY_FIELDS = ["item", "quantity", "status", "assignee", "due_date", "amount"]

# entity -> coercer. Returns (value, error_message). Defined after the coercers below.
VALIDATORS = {}


def _is_blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _coerce_text(v):
    if _is_blank(v):
        return None, None  # missing is not an error
    return str(v).strip(), None


def _coerce_status(v):
    if _is_blank(v):
        return None, None
    return str(v).strip().lower(), None


def _coerce_int(v):
    try:
        if v is None or str(v).strip() == "":
            return None, None
        if isinstance(v, float) and v == int(v):
            return int(v), None
        return int(str(v).strip().replace(" ", "").replace(",", "")), None
    except (ValueError, TypeError):
        return None, f"not an integer: {v!r}"


def _coerce_float(v):
    try:
        if v is None or str(v).strip() == "":
            return None, None
        cleaned = str(v).strip().replace(" ", "").replace(",", ".")
        return float(cleaned), None
    except (ValueError, TypeError):
        return None, f"not a number: {v!r}"


def _coerce_date(v):
    if v is None or str(v).strip() == "":
        return None, None
    if isinstance(v, datetime):
        return v.date().isoformat(), None
    if isinstance(v, date):
        return v.isoformat(), None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat(), None
        except ValueError:
            continue
    return None, f"unrecognized date: {v!r}"


VALIDATORS.update({
    "item": _coerce_text,
    "assignee": _coerce_text,
    "status": _coerce_status,
    "quantity": _coerce_int,
    "amount": _coerce_float,
    "due_date": _coerce_date,
})


@dataclass
class SheetParse:
    columns: list[str]
    preview: list[dict]  # first rows as {column: value}
    total_rows: int


@dataclass
class RowError:
    row_number: int  # 1-based data row (excluding header)
    field: str
    message: str
    raw_value: object


@dataclass
class ImportReport:
    collection_id: int
    imported: int = 0
    skipped: int = 0
    errors: list[RowError] = field(default_factory=list)


def parse_sheet(data: bytes) -> SheetParse:
    """Parse the first worksheet of an .xlsx into columns + preview rows."""
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        raise ValueError("The file is empty (no header row found)")
    columns = [str(c).strip() if c is not None else f"column_{i}" for i, c in enumerate(header)]
    columns = [c if c else f"column_{i}" for i, c in enumerate(columns)]
    preview, total = [], 0
    for row in rows_iter:
        total += 1
        if len(preview) < 10:
            preview.append({columns[i]: row[i] if i < len(row) else None for i in range(len(columns))})
    wb.close()
    if not columns:
        raise ValueError("No columns detected in the file")
    return SheetParse(columns=columns, preview=preview, total_rows=total)


def validate_mapping(columns: list[str], mapping: dict[str, str]) -> list[str]:
    """mapping: {column_name -> entity_field}. At least one column must be mapped;
    every mapped entity field must be known and used at most once."""
    problems = []
    if not mapping:
        problems.append("Mapping is empty: map at least one column")
    known = set(ENTITY_FIELDS)
    used = {}
    for col, ent in mapping.items():
        if col not in columns:
            problems.append(f"Unknown column {col!r}")
        if ent not in known:
            problems.append(f"Unknown entity field {ent!r} for column {col!r}")
        if ent in used:
            problems.append(f"Entity field {ent!r} mapped twice ({used[ent]!r} and {col!r})")
        used[ent] = col
    return problems


def build_rows(data: bytes, mapping: dict[str, str]) -> tuple[list[dict], list[RowError]]:
    """Apply the mapping to the whole sheet. Returns (typed_rows, errors).

    Rows are always returned with all 6 entity keys (None where absent/invalid);
    rows whose 'item' (identity) could not be parsed are skipped and reported.
    """
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows_iter)]
    col_index = {name: i for i, name in enumerate(header)}
    out, errors = [], []
    n = 0
    for raw in rows_iter:
        n += 1

        def cell(col):
            i = col_index.get(col)
            return raw[i] if i is not None and i < len(raw) else None

        typed, row_errors, has_any = {}, [], False
        for col, ent in mapping.items():
            value, err = VALIDATORS[ent](cell(col))
            typed[ent] = value
            if err:
                row_errors.append(RowError(n, ent, err, cell(col)))
            if value is not None:
                has_any = True
        if not has_any:
            errors.extend(row_errors or [RowError(n, "row", "row is completely empty", None)])
            continue
        if row_errors:
            errors.extend(row_errors)
        out.append(typed)
    wb.close()
    return out, errors


def mapping_to_json(mapping: dict[str, str]) -> str:
    return json.dumps(mapping, ensure_ascii=False)


def mapping_from_json(s: str) -> dict[str, str]:
    return json.loads(s)
