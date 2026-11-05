"""Multi-sheet xlsx import: sheet list + sheet selector in the upload/map flow."""
import io

from openpyxl import Workbook, load_workbook

from app import importer
from tests.conftest import SAMPLE_MAPPING


def make_multisheet_xlsx() -> bytes:
    """Two worksheets with different data: 'Замовлення' and 'Склад'."""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Замовлення"
    ws1.append(["Товар", "К-сть", "Статус", "Хто", "Термін", "Ціна"])
    ws1.append(["Стіл", 2, "new", "Оля", "2026-12-01", 900])
    ws2 = wb.create_sheet("Склад")
    ws2.append(["Товар", "К-сть", "Статус", "Хто", "Термін", "Ціна"])
    ws2.append(["Шафа", 5, "done", "Іван", "2026-11-30", 2400])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_multisheet(client, sheet=None):
    data = make_multisheet_xlsx()
    files = {"file": ("book.xlsx", data,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    form = {"sheet": sheet} if sheet else None
    r = client.post("/api/import/upload", files=files, data=form)
    assert r.status_code == 200, r.text
    return r.json()


def test_list_sheets_unit():
    names = importer.list_sheets(make_multisheet_xlsx())
    assert names == ["Замовлення", "Склад"]
    assert importer.list_sheets(b"a,b\n1,2\n") == ["csv"]


def test_upload_reports_sheet_list(client):
    d = upload_multisheet(client)
    assert d["sheets"] == ["Замовлення", "Склад"]
    assert d["sheet"] is None  # active sheet by default
    # default parse reads the active (first) sheet
    assert "Товар" in d["columns"]
    assert d["preview"][0]["Товар"] == "Стіл"


def test_upload_with_sheet_selector_parses_that_sheet(client):
    d = upload_multisheet(client, sheet="Склад")
    assert d["sheet"] == "Склад"
    assert d["preview"][0]["Товар"] == "Шафа"
    assert d["preview"][0]["К-сть"] == 5


def test_map_imports_selected_sheet_only(client):
    d = upload_multisheet(client, sheet="Склад")
    r = client.post("/api/import/map", json={
        "upload_id": d["upload_id"], "name": "Склад",
        "mapping": SAMPLE_MAPPING, "sheet": "Склад",
    })
    assert r.status_code == 200, r.text
    cid = r.json()["collection_id"]
    rows = client.get(f"/api/collections/{cid}/rows").json()
    assert [x["item"] for x in rows] == ["Шафа"]
    assert rows[0]["quantity"] == 5


def test_map_with_unknown_sheet_rejected(client):
    d = upload_multisheet(client, sheet="Склад")
    r = client.post("/api/import/map", json={
        "upload_id": d["upload_id"], "name": "X",
        "mapping": SAMPLE_MAPPING, "sheet": "Неіснуючий",
    })
    assert r.status_code == 422 and "Неіснуючий" in r.json()["detail"]


def test_csv_upload_has_single_pseudo_sheet(client):
    r = client.post("/api/import/upload",
                    files={"file": ("t.csv", "Товар,К-сть\nСтіл,2\n".encode("utf-8-sig"), "text/csv")})
    assert r.status_code == 200
    d = r.json()
    assert d["sheets"] == ["csv"]


def test_parse_sheet_unit_selects_sheet():
    data = make_multisheet_xlsx()
    p1 = importer.parse_sheet(data)
    p2 = importer.parse_sheet(data, sheet="Склад")
    assert p1.preview[0]["Товар"] == "Стіл"
    assert p2.preview[0]["Товар"] == "Шафа"
    assert p2.sheet == "Склад"
    wb = load_workbook(io.BytesIO(data), read_only=True)
    assert wb.sheetnames == ["Замовлення", "Склад"]


def test_ui_has_sheet_selector(client):
    html = client.get("/").text
    assert 'id="sheetSel"' in html and "sheetBox" in html
