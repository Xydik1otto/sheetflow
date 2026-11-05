"""Version consistency: v1.0.0 everywhere."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.0.0"


def test_app_version():
    from app.main import app
    assert app.version == VERSION


def test_pyproject_version():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == VERSION


def test_changelog_has_release_entry():
    md = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{VERSION}]" in md
    assert "Користувацькі поля" in md and "multi-sheet" in md.lower()
