"""Exercise canonical results across the independent fetcher boundary."""
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from backend_ops.worker import ProviderWorker
from backend_ops.manager import Host
from backend_ops.worker_contract import contract_id, decode_result, encode, request
from sports_ticker.domain import ContentItem, DisplaySettings
from sports_ticker.providers.contracts import ProviderResult
from sports_ticker.providers.factory import create_provider

pytestmark = pytest.mark.critical


def message(settings=None):
    return {"protocol": 1, "contract": contract_id(), "op": "fetch", "ticker_id": "test",
            "settings": encode(settings or DisplaySettings(mode="clock"))}


def test_contract_identity_includes_shared_immutable_helper(tmp_path):
    paths = ("backend_ops/worker_contract.py", "sports_ticker/domain/models.py",
             "sports_ticker/providers/contracts.py", "sports_ticker/immutable.py")
    for name in paths:
        for root in (tmp_path / "previous", tmp_path / "current"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(name), target)
    previous = contract_id(tmp_path / "previous")
    assert contract_id(tmp_path / "current") == previous
    helper = tmp_path / "current/sports_ticker/immutable.py"
    helper.write_text(helper.read_text(encoding="utf-8") + "\n# updated behavior\n", encoding="utf-8")
    contract_id.cache_clear()
    assert contract_id(tmp_path / "current") != previous
    assert contract_id(tmp_path / "previous") == previous


def test_contract_identity_uses_the_actual_legacy_release_dependencies(tmp_path):
    paths = ("backend_ops/worker_contract.py", "sports_ticker/domain/models.py",
             "sports_ticker/providers/contracts.py")
    expected = hashlib.sha256()
    for name in paths:
        data = (Path("tests/fixtures/backend_legacy") / name).read_bytes()
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        expected.update(name.encode())
        expected.update(data.replace(b"\r\n", b"\n"))
    assert not (tmp_path / "sports_ticker/immutable.py").exists()
    assert contract_id(tmp_path) == expected.hexdigest()


def test_worker_retains_canonical_fields_and_private_exception_replay(tmp_path):
    settings = DisplaySettings(mode="clock")
    worker = ProviderWorker("clock", create_provider("clock"), replay_directory=tmp_path)
    result = decode_result(json.loads(json.dumps(worker.handle(message(settings))))["result"])
    assert result.health.healthy and result.content[0].family == "clock"
    original = ProviderResult(content=(ContentItem(id="sample", family="sports", kind="nhl",
                                                  data={"penalties": [{"number": 88, "seconds": 45}]}),),
                              alerts=({"kind": "score", "nested": [1, 2]},))
    assert decode_result(json.loads(json.dumps(encode(original)))) == original
    class Broken:
        def fetch(self, settings):
            raise KeyError("missing source field")
    worker = ProviderWorker("clock", Broken(), replay_directory=tmp_path)
    for _ in range(3):
        response = worker.handle(message())
    assert not response["result"]["health"]["healthy"]
    health = worker.handle({**message(), "op": "health"})
    assert health["failures"] == 3 and health["error_type"] == "KeyError"
    assert json.loads((tmp_path / "clock-last-failure.json").read_text()) == message()
    assert "error" in worker.handle({**message(), "contract": "wrong"})
    worker.lock.acquire()
    try:
        assert "error" in worker.handle(message())
    finally:
        worker.lock.release()


def test_source_wait_does_not_take_the_fetch_lock_and_validates_its_bounds():
    class Source:
        def wait_for_changes(self, after, timeout):
            assert after == {"nfl": "old"} and timeout == 1
            return {"nfl": "new"}

    worker = ProviderWorker("espn", Source())
    worker.lock.acquire()
    try:
        request_message = {**message(), "op": "changes", "after": {"nfl": "old"}, "timeout": 1}
        assert worker.handle(request_message)["versions"] == {"nfl": "new"}
        for timeout in (True, -1, 6, float('nan')):
            assert "error" in worker.handle({**request_message, "timeout": timeout})
        assert "error" in worker.handle({**request_message, "after": {"nfl": 1}})
    finally:
        worker.lock.release()


def test_recovery_probe_keeps_previous_release_contract(monkeypatch, tmp_path):
    sent = []

    def exchange(path, body, *, timeout):
        sent.append((path, json.loads(body), timeout))
        return b'{"protocol":1,"contract":"previous","ready":true}\n'

    monkeypatch.setattr("backend_ops.manager.exchange", exchange)
    path = tmp_path / "worker.sock"
    response = Host(tmp_path).rpc(path, {"contract": "previous", "op": "health"})
    assert response["ready"]
    assert sent == [(path, {"contract": "previous", "op": "health"}, 3)]


@pytest.mark.skipif(sys.platform == "win32", reason="Production worker transport requires Linux UnixStreamServer")
def test_real_worker_process_returns_clock_and_health(tmp_path):
    path = Path("/tmp") / ("ticker-test-" + tmp_path.name[-24:] + ".sock")
    process = subprocess.Popen([sys.executable, "-m", "backend_ops.worker", "--component", "clock",
                                "--socket", str(path), "--env-file", str(tmp_path / "absent.env")],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 15
        while not path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert process.poll() is None, process.stderr.read().decode()
        result = decode_result(request(path, message())["result"])
        assert result.health.healthy and result.content[0].family == "clock"
        assert request(path, {**message(), "op": "health"})["ready"]
    finally:
        process.terminate()
        process.wait(timeout=5)
        path.unlink(missing_ok=True)
