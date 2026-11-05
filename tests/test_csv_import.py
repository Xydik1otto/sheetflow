"""CSV import: delimiter + encoding auto-detection, same wizard as xlsx."""
import io

import pytest

from app import importer
from tests.conftest import SAMPLE_MAPPING


def make_csv(rows: list[list], delimiter: str = ",",
             encoding: str = "utf-8", bom: bool = False) -> bytes:
    buf = io.StringIO()
    import csv as csv_mod
    writer = csv_mod.writer(buf, delimiter=delimiter)
    writer.writerows(rows)
    data = buf.getvalue().encode(encoding)
    if bom and encoding == "utf-8":
        data = b"\xef\xbb\xbf" + data
    return data


def test_is_xlsx_signature(sample_xlsx):
    assert importer.is_xlsx(sample_xlsx)
    assert not importer.is_xlsx(make_csv([["a"]]))


def test_detect_encoding_variants():
    assert importer.detect_encoding(b"\xef\xbb\xbf\xd0\xbf") == "utf-8-sig"  # BOM
    assert importer.detect_encoding("текст".encode("utf-8")) == "utf-8"
    assert importer.detect_encoding("текст".encode("cp1251")) == "cp1251"
    assert importer.detect_encoding("текст".encode("utf-16")) == "utf-16"


def test_detect_delimiter():
    assert importer.detect_delimiter("a,b,c\n1,2,3") == ","
    assert importer.detect_delimiter("a;b;c\n1;2;3") == ";"
    assert importer.detect_delimiter("a\tb\tc\n1\t2\t3") == "\t"
    assert importer.detect_delimiter("a|b|c\n1|2|3") == "|"


def test_csv_rows_decodes_cp1251():
    data = "Товар;К-сть\nКава;10".encode("cp1251")
    rows, enc, delim = importer.csv_rows(data)
    assert enc == "cp1251" and delim == ";"
    assert rows[0] == ["Товар", "К-сть"] and rows[1] == ["Кава", "10"]


def test_parse_csv_with_semicolon_and_cyrillic():
    data = make_csv(
        [["Товар", "К-сть", "Статус", "Хто", "Термін", "Ціна"],
         ["Кава 1кг", "10", "нове", "Оля", "2026-12-01", "450,50"],
         ["Чай", "7", "в роботі", "Іван", "", "120"]],
        delimiter=";",
    )
    parsed = importer.parse_sheet(data)
    assert parsed.source_format == "csv"
    assert parsed.encoding == "utf-8" and parsed.delimiter == ";"
    assert parsed.columns[0] == "Товар" and parsed.total_rows == 2


def test_csv_header_row_autodetect_skips_title_line():
    data = make_csv(
        [["Звіт за листопад"], [],  # title line then blank
         ["Товар", "К-сть"], ["Кава", "10"], ["Чай", "7"]]
    )
    parsed = importer.parse_sheet(data)
    assert parsed.header_row == 2
    assert parsed.columns == ["Товар", "К-сть"]
    assert parsed.total_rows == 2


def test_csv_build_rows_types():
    data = make_csv(
        [["Товар", "К-сть", "Статус", "Хто", "Термін", "Ціна"],
         ["Кава", "10", "нове", "Оля", "01.12.2026", "450,50"],
         ["", "", "", "", "", ""]]  # empty row → same 'completely empty' error as xlsx
    )
    rows, errors = importer.build_rows(data, SAMPLE_MAPPING)
    assert len(rows) == 1
    assert [(e.row_number, e.field) for e in errors] == [(2, "row")]
    r = rows[0]
    assert r["item"] == "Кава" and r["quantity"] == 10
    assert r["due_date"] == "2026-12-01" and r["amount"] == 450.5


def test_full_csv_wizard_flow(client):
    data = make_csv(
        [["Товар", "К-сть", "Статус", "Хто", "Термін", "Ціна"],
         ["Кава 1кг", "10", "нове", "Оля", "2026-12-01", "450,50"],
         ["Чай 0.5кг", "7", "в роботі", "Іван", "", "120"]],
        delimiter=";",
    )
    r = client.post("/api/import/upload", files={"file": ("orders.csv", data, "text/csv")})
    assert r.status_code == 200
    d = r.json()
    assert d["source_format"] == "csv" and d["delimiter"] == ";"
    assert d["suggested_mapping"]["Товар"] == "item"
    r = client.post("/api/import/map", json={
        "upload_id": d["upload_id"], "name": "CSV Замовлення",
        "mapping": SAMPLE_MAPPING,
    })
    assert r.status_code == 200
    assert r.json()["imported"] == 2 and r.json()["error_count"] == 0
    cid = r.json()["collection_id"]
    rows = client.get(f"/api/collections/{cid}/rows").json()
    assert rows[0]["item"] == "Кава 1кг" and rows[0]["quantity"] == 10


def test_csv_utf16_upload(client):
    data = make_csv([["Товар", "К-сть"], ["Кава", "10"]], encoding="utf-16")
    r = client.post("/api/import/upload", files={"file": ("o.csv", data, "text/csv")})
    assert r.status_code == 200
    assert r.json()["encoding"] == "utf-16"
    assert r.json()["columns"] == ["Товар", "К-сть"]
