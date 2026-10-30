from pathlib import Path
import json
import os
from types import SimpleNamespace

from PIL import Image
import pytest

from ticker.six import updater
from ticker.six.platform.frame_health import PresentedFrameHealth, receipt_matches
from ticker.six.runtime import FrameKind

pytestmark = pytest.mark.critical


def test_frame_receipt_requires_successful_nonblank_output_and_current_identity(tmp_path):
    path = tmp_path / "frame.json"
    health = PresentedFrameHealth(path, tmp_path, clock=lambda: 100)
    health.record(Image.new("RGB", (384, 32)), FrameKind.STATIC)
    assert not path.exists()
    health.record(Image.new("RGB", (64, 32), "red"), FrameKind.STATIC)
    assert not path.exists()
    health.record(Image.new("RGB", (384, 32), "red"), FrameKind.STATIC)
    value = json.loads(path.read_text())
    assert receipt_matches(value, tmp_path, os.getpid(), 100)
    for change in ({"pid": -1}, {"width": 64}, {"sha256": "bad"}, {"blank": True}, {"recorded_at": 99}, {"release": "old"}):
        assert not receipt_matches({**value, **change}, tmp_path, os.getpid(), 100)
    assert not receipt_matches(value, tmp_path / "other", os.getpid(), 100)
    assert not receipt_matches(value, tmp_path, os.getpid() + 1, 100)


def test_active_service_without_a_new_frame_fails_release_health(tmp_path, monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr(updater, "FRAME_HEALTH_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(updater.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(updater.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(updater.subprocess, "check_output", lambda *args, **kwargs: "123")
    assert not updater._service_is_healthy(tmp_path, not_before=1, timeout_seconds=3)


def test_failed_frame_validation_restores_previous_release_before_cleanup(tmp_path, monkeypatch):
    previous, candidate = tmp_path / "previous", tmp_path / "candidate"
    selected, installed = [], []
    monkeypatch.setattr(updater, "_activate_release", lambda path: selected.append(path))
    monkeypatch.setattr(updater, "_install_service", lambda path: installed.append(path))
    monkeypatch.setattr(updater, "_service_is_healthy", lambda *args, **kwargs: False)
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    with pytest.raises(RuntimeError, match="display health"):
        updater._install_checked_release(candidate, previous)
    assert selected == installed == [candidate, previous]


def test_cleanup_retains_the_actual_rollback_release(tmp_path, monkeypatch):
    active, previous = tmp_path / "active", tmp_path / "previous"
    for index, name in enumerate(("previous", "newer1", "newer2", "newer3", "active")):
        path = tmp_path / name
        path.mkdir()
        os.utime(path, (index + 1, index + 1))
    removed = []
    monkeypatch.setattr(updater, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(updater, "_git", lambda *args, **kwargs: removed.append(Path(args[-1])))
    updater._cleanup_releases(active, previous)
    assert previous not in removed and active not in removed
    assert set(removed) == {tmp_path / "newer1", tmp_path / "newer2"}
