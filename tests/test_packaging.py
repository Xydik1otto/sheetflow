"""Packaging: pyproject metadata, console script, INSTALL for non-programmers."""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_is_valid_and_complete():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    proj = data["project"]
    assert proj["name"] == "sheetflow"
    assert proj["version"] == "1.0.0"
    assert proj["requires-python"] == ">=3.10"
    deps = " ".join(proj["dependencies"]).lower()
    for pkg in ("fastapi", "uvicorn", "openpyxl"):
        assert pkg in deps
    assert proj["scripts"]["sheetflow"] == "app.cli:main"
    assert "pytest" in " ".join(proj["optional-dependencies"]["dev"])
    assert proj["license"]["text"] == "MIT"


def test_console_script_module_exists_and_boots_config():
    from app import cli

    assert callable(cli.main)
    assert hasattr(cli, "__package__")


def test_requirements_and_readme_agree_with_pyproject():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for pkg in ("fastapi", "uvicorn", "openpyxl"):
        assert pkg in reqs
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert sys.version_info >= (3, 10)


def test_install_md_is_step_by_step():
    md = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    for section in ("Windows", "Linux", "systemd", "start.bat", "Оновлення",
                    "shell:startup", "admin"):
        assert section in md, f"INSTALL.md misses {section!r}"
    assert (ROOT / "start.bat").exists()
    bat = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "uvicorn app.main:app" in bat
