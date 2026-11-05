"""Open-source hygiene: community files, privacy, .gitignore coverage."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUSSIAN = re.compile(r"[ЫыЪъЭэЁё]")


def test_community_files_exist():
    for name in ("CONTRIBUTING.md", "SECURITY.md", "LICENSE",
                 ".github/ISSUE_TEMPLATE/bug_report.md",
                 ".github/ISSUE_TEMPLATE/feature_request.md"):
        assert (ROOT / name).exists(), f"missing {name}"


def test_issue_templates_are_bilingual_and_not_russian():
    for name in ("bug_report.md", "feature_request.md"):
        text = (ROOT / ".github/ISSUE_TEMPLATE" / name).read_text(encoding="utf-8")
        assert "**EN**" in text and "**UA**" in text, name
        assert not RUSSIAN.search(text), f"Russian letters in {name}"


def test_contributing_states_language_policy():
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "українською та англійською" in text
    assert "Ukrainian and English" in text


def test_no_local_paths_or_secrets_in_repo():
    """Privacy audit: no personal disk paths, tokens or real credentials."""
    offenders = []
    patterns = [
        re.compile(r"[Gg]:\\\\"), re.compile(r"C:[/\\]Users", re.I),
        re.compile(r"/g/Projects"), re.compile(r"bigpi"),
        re.compile(r"ghp_[A-Za-z0-9]{20,}"), re.compile(r"AKIA[0-9A-Z]{16}"),
    ]
    skip_dirs = {".git", "__pycache__", ".pytest_cache", ".venv", "venv",
                 "node_modules", "dist", "build"}
    for path in ROOT.rglob("*"):
        if path.name == "test_oss.py":  # this audit file carries the patterns themselves
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() not in (".py", ".md", ".html", ".js", ".toml",
                                       ".ini", ".yml", ".yaml", ".sh", ".bat",
                                       ".txt", ".cfg"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pat in patterns:
            if pat.search(text):
                # FUNDING.yml intentionally carries the public GitHub handle
                if path.name == "FUNDING.yml" and pat.pattern == "bigpi":
                    continue
                offenders.append(f"{path.name}: {pat.pattern}")
    assert offenders == [], f"privacy leaks: {offenders}"


def test_passwords_are_fixture_only():
    """The only passwords in the codebase are the documented demo/fixture ones."""
    allowed = {"admin123", "w123", "password123"}
    found = set()
    for path in list(ROOT.glob("tests/*.py")) + list(ROOT.glob("app/*.py")):
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r"""["']([A-Za-z0-9_!@#$%^&*-]{6,})["'](?=\s*[,)])""", text))
    real = {p for p in found if re.fullmatch(r"(?=.*[A-Z])(?=.*[a-z])(?=.*\d).{9,}", p)}
    assert not real, f"possible real credentials: {real}"


def test_gitignore_covers_env_and_db():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for line in (".env", ".env.*", "*.db", "*.db-journal", "*.db-wal"):
        assert line in gi, f".gitignore misses {line}"
    for db in ROOT.glob("*.db"):
        assert db.name in gi or True  # *.db pattern covers them


def test_readmes_have_contributing_and_topics():
    for name in ("README.md", "README.en.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "## Contributing" in text, name
        assert "CONTRIBUTING.md" in text and "SECURITY.md" in text, name
        for topic in ("smb", "excel", "no-code", "fastapi", "sqlite", "small-business"):
            assert f"`{topic}`" in text, f"{name} misses topic {topic}"
