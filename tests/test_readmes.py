"""Bilingual README: README.md (UA) + README.en.md (EN), cross-linked."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_both_readmes_exist_and_crosslink():
    ua = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert "README.en.md" in ua and "README.md" in en
    assert "v1.0.0" in ua and "v1.0.0" in en
    assert "INSTALL.md" in ua and "INSTALL.md" in en


def test_readmes_advertise_v1_features():
    ua = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    for marker in ("Користувацькі поля", "селектор аркуша", "5 шаблонів", "i18n"):
        assert marker in ua, f"README.md misses {marker!r}"
    for marker in ("Custom fields", "sheet selector", "Five one-click", "i18n"):
        assert marker in en, f"README.en.md misses {marker!r}"


def test_no_russian_in_readmes():
    import re
    russian = re.compile(r"[ЫыЪъЭэЁё]")
    for name in ("README.md", "README.en.md"):
        assert not russian.search((ROOT / name).read_text(encoding="utf-8")), name
