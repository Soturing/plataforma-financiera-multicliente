import re
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.version import __version__, read_version

ROOT = Path(__file__).resolve().parents[1]


def test_version_file_is_semver_and_matches_the_module():
    text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert re.fullmatch(r"\d+\.\d+\.\d+", text)
    assert __version__ == read_version() == text


def test_changelog_top_release_matches_the_version_file():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)

    assert first and first.group(1) == __version__


def test_health_and_openapi_expose_the_version():
    client = TestClient(app)

    assert client.get("/health").json()["version"] == __version__
    assert client.get("/openapi.json").json()["info"]["version"] == __version__


def test_bump_script_computes_the_next_version_without_writing(tmp_path):
    def run(part: str) -> str:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bump_version.py"), part, "--dry-run"],
            capture_output=True, text=True, cwd=ROOT,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    major, minor, patch = (int(item) for item in __version__.split("."))
    assert run("patch") == f"{__version__} -> {major}.{minor}.{patch + 1}"
    assert run("minor") == f"{__version__} -> {major}.{minor + 1}.0"
    assert run("major") == f"{__version__} -> {major + 1}.0.0"
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == __version__
