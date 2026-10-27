from __future__ import annotations

from pathlib import Path
import json

import pytest

from ticker_core.platform import OtaUpdaterService
from updater import _validate_release


class Commands:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run_update(self, command: tuple[str, ...]) -> None:
        self.commands.append(command)


def test_update_request_launches_once_until_finished() -> None:
    commands = Commands()
    service = OtaUpdaterService(commands, executable="python", updater_path="/opt/ticker/updater.py")

    assert service.request_update("r100", command_id="attempt", ticker_id="six") is True
    assert service.request_update("r100", command_id="attempt", ticker_id="six") is False
    assert service.state().active is True
    assert commands.commands == [("python", "/opt/ticker/updater.py", "--version", "r100", "--command-id", "attempt", "--ticker-id", "six")]


def test_updater_compiles_runtime_packages_before_activation(tmp_path: Path) -> None:
    """Reject releases without runtime packages and compile valid package sources."""

    (tmp_path / "ticker_core").mkdir()
    (tmp_path / "sports_ticker").mkdir()
    (tmp_path / "ticker_core" / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "sports_ticker" / "sample.py").write_text("value = 2\n", encoding="utf-8")

    (tmp_path / "release-layout.json").write_text(json.dumps({"schema_version": 1, "runtime_packages": ["ticker_core", "sports_ticker"]}))
    _validate_release(tmp_path)

    assert (tmp_path / "ticker_core" / "__pycache__").is_dir()
    assert (tmp_path / "sports_ticker" / "__pycache__").is_dir()


@pytest.mark.parametrize("packages", [["ticker-six/ticker_core", "ticker-server/sports_ticker"], ["ticker_core", "sports_ticker"]])
def test_updater_validates_declared_product_layouts(tmp_path, packages):
    for name in packages:
        path = tmp_path / name
        path.mkdir(parents=True)
        (path / "example.py").write_text("value = 1\n")
    (tmp_path / "release-layout.json").write_text(json.dumps({"schema_version": 1, "runtime_packages": packages}))
    _validate_release(tmp_path)
    assert all((tmp_path / name / "__pycache__").is_dir() for name in packages)


def test_updater_rejects_layout_outside_its_release(tmp_path):
    (tmp_path / "release-layout.json").write_text(json.dumps({"schema_version": 1, "runtime_packages": ["../"]}))
    with pytest.raises(ValueError, match="escapes"):
        _validate_release(tmp_path)
