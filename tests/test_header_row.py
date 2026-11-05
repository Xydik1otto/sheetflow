"""Tests for header row detection and manual header row selection."""
from io import BytesIO

from openpyxl import Workbook

from app.importer import build_rows, detect_header_row, parse_sheet
from tests.conftest import make_xlsx, SAMPLE_MAPPING, SAMPLE_ROWS


def xlsx_with_title_row(title: str = "Звіт за березень 2026") -> bytes:
    """Sheet with a title band, a blank row, then the real header + data."""
    wb = Workbook()
    ws = wb.active
    ws.append([title, None, None, None, None, None])
    ws.append([None] * 6)  # blank band
    ws.append(list(SAMPLE_MAPPING.keys()))
    for r in SAMPLE_ROWS:
        ws.append([r.get(h) for h in SAMPLE_MAPPING.keys()])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_detects_header_below_title_and_blank_rows():
    data = xlsx_with_title_row()
    assert detect_header_row(data) == 2  # 0-based: title=0, blank=1, header=2


def test_first_row_is_header_when_mostly_text():
    data = make_xlsx(SAMPLE_ROWS)
    assert detect_header_row(data) == 0


def test_blank_sheet_falls_back_to_row_zero():
    wb = Workbook()
    wb.active.append([None, None, None])
    buf = BytesIO()
    wb.save(buf)
    assert detect_header_row(buf.getvalue()) == 0


def test_parse_sheet_auto_skips_title_rows():
    data = xlsx_with_title_row()
    parsed = parse_sheet(data)
    assert parsed.header_row == 2
    assert parsed.columns == list(SAMPLE_MAPPING.keys())
    assert parsed.total_rows == len(SAMPLE_ROWS)
    assert parsed.preview[0]["Товар"] == "Кава 1кг"


def test_parse_sheet_manual_header_row():
    data = xlsx_with_title_row()
    parsed = parse_sheet(data, header_row=1)  # 1-based -> 0-based row 0 (title row)
    assert parsed.header_row == 0
    assert parsed.columns[0] == "Звіт за березень 2026"
    assert parsed.total_rows == 6  # blank + real header + 4 data rows


def test_build_rows_with_detected_header():
    data = xlsx_with_title_row()
    rows, _ = build_rows(data, SAMPLE_MAPPING)
    assert len(rows) == len(SAMPLE_ROWS)
    assert rows[0]["item"] == "Кава 1кг"


def test_build_rows_manual_header_must_match_parse():
    data = xlsx_with_title_row()
    rows, _ = build_rows(data, SAMPLE_MAPPING, header_row=3)  # 1-based -> 0-based 2
    assert rows[0]["item"] == "Кава 1кг"


def test_upload_echoes_detected_header_row(client):
    data = xlsx_with_title_row()
    r = client.post("/api/import/upload", files={"file": ("t.xlsx", data, "application/x")})
    d = r.json()
    assert d["header_row"] == 3  # 1-based echo of the detected row


def test_upload_with_manual_header_row(client):
    data = xlsx_with_title_row()
    r = client.post(
        "/api/import/upload",
        files={"file": ("t.xlsx", data, "application/x")},
        data={"header_row": "3"},
    )
    d = r.json()
    assert d["columns"] == list(SAMPLE_MAPPING.keys())
    assert d["suggested_mapping"] == SAMPLE_MAPPING
    # full import with the manual header row produces the same 4 rows
    r = client.post("/api/import/map", json={
        "upload_id": d["upload_id"], "name": "Ручна шапка",
        "mapping": SAMPLE_MAPPING, "header_row": 3,
    })
    assert r.status_code == 200
    assert r.json()["imported"] == 4
