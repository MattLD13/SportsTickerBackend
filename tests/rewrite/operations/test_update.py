from __future__ import annotations

from ticker_core.platform import OtaUpdaterService


class Commands:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run_update(self, command: tuple[str, ...]) -> None:
        self.commands.append(command)


def test_update_request_launches_once_until_finished() -> None:
    commands = Commands()
    service = OtaUpdaterService(commands, executable="python", updater_path="/opt/ticker/updater.py")

    assert service.request_update("r100") is True
    assert service.request_update("r100") is False
    assert service.state().active is True
    assert commands.commands == [("python", "/opt/ticker/updater.py", "--no-display")]
