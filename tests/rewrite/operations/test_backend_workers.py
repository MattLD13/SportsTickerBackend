"""Exercise canonical results across the independent fetcher boundary."""
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from backend_ops.worker import ProviderWorker
from backend_ops.worker_contract import contract_id, decode_result, encode, request
from sports_ticker.domain import ContentItem, DisplaySettings
from sports_ticker.providers.contracts import ProviderResult
from sports_ticker.providers.factory import create_provider

pytestmark = pytest.mark.critical


def message(settings=None):
    return {"protocol": 1, "contract": contract_id(), "op": "fetch", "ticker_id": "test",
            "settings": encode(settings or DisplaySettings(mode="clock"))}


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
