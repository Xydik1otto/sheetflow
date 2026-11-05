"""i18n: UA/EN switcher, dictionaries, no Russian anywhere."""
import re

RUSSIAN_LETTERS = re.compile(r"[ЫыЪъЭэЁё]")


def test_i18n_js_served(client):
    r = client.get("/static/i18n.js")
    assert r.status_code == 200
    assert "text/javascript" in r.headers["content-type"] or "application/javascript" in r.headers["content-type"]


def test_dictionaries_have_ua_and_en(client):
    js = client.get("/static/i18n.js").text
    assert "ua: {" in js and "en: {" in js
    for key in ("login_h", "step1_h", "collections_h", "custom_fields_h", "export_btn"):
        assert js.count(key + ":") >= 2  # present in both dictionaries


def test_no_russian_in_i18n_and_ui(client):
    """Ukrainian only — Russian-specific letters (ы, ъ, э, ё) must not appear."""
    for path in ("/static/i18n.js", "/"):
        text = client.get(path).text
        assert not RUSSIAN_LETTERS.search(text), f"Russian letters found in {path}"


def test_ui_has_language_switcher(client):
    html = client.get("/").text
    assert 'id="langSel"' in html
    assert '<option value="ua">UA</option><option value="en">EN</option>' in html
    assert 'src="/static/i18n.js"' in html
    assert "applyI18n()" in html
    assert 'data-i18n="login_btn"' in html and 'data-i18n-ph="ph_search"' in html


def test_detect_and_persist_logic_in_i18n_js(client):
    js = client.get("/static/i18n.js").text
    assert "navigator.language" in js  # auto-detect browser language
    assert "localStorage.getItem" in js  # saved choice wins over detection
    assert "startsWith(\"uk\")" in js
    html = client.get("/").text
    assert "localStorage.setItem('lang'" in html  # persists the choice (setLang)
