"""Verify durable result retry and independent startup recovery."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from ticker.six.platform.update_journal import UpdateJournal
from ticker.six import updater

pytestmark = pytest.mark.critical


def test_update_result_survives_network_failure_and_reports_each_transition_once(tmp_path):
    journal = UpdateJournal(tmp_path)
    receipt = {"id": "attempt", "version": "new", "status": "started", "running_version": "old", "reason": ""}
    journal.save(receipt)
    def offline(*args):
        raise OSError("offline")
    with pytest.raises(OSError):
        journal.flush(SimpleNamespace(report_update=offline), "six")
    assert UpdateJournal(tmp_path).load() == receipt
    sent = []
    client = SimpleNamespace(report_update=lambda identity, body: (sent.append((identity, body)) or {"accepted": True}))
    journal.flush(client, "six")
    journal.flush(client, "six")
    assert len(sent) == 1
    journal.save({**receipt, "status": "rolled_back", "reason": "render_validation"})
    UpdateJournal(tmp_path).flush(client, "six")
    assert len(sent) == 2 and sent[-1][1]["status"] == "rolled_back"


def test_boot_guard_recovers_an_interrupted_unhealthy_activation(tmp_path, monkeypatch):
    root = tmp_path / "releases"
    previous, target = root / "previous", root / "target"
    previous.mkdir(parents=True)
    target.mkdir()
    journal = UpdateJournal(tmp_path)
    journal.save({"id": "attempt", "version": "new", "status": "started", "running_version": "old", "reason": "",
                  "phase": "activating", "previous_release": str(previous), "target_release": str(target)})
    selected, installed, sent = [], [], []
    monkeypatch.setattr(updater, "RELEASES_DIR", root)
    monkeypatch.setattr(updater, "_current_release", lambda: target)
    monkeypatch.setattr(updater, "_service_is_healthy", lambda *a, **kw: False)
    monkeypatch.setattr(updater, "_activate_release", selected.append)
    monkeypatch.setattr(updater, "_install_service", installed.append)
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **kw: "100 200" if path.as_posix() == "/proc/uptime" else original(path, *a, **kw))
    client = SimpleNamespace(report_update=lambda identity, body: (sent.append(body) or {"accepted": True}))
    assert updater._recover_pending_boot(journal, client, "six") == 0
    assert selected == installed == [previous]
    assert journal.load()["status"] == sent[-1]["status"] == "rolled_back"
    assert sent[-1]["reason"] == "boot_reset"
