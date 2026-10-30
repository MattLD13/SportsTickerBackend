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

    (tmp_path / "ticker/six").mkdir(parents=True)
    (tmp_path / "ticker/shared").mkdir(parents=True)
    (tmp_path / "ticker" / "six" / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "ticker" / "shared" / "sample.py").write_text("value = 2\n", encoding="utf-8")

    _validate_release(tmp_path)

    assert (tmp_path / "ticker" / "six" / "__pycache__").is_dir()
    assert (tmp_path / "ticker" / "shared" / "__pycache__").is_dir()
