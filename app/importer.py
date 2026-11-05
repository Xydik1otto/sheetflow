"""XLSX parsing, column mapping and type validation for SheetFlow.

Key idea: do not force users to change their process — import THEIR process.
The user uploads their existing .xlsx, maps its columns onto known entities
(item, quantity, status, assignee, due_date, amount) and SheetFlow creates a
validated collection from it.
"""
import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime

from openpyxl import load_workbook

import difflib

ENTITY_FIELDS = ["item", "quantity", "status", "assignee", "due_date", "amount"]


# ------------------------------------------------------------- csv support

def is_xlsx(data: bytes) -> bool:
    """XLSX files are ZIP archives and start with the PK\\x03\\x04 signature."""
    return data[:2] == b"PK"


def detect_encoding(data: bytes) -> str:
    """Best-effort encoding detection for text uploads.

    BOM wins first; then valid UTF-8; otherwise fall back to cp1251
    (the de-facto Windows single-byte codepage for Ukrainian/Cyrillic CSVs).
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1251"


def detect_delimiter(text: str) -> str:
    """Pick the column separator for a CSV/DSV text file.

    csv.Sniffer on the first lines first; on failure a frequency+consistency
    heuristic over , ; tab |. Falls back to comma.
    """
    lines = [ln for ln in text.splitlines()[:20] if ln.strip()]
    sample = "\n".join(lines)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass
    best, best_score = ",", 0
    for d in (",", ";", "\t", "|"):
        counts = [ln.count(d) for ln in lines]
        if max(counts, default=0) == 0:
            continue
        # consistent separators (same count on every line) rank highest
        score = counts[0] if len(set(counts)) == 1 else min(counts)
        if score > best_score:
            best, best_score = d, score
    return best


def csv_rows(data: bytes) -> tuple[list[list], str, str]:
    """Decode + parse CSV bytes. Returns (rows, encoding, delimiter)."""
    encoding = detect_encoding(data)
    text = data.decode(encoding)
    delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    # Empty lines are kept as [] so row indices match the xlsx path exactly
    # (detect_header_row and build_rows handle/skip them the same way).
    return list(reader), encoding, delimiter


# Best-effort suggestions for the import wizard: entity -> known column-name
# synonyms (EN + UA). Matching is hybrid: exact = 1.0, substring = 0.85,
# difflib.SequenceMatcher fuzzy ratio otherwise, threshold 0.6.
FIELD_SYNONYMS = {
    "item": ["item", "name", "товар", "назва", "найменування", "продукт", "product",
             "послуга", "номенклатура", "заказ", "замовлення"],
    "quantity": ["quantity", "qty", "к-сть", "кількість", "количество", "штук", "шт"],
    "status": ["status", "статус", "стан", "state"],
    "assignee": ["assignee", "виконавець", "виконавец", "executor", "хто", "who",
                 "owner", "власник", "відповідальний", "assign"],
    "due_date": ["due_date", "due", "deadline", "термін", "дедлайн", "term",
                 "дата", "date", "due date", "срок"],
    "amount": ["amount", "sum", "сума", "сумма", "ціна", "price", "cost",
               "вартість", "total", "всього"],
}

SUGGEST_THRESHOLD = 0.6


def suggest_mapping(columns: list[str], threshold: float = SUGGEST_THRESHOLD) -> dict[str, str]:
    """Suggest {column_name -> entity_field} for the mapping wizard.

    Hybrid scoring per (column, synonym): exact match = 1.0, substring
    containment = 0.85, otherwise difflib.SequenceMatcher().ratio(). A column
    is suggested for an entity only at/above `threshold`; assignments are
    greedy one-to-one, highest score first, so a column never takes an entity
    already claimed by a better match.
    """
    def score(norm_col: str, syn: str) -> float:
        if norm_col == syn:
            return 1.0
        if syn and (syn in norm_col or norm_col in syn):
            return 0.85
        return difflib.SequenceMatcher(None, norm_col, syn).ratio()

    candidates: list[tuple[float, str, str]] = []
    for col in columns:
        norm = str(col).strip().lower()
        for entity, syns in FIELD_SYNONYMS.items():
            best = max(score(norm, s) for s in syns)
            if best >= threshold:
                candidates.append((best, col, entity))
    candidates.sort(key=lambda t: t[0], reverse=True)
    mapping: dict[str, str] = {}
    used_cols: set[str] = set()
    used_entities: set[str] = set()
    for _, col, entity in candidates:
        if col in used_cols or entity in used_entities:
            continue
        mapping[col] = entity
        used_cols.add(col)
        used_entities.add(entity)
    return mapping


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
    header_row: int  # 0-based index of the row used as the header
    source_format: str = "xlsx"  # 'xlsx' | 'csv'
    encoding: str | None = None  # csv only
    delimiter: str | None = None  # csv only


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


def iter_rows(data: bytes):
    """Yield the rows of the first worksheet (xlsx) or of the CSV text file
    as value tuples. One entry point for both formats, so header detection,
    mapping and row building work identically."""
    if is_xlsx(data):
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        yield from ws.iter_rows(values_only=True)
        wb.close()
    else:
        rows, _encoding, _delim = csv_rows(data)
        yield from rows


def detect_header_row(data: bytes) -> int:
    """0-based index of the first non-empty row whose non-empty cells are
    mostly text (>50%, at least 2 cells) — real sheets often start with a
    merged title cell or a blank band; a lone text cell is a title, not a header."""
    for i, row in enumerate(iter_rows(data)):
        cells = [c for c in row if not _is_blank(c)]
        if len(cells) < 2:
            continue
        text_cells = sum(1 for c in cells if isinstance(c, str))
        if text_cells / len(cells) > 0.5:
            return i
    return 0


def resolve_header_row(data: bytes, header_row: int | None = None) -> int:
    """header_row given by the user is 1-based as shown in the UI; None = auto-detect."""
    if header_row is not None:
        return header_row - 1  # UI is 1-based
    return detect_header_row(data)


def parse_sheet(data: bytes, header_row: int | None = None) -> SheetParse:
    """Parse the first worksheet of an .xlsx into columns + preview rows.

    header_row: 1-based row to use as the header (manual selection); None
    auto-detects the first mostly-text non-empty row.
    """
    hr = resolve_header_row(data, header_row)
    all_rows = list(iter_rows(data))
    if not all_rows:
        raise ValueError("The file is empty (no header row found)")
    source_format = "xlsx" if is_xlsx(data) else "csv"
    encoding = delimiter = None
    if source_format == "csv":
        encoding = detect_encoding(data)
        delimiter = detect_delimiter(data.decode(encoding))
    header = all_rows[hr] if hr < len(all_rows) else all_rows[0]
    columns = [str(c).strip() if c is not None else f"column_{i}" for i, c in enumerate(header)]
    columns = [c if c else f"column_{i}" for i, c in enumerate(columns)]
    preview, total = [], 0
    for row in all_rows[hr + 1:]:
        total += 1
        if len(preview) < 10:
            preview.append({columns[i]: row[i] if i < len(row) else None for i in range(len(columns))})
    if not columns:
        raise ValueError("No columns detected in the file")
    return SheetParse(columns=columns, preview=preview, total_rows=total, header_row=hr,
                      source_format=source_format, encoding=encoding, delimiter=delimiter)


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


def build_rows(data: bytes, mapping: dict[str, str],
               header_row: int | None = None) -> tuple[list[dict], list[RowError]]:
    """Apply the mapping to the whole sheet. Returns (typed_rows, errors).

    header_row: 1-based row to use as the header (manual selection); None
    auto-detects, mirroring parse_sheet. Rows are always returned with all 6
    entity keys (None where absent/invalid); rows whose 'item' (identity)
    could not be parsed are skipped and reported.
    """
    all_rows = list(iter_rows(data))
    hr = resolve_header_row(data, header_row)
    header_row_values = all_rows[hr] if hr < len(all_rows) else all_rows[0]
    header = [str(c).strip() if c is not None else "" for c in header_row_values]
    col_index = {name: i for i, name in enumerate(header)}
    out, errors = [], []
    n = 0
    for raw in all_rows[hr + 1:]:
        n += 1

        def cell(col):
            i = col_index.get(col)
            return raw[i] if i is not None and i < len(raw) else None

        typed = {f: None for f in ENTITY_FIELDS}
        row_errors, has_any = [], False
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
    return out, errors


def mapping_to_json(mapping: dict[str, str]) -> str:
    return json.dumps(mapping, ensure_ascii=False)


def mapping_from_json(s: str) -> dict[str, str]:
    return json.loads(s)
