"""Unit tests for xlsx parsing, column mapping and type validation."""
from datetime import date

import pytest

from app import importer
from tests.conftest import make_xlsx


def test_parse_sheet_returns_columns_and_preview(sample_xlsx):
    parsed = importer.parse_sheet(sample_xlsx)
    assert parsed.columns == ["Товар", "К-сть", "Статус", "Хто", "Термін", "Ціна"]
    assert parsed.total_rows == 4
    assert parsed.preview[0]["Товар"] == "Кава 1кг"


def test_parse_sheet_empty_file_raises():
    import io
    from openpyxl import Workbook

    wb = Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError):
        importer.parse_sheet(buf.getvalue())


def test_validate_mapping_ok_and_errors():
    cols = ["a", "b", "c"]
    assert importer.validate_mapping(cols, {"a": "item", "b": "quantity"}) == []
    problems = importer.validate_mapping(cols, {"a": "item", "b": "item", "c": "bogus"})
    assert any("twice" in p for p in problems)
    assert any("Unknown entity field" in p for p in problems)
    assert importer.validate_mapping(cols, {})  # empty mapping is an error
    assert importer.validate_mapping(cols, {"nope": "item"})  # unknown column


def test_build_rows_applies_mapping_and_types(sample_xlsx):
    rows, errors = importer.build_rows(sample_xlsx, {
        "Товар": "item", "К-сть": "quantity", "Статус": "status",
        "Хто": "assignee", "Термін": "due_date", "Ціна": "amount",
    })
    assert len(rows) == 4
    r0, r1, r2, r3 = rows
    assert r0["quantity"] == 10 and isinstance(r0["quantity"], int)
    assert r1["quantity"] == 7                      # numeric string coerced
    assert r1["amount"] == 120.50                   # comma decimal coerced
    assert r2["quantity"] is None                   # 'abc' -> None + error
    assert r3["assignee"] is None                   # empty -> None
    # all rows always carry all 6 entity keys
    for r in rows:
        assert set(r.keys()) == set(importer.ENTITY_FIELDS)


def test_build_rows_collects_errors_per_row(sample_xlsx):
    mapping = {"Товар": "item", "К-сть": "quantity", "Ціна": "amount", "Термін": "due_date"}
    _, errors = importer.build_rows(sample_xlsx, mapping)
    bad = {(e.row_number, e.field) for e in errors}
    assert (3, "quantity") in bad        # 'abc'
    assert (3, "amount") in bad          # 'не число'
    assert (2, "due_date") not in bad    # '31.12.2026' parses via dd.mm.yyyy


def test_date_formats():
    assert importer.VALIDATORS["due_date"]("31.12.2026") == ("2026-12-31", None)
    assert importer.VALIDATORS["due_date"]("2026-12-31") == ("2026-12-31", None)
    assert importer.VALIDATORS["due_date"]("not a date")[1] is not None
    assert importer.VALIDATORS["due_date"](date(2026, 1, 2)) == ("2026-01-02", None)


def test_empty_row_is_skipped():
    xlsx = make_xlsx(
        [{"Name": "a"}, {"Name": ""}],
        headers=["Name"],
    )
    rows, errors = importer.build_rows(xlsx, {"Name": "item"})
    assert len(rows) == 1
    assert len(errors) == 1
