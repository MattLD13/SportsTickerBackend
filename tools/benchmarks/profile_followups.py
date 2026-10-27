"""Measure provider demand, Fastcast snapshots, and HTTPS connection reuse with fixed inputs."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import statistics
import sys
import tempfile
from threading import Thread
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=lambda item: dict(item)).encode()


def metrics(values):
    ordered = sorted(values)
    return {
        "count": len(values), "p50_ms": statistics.median(values),
        "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
    }


def demand(args):
    from sports_ticker.application.provider_demand import ProviderDemand
    from sports_ticker.application.schedule import ScheduleService
    from sports_ticker.application.state_store import SnapshotStore
    from sports_ticker.domain import DisplaySettings
    from sports_ticker.fleet import TickerRepository

    now = datetime(2026, 5, 5, 12, tzinfo=timezone.utc)
    providers = ("espn", "golf", "stock", "flights", "weather")
    with tempfile.TemporaryDirectory(prefix="ticker-demand-") as temporary:
        with TickerRepository(Path(temporary) / "fleet.sqlite3") as repository:
            schedules = ScheduleService(repository, SnapshotStore(), clock=lambda: now.timestamp())
            settings = {}
            for index in range(10):
                identifier = f"benchmark-{index}"
                settings[identifier] = DisplaySettings(mode="weather", timezone="UTC")
                repository.create_ticker(identifier, settings[identifier])
                schedules.create_block(identifier, days_of_week=[now.weekday()], start_minute=0, end_minute=1440,
                                       mode=("stock", "sports", "flights")[index % 3])
            policy = ProviderDemand(repository, schedules)
            queries = Counter()

            def count(statement):
                if statement.lstrip().upper().startswith("SELECT"):
                    queries["select"] += 1

            repository._connection.set_trace_callback(count)
            samples = []
            for _ in range(args.repeats):
                started = time.perf_counter()
                if args.demand_call == "single":
                    selected = {provider: frozenset(identifier for identifier, value in settings.items()
                                                     if policy(provider, identifier, value, now)) for provider in providers}
                else:
                    selected = policy(providers, settings, now)
                samples.append((time.perf_counter() - started) * 1000)
            return {"timing": metrics(samples), "selects_per_pass": queries["select"] / args.repeats,
                    "tickers": len(settings), "output_sha256": hashlib.sha256(canonical({key: sorted(value) for key, value in selected.items()})).hexdigest()}


def fastcast(args):
    from sports_ticker.providers.espn_fastcast import EspnFastcastSource

    payload = json.loads(args.espn_snapshot.read_text(encoding="utf-8"))
    source = EspnFastcastSource({"nfl": "scoreboard-football-nfl"})
    source.prime("nfl", payload)
    read_times, patch_times, event_times = [], [], []
    for index in range(args.repeats * 5):
        started = time.perf_counter()
        snapshot = source.snapshot("nfl")
        read_times.append((time.perf_counter() - started) * 1000)
        if index % 5 == 0:
            event = deepcopy(payload["events"][0])
            event["status"]["type"]["state"] = "pre"
            started = time.perf_counter()
            source.prime_event("nfl", event)
            event_times.append((time.perf_counter() - started) * 1000)
        message = {"op": "P", "tc": "scoreboard-football-nfl", "pl": json.dumps([
            {"op": "replace", "path": "/events/0/status/type/state", "value": "in" if index % 2 else "post"},
        ])}
        started = time.perf_counter()
        source._handle_message(message)
        patch_times.append((time.perf_counter() - started) * 1000)
        if source.error("nfl"):
            raise AssertionError(source.error("nfl"))
    snapshot = source.snapshot("nfl")
    return {"events": len(payload["events"]), "snapshot_read": metrics(read_times),
            "patch": metrics(patch_times), "event_refresh": metrics(event_times),
            "output_sha256": hashlib.sha256(canonical(snapshot)).hexdigest()}


def https(args):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from sports_ticker.providers import http

    with tempfile.TemporaryDirectory(prefix="ticker-https-") as temporary:
        root = Path(temporary)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ticker-benchmark")])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                       .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                       .not_valid_after(now + timedelta(hours=1))
                       .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                       .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
        (root / "cert.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        (root / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context = ssl.create_default_context(cafile=str(root / "cert.pem"))
        http.verified_https_context = lambda: context

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *values):
                pass

            def do_GET(self):
                body = b'{"value":7}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def get_request(self):
                connection, address = super().get_request()
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.connections += 1
                return connection, address

        server = Server(("127.0.0.1", 0), Handler)
        server.connections = 0
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(root / "cert.pem", root / "key.pem")
        server.socket = server_context.wrap_socket(server.socket, server_side=True)
        worker = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        worker.start()
        client = getattr(http, args.http_class)()
        samples, values = [], []
        try:
            for _ in range(args.repeats):
                started = time.perf_counter()
                values.append(client.get_json(f"https://127.0.0.1:{server.server_port}/data", timeout=2))
                samples.append((time.perf_counter() - started) * 1000)
        finally:
            if args.http_class == "PooledJsonHttpClient":
                client.close()
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
        if values != [{"value": 7}] * args.repeats:
            raise AssertionError("HTTPS responses changed")
        return {"timing": metrics(samples), "requests": args.repeats, "tls_connections": server.connections,
                "output_sha256": hashlib.sha256(canonical(values)).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--espn-snapshot", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--demand-call", choices=("single", "batch"), default="batch", help="Select the historical or current demand contract explicitly.")
    parser.add_argument("--http-class", default="PooledJsonHttpClient", help="Select the transport class in the measured source tree.")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    sys.path.insert(0, str(args.repository.resolve()))
    report = {"demand": demand(args), "fastcast": fastcast(args), "https": https(args)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
