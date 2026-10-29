import asyncio
import gzip
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

import pytest

from ticker3.sdk.http import HttpClient, UpstreamError

pytestmark = pytest.mark.critical


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            with self.server.lock:
                self.server.requests.append((self.path, dict(self.headers), time.monotonic()))
            if self.path == "/slow":
                time.sleep(0.2)
            status, headers = 200, {}
            body = json.dumps({"path": self.path, "version": self.server.version}).encode()
            if self.path == "/etag":
                headers["ETag"] = f'"v{self.server.version}"'
                if self.headers.get("If-None-Match") == headers["ETag"]:
                    status, body = 304, b""
            if self.path == "/down":
                status, body = 503, b"down"
            if status == 200 and "gzip" in self.headers.get("Accept-Encoding", ""):
                body, headers["Content-Encoding"] = gzip.compress(body), "gzip"
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    instance.daemon_threads = True
    instance.lock, instance.requests, instance.version = Lock(), [], 1
    Thread(target=instance.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    instance.url = f"http://127.0.0.1:{instance.server_port}"
    yield instance
    instance.shutdown()
    instance.server_close()


def test_gzip_revalidation_and_reuse(server):
    async def scenario():
        client = HttpClient()
        assert (await client.get_json(server.url + "/etag"))["version"] == 1
        assert (await client.get_json(server.url + "/etag"))["version"] == 1
        server.version = 2
        assert (await client.get_json(server.url + "/etag", reuse=60))["version"] == 1
        assert (await client.get_json(server.url + "/etag"))["version"] == 2
        client.close()
        return client
    client = asyncio.run(scenario())
    assert client.requests == 3 and client.not_modified == 1
    assert server.requests[0][1]["Accept-Encoding"] == "gzip, deflate"
    assert server.requests[1][1]["If-None-Match"] == '"v1"'


def test_concurrent_reads_of_one_url_share_one_request(server):
    async def scenario():
        client = HttpClient()
        results = await asyncio.gather(*(client.get_json(server.url + "/slow") for _ in range(10)))
        client.close()
        return results
    assert len(asyncio.run(scenario())) == 10
    assert len(server.requests) == 1


def test_host_spacing_and_errors(server):
    async def scenario():
        client = HttpClient(spacing={"127.0.0.1": 0.15})
        await client.get_json(server.url + "/a")
        await client.get_json(server.url + "/b")
        with pytest.raises(UpstreamError, match="HTTP 503"):
            await client.get_json(server.url + "/down")
        client.close()
    asyncio.run(scenario())
    times = [entry[2] for entry in server.requests]
    assert times[1] - times[0] >= 0.14 and times[2] - times[1] >= 0.14
