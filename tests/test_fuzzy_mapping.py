"""Tests for fuzzy auto-mapping: suggested column mapping in the import wizard."""
from app.importer import suggest_mapping


def test_suggests_mapping_for_typical_ukrainian_headers():
    columns = ["Назва товару", "К-сть", "Статус", "Виконавець", "Термін", "Сума"]
    assert suggest_mapping(columns) == {
        "Назва товару": "item",
        "К-сть": "quantity",
        "Статус": "status",
        "Виконавець": "assignee",
        "Термін": "due_date",
        "Сума": "amount",
    }


def test_suggests_mapping_for_typical_english_headers():
    columns = ["Item Name", "Qty", "Status", "Assignee", "Deadline", "Amount"]
    suggested = suggest_mapping(columns)
    assert suggested["Item Name"] == "item"
    assert suggested["Qty"] == "quantity"
    assert suggested["Status"] == "status"
    assert suggested["Assignee"] == "assignee"
    assert suggested["Deadline"] == "due_date"
    assert suggested["Amount"] == "amount"


def test_fuzzy_fuzzy_variants_above_threshold():
    """Fuzzy (not exact, not substring) names still map: 'Продукт'->item,
    'Кол-во'->quantity, 'Цена'->amount."""
    suggested = suggest_mapping(["Продукт", "Кол-во", "Цена"])
    assert suggested.get("Продукт") == "item"
    assert suggested.get("Кол-во") == "quantity"
    assert suggested.get("Цена") == "amount"


def test_unrelated_column_is_not_mapped():
    assert "Примітки" not in suggest_mapping(["Товар", "Примітки"])
    assert "Comments" not in suggest_mapping(["Name", "Comments"])


def test_mapping_is_one_to_one():
    """Two competing columns never claim the same entity; the better match wins."""
    suggested = suggest_mapping(["Назва", "Найменування товару", "К-сть"])
    entities = list(suggested.values())
    assert len(entities) == len(set(entities))
    # 'Назва' is the exact-synonym match and must win 'item'
    assert suggested["Назва"] == "item"
    assert suggested["К-сть"] == "quantity"


def test_threshold_is_respected():
    """Below-threshold fuzzy similarity yields no suggestion."""
    # 'zzz' has no plausible similarity to any synonym
    assert suggest_mapping(["zzz"]) == {}


def test_upload_returns_suggested_mapping(client, sample_xlsx):
    r = client.post(
        "/api/import/upload",
        files={"file": ("orders.xlsx", sample_xlsx, "application/x")},
    )
    d = r.json()
    assert r.status_code == 200
    assert d["suggested_mapping"] == {
        "Товар": "item",
        "К-сть": "quantity",
        "Статус": "status",
        "Хто": "assignee",
        "Термін": "due_date",
        "Ціна": "amount",
    }


def test_user_can_override_suggestion(client, sample_xlsx):
    """Suggestion is only a pre-fill: a corrected mapping is accepted."""
    r = client.post("/api/import/upload", files={"file": ("o.xlsx", sample_xlsx, "application/x")})
    uid = r.json()["upload_id"]
    mapping = dict(r.json()["suggested_mapping"])
    mapping["Хто"] = "item"          # user overrides assignee -> item... would clash,
    del mapping["Товар"]             # so drop the original item column first
    r = client.post("/api/import/map", json={"upload_id": uid, "name": "Виправлено", "mapping": mapping})
    assert r.status_code == 200
    rows = client.get(f"/api/collections/{r.json()['collection_id']}/rows").json()
    assert rows[0]["item"] == "Оля"
