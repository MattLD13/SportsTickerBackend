from __future__ import annotations

from pathlib import Path

from ticker.six.platform import OtaUpdaterService
from ticker.six.updater import _validate_release


class Commands:
    def __init__(self) -> None:
        self.commands: list[tuple[tuple[str, ...], Path]] = []

    def run_update(self, command: tuple[str, ...], *, working_directory: Path) -> None:
        self.commands.append((command, working_directory))


def test_update_request_launches_once_until_finished() -> None:
    commands = Commands()
    service = OtaUpdaterService(commands, executable="python", release=Path("/opt/ticker"))

    assert service.request_update("r100", command_id="attempt", ticker_id="six") is True
    assert service.request_update("r100", command_id="attempt", ticker_id="six") is False
    assert service.state().active is True
    assert commands.commands == [(("python", "-m", "ticker.six.updater", "--version", "r100", "--command-id", "attempt",
                                   "--ticker-id", "six"), Path("/opt/ticker"))]


def test_updater_compiles_runtime_packages_before_activation(tmp_path: Path) -> None:
    """Reject releases without runtime packages and compile valid package sources."""

    packages = ("six/ticker/six", "shared/ticker/shared", "shared/ticker/panel")
    for number, package in enumerate(packages):
        (tmp_path / package).mkdir(parents=True)
        (tmp_path / package / "sample.py").write_text(f"value = {number}\n", encoding="utf-8")

    _validate_release(tmp_path)

    assert all((tmp_path / package / "__pycache__").is_dir() for package in packages)
