from __future__ import annotations

from pathlib import Path

from updater import _validate_release


def test_updater_compiles_runtime_packages_before_activation(tmp_path: Path) -> None:
    """Reject releases without runtime packages and compile valid package sources."""

    (tmp_path / "ticker_core").mkdir()
    (tmp_path / "sports_ticker").mkdir()
    (tmp_path / "ticker_core" / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "sports_ticker" / "sample.py").write_text("value = 2\n", encoding="utf-8")

    _validate_release(tmp_path)

    assert (tmp_path / "ticker_core" / "__pycache__").is_dir()
    assert (tmp_path / "sports_ticker" / "__pycache__").is_dir()
