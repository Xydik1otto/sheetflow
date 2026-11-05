"""Accessibility: aria-labels, contrast, keyboard navigation in key flows."""


def test_index_has_focus_and_keyboard_styles(client):
    css = client.get("/").text
    assert ":focus-visible" in css          # visible keyboard focus
    assert "contenteditable]:focus" in css  # editable cells highlighted
    assert "#b91c1c" in css                 # overdue badge >= 4.5:1 on red bg


def test_interactive_elements_have_aria_labels(client):
    html = client.get("/").text
    for marker in (
        'aria-label="Файл .xlsx або .csv"',
        'aria-label="Рядок-шапка"',
        'aria-label="Аркуш Excel"',
        'aria-label="Назва колекції"',
        'aria-label="Пошук по рядках"',
        'aria-label="Збережені фільтри"',
        'aria-label="Мова / Language"',
        'aria-label="Ім\'я нового поля"',
    ):
        assert marker in html, f"missing {marker}"


def test_status_regions_are_live(client):
    html = client.get("/").text
    assert 'id="mapResult" role="status" aria-live="polite"' in html
    assert 'id="bulkCount" role="status" aria-live="polite"' in html


def test_enter_key_submits_login_and_mapping(client):
    js = client.get("/").text
    assert "if (e.key === 'Enter') login()" in js
    assert "if (e.key === 'Enter') doMap()" in js
    assert "keydown" in js
