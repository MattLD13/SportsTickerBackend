from __future__ import annotations

import subprocess

from backend_ops.components import changed_components


def _git(root, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_changed_components_skips_binary_file_reads(tmp_path) -> None:
    (tmp_path / "docs/research").mkdir(parents=True)
    (tmp_path / "sports_ticker/providers").mkdir(parents=True)
    image = tmp_path / "docs/research/diagram.png"
    weather = tmp_path / "sports_ticker/providers/weather.py"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    weather.write_text("condition = 'cloud'\n", encoding="utf-8")

    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")

    image.write_bytes(b"\x89PNG\r\n\x1a\nupdated")
    weather.write_text("condition = 'sun'\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "change weather and image")

    assert changed_components(tmp_path, base) == ["weather"]
