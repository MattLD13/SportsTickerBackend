import asyncio
import json
import socket
import sys
import tempfile
import urllib.request
from pathlib import Path

import pytest

pytestmark = [pytest.mark.critical, pytest.mark.skipif(sys.platform == "win32", reason="Workers use Unix sockets")]

REPOSITORY = Path(__file__).resolve().parents[3]
FEATURE = '''
import itertools
from ticker3.sdk.feature import Feature, Poll

COUNTER = itertools.count()

class Demo(Feature):
    manifest = {{"feature": "demo", "title": "Demo", "version": {release!r},
                "settings": {{"fields": {{"name": {{"type": "string", "default": "x"}}}}}},
                "templates": [{{"id": "demo.card", "version": 1, "panels": {{"w64h32": {{"box": [64, 32], "flow": "page",
                    "parts": [{{"part": "text", "at": [0, 0], "font": "tiny", "value": "{{v}}"}},
                              {{"part": "text", "at": [0, 12], "font": "tiny", "value": "{{name}}"}}]}}}}}}]}}

    async def poll(self, config, context):
        return Poll([{{"id": "item", "template": "demo.card",
                      "values": {{"v": {release!r} + ":" + str(next(COUNTER)), "name": config["name"]}}}}], 0.3)

def create():
    return Demo()
'''


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def call(base, method, path, body=None, token=None):
    request = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = response.read()
            return response.status, (json.loads(data) if response.headers["content-type"] == "application/json" else data)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


class Device:
    def __init__(self, url):
        import websocket
        self.socket = websocket.create_connection(url, timeout=10)
        self.messages = []

    def send(self, message):
        self.socket.send(json.dumps(message))

    def next(self, kind, test=lambda message: True):
        while True:
            message = json.loads(self.socket.recv())
            self.messages.append(message)
            if message["t"] == kind and test(message):
                return message


def test_pairing_playlist_device_stream_and_hot_swap_deploy():
    async def scenario(directory: Path):
        from hypercorn.asyncio import serve
        from hypercorn.config import Config

        from ticker3.core.app import CoreApp
        from ticker3.core.builtin import BUILTINS
        from ticker3.core.hub import Hub
        from ticker3.core.store import Store
        from ticker3.core.supervisor import Supervisor, WorkerSpec

        for release in ("r1", "r2"):
            root = directory / "releases" / release
            root.mkdir(parents=True)
            (root / "ticker3").symlink_to(REPOSITORY / "ticker3", target_is_directory=True)
            (root / "demo_feature.py").write_text(FEATURE.format(release=release), encoding="utf-8")
        hub = Hub()
        for builtin in BUILTINS.values():
            hub.register(builtin.manifest, builtin=builtin)
        store = Store(directory / "ticker3.sqlite3")
        app = CoreApp(hub, store, admin_token="admin-token-for-tests", ping_seconds=30)
        supervisor = Supervisor(hub, directory / "core.sock", directory / "supervisor.json", [WorkerSpec("demo", "demo_feature")],
                                lambda release: directory / "releases" / release, initial_release="r1",
                                log_directory=directory / "logs", adopt_seconds=0, watch_seconds=0.05,
                                worker_arguments=("--health-seconds", "0.2"))
        app.supervisor = supervisor
        await supervisor.start()
        port = free_port()
        config = Config()
        config.bind = [f"127.0.0.1:{port}"]
        config.accesslog = None
        stop = asyncio.Event()
        server = asyncio.create_task(serve(app, config, shutdown_trigger=stop.wait))
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if "demo" in hub.manifests:
                    break
                await asyncio.sleep(0.05)
            status, features = await asyncio.to_thread(call, base, "GET", "/v3/features")
            assert status == 200 and {item["feature"] for item in features} == {"clock", "demo"}
            status, _ = await asyncio.to_thread(call, base, "POST", "/v3/tickers", {"name": "Den"})
            assert status == 403
            status, created = await asyncio.to_thread(call, base, "POST", "/v3/tickers", {"name": "Den", "timezone": "America/Denver"},
                                                      "admin-token-for-tests")
            assert status == 200
            ticker = created["id"]
            status, paired = await asyncio.to_thread(call, base, "POST", "/v3/pair", {"code": created["pairing_code"]})
            token = paired["app_token"]
            status, error = await asyncio.to_thread(call, base, "PUT", f"/v3/tickers/{ticker}/apps",
                                                    {"apps": [{"id": "d", "feature": "demo", "settings": {"color": "red"}}]}, token)
            assert status == 400 and "unknown settings" in error["error"]
            status, view = await asyncio.to_thread(call, base, "PUT", f"/v3/tickers/{ticker}/apps", {"apps": [
                {"id": "d", "feature": "demo", "settings": {"name": "den"}}, {"id": "c", "feature": "clock", "settings": {}}]}, token)
            assert status == 200 and [app["feature"] for app in view["apps"]] == ["demo", "clock"]

            device = await asyncio.to_thread(Device, f"ws://127.0.0.1:{port}/v3/stream")
            await asyncio.to_thread(device.send, {"t": "hello", "protocol": 1, "token": created["device_token"], "panel": "w64h32"})
            templates = await asyncio.to_thread(device.next, "templates")
            assert set(templates["templates"]) == {"clock.face", "demo.card"}
            screens = await asyncio.to_thread(device.next, "screens")
            assert [screen["id"] for screen in screens["screens"]][-1] == "c/clock"
            delta = await asyncio.to_thread(device.next, "delta", lambda message: "upsert" in message)
            [change] = delta["upsert"]
            assert change["id"] == "d/item" and set(change["values"]) == {"v"} and change["values"]["v"].startswith("r1:")
            assert len(json.dumps(delta, separators=(",", ":"))) < 80

            again = await asyncio.to_thread(Device, f"ws://127.0.0.1:{port}/v3/stream")
            await asyncio.to_thread(again.send, {"t": "hello", "protocol": 1, "token": created["device_token"], "panel": "w64h32",
                                                 "bundle": templates["bundle"]})
            first = await asyncio.to_thread(again.next, "screens")
            assert again.messages == [first]
            again.socket.close()

            status, result = await asyncio.to_thread(call, base, "POST", "/v3/deploy", {"feature": "demo", "release": "r2"},
                                                     "admin-token-for-tests")
            assert status == 200 and result == {"promoted": True}
            swapped = await asyncio.to_thread(device.next, "delta", lambda message: any(
                item.get("values", {}).get("v", "").startswith("r2:") for item in message.get("upsert", ())))
            assert swapped["upsert"][0]["id"] == "d/item"
            assert not [message for message in device.messages if message["t"] in ("screens", "templates")][2:]

            status, png = await asyncio.to_thread(call, base, "GET", f"/v3/tickers/{ticker}/frame.png?panel=w64h32", None, token)
            assert status == 200 and png[:8] == b"\x89PNG\r\n\x1a\n"
            status, health = await asyncio.to_thread(call, base, "GET", "/v3/health")
            assert health["workers"]["demo"]["active"] == "r2" and health["workers"]["demo"]["previous"] == "r1"
            device.socket.close()
        finally:
            stop.set()
            await server
            await supervisor.stop(stop_workers=True)
            store.close()

    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        asyncio.run(asyncio.wait_for(scenario(Path(directory)), 90))
