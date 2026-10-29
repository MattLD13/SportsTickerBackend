"""Own the strict JSON boundary between core and versioned fetcher workers."""
import ast
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import socket
import time
from uuid import uuid4

PROVIDERS = ("espn", "fotmob", "weather", "golf", "racing", "stock", "flights", "music", "news", "clock")
MAX_MESSAGE = 8 * 1024 * 1024
MAX_BATCH = 256


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=16)
def contract_id(root: Path | None = None):
    root = root or REPOSITORY_ROOT
    # Each release declares its own contract files in this literal list.
    paths = ["backend_ops/worker_contract.py", "sports_ticker/domain/models.py", "sports_ticker/providers/contracts.py",
             "sports_ticker/immutable.py"]
    paths = contract_files(root)
    digest = hashlib.sha256()
    for name in paths:
        digest.update(name.encode())
        digest.update((root / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def contract_files(root: Path | None = None):
    """Return the contract files that the release at ``root`` declares in ``contract_id``."""
    root = root or REPOSITORY_ROOT
    source = (root / "backend_ops/worker_contract.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "contract_id")
    declaration = next(node for node in function.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "paths" for target in node.targets))
    paths = ast.literal_eval(declaration.value)
    if not isinstance(paths, list) or not paths or any(
            not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts for name in paths):
        raise ValueError("invalid worker contract dependencies")
    return tuple(paths)


def encode(value):
    if is_dataclass(value):
        return {field.name: encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [encode(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _decode_content(items, receipt):
    from sports_ticker.domain import ContentItem
    content = []
    trace_prefix = uuid4().hex if receipt is not None else ""
    for item in items:
        if receipt is not None:
            timing = item["data"].get("_source_timing")
            timing = dict(timing) if isinstance(timing, Mapping) else {
                "trace_id": f"worker:{trace_prefix}:{item['id']}", "source": receipt["source"],
                "ingested_at_ms": receipt["core_received_at_ms"], "input_boundary": "core_worker_result_received",
            }
            timing.update(core_received_at_ms=receipt["core_received_at_ms"], request_started_ms=receipt["request_started_ms"])
            item = {**item, "data": {**item["data"], "_source_timing": timing}}
        content.append(ContentItem(**item))
    return tuple(content)


def _decode_provider_result(value, content):
    from sports_ticker.providers.contracts import ProviderHealth, ProviderResult
    return ProviderResult(content=content, alerts=tuple(value["alerts"]), news=tuple(value["news"]),
                          observed_at=datetime.fromisoformat(value["observed_at"]),
                          health=ProviderHealth(**value["health"]))


def decode_result(value, *, receipt=None):
    required = {"content", "alerts", "news", "observed_at", "health"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("worker result does not match the provider contract")
    content = _decode_content(value["content"], receipt)
    return _decode_provider_result(value, content)


def encode_batch(results):
    """Encode each shared immutable game once for the complete worker batch."""
    items, indices, encoded = [], {}, {}
    for ticker_id, result in results.items():
        references = []
        for item in result.content:
            key = id(item)
            if key not in indices:
                indices[key] = len(items)
                items.append(encode(item))
            references.append(indices[key])
        encoded[ticker_id] = {"content": references, "alerts": encode(result.alerts), "news": encode(result.news),
                             "observed_at": encode(result.observed_at), "health": encode(result.health)}
    return {"items": items, "results": encoded}


def decode_batch(value, expected_ids, *, receipt):
    """Restore shared games once and reject incomplete or cross-ticker batch results."""
    if (not isinstance(value, dict) or set(value) != {"items", "results"}
            or not isinstance(value["items"], list) or not isinstance(value["results"], dict)
            or set(value["results"]) != set(expected_ids)):
        raise ValueError("worker batch does not match the requested tickers")
    items = _decode_content(value["items"], receipt)
    results = {}
    for ticker_id, result in value["results"].items():
        if not isinstance(result, dict) or set(result) != {"content", "alerts", "news", "observed_at", "health"}:
            raise ValueError("worker batch result does not match the provider contract")
        refs = result["content"]
        if not isinstance(refs, list) or any(type(index) is not int or not 0 <= index < len(items) for index in refs):
            raise ValueError("worker batch contains an invalid game reference")
        results[ticker_id] = _decode_provider_result(result, tuple(items[index] for index in refs))
    return results


def exchange(path: Path, body: bytes, *, timeout: float) -> bytes:
    """Exchange one framed message with a local worker."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(body)
        with connection.makefile("rb") as source:
            return source.readline(MAX_MESSAGE + 1)


def request(path: Path, message: dict, *, timeout=30.0):
    body = json.dumps(message, separators=(",", ":")).encode() + b"\n"
    if len(body) > MAX_MESSAGE:
        raise ValueError("worker request exceeds the contract limit")
    response = exchange(path, body, timeout=timeout)
    if len(response) > MAX_MESSAGE or not response.endswith(b"\n"):
        raise ValueError("worker response exceeds the contract limit or is incomplete")
    result = json.loads(response)
    if result.get("protocol") != 1 or result.get("contract") != contract_id():
        raise ValueError("worker and core contracts do not match")
    return result


class WorkerProvider:
    """Read canonical provider results from one independently versioned process."""

    def __init__(self, name: str, directory: Path):
        if name not in PROVIDERS:
            raise ValueError("unknown fetcher component")
        self.name, self.socket = name, directory / (name + ".sock")

    def fetch_for_ticker(self, ticker_id, settings):
        return self._fetch("fetch", ticker_id, settings)

    def fetch_live_for_ticker(self, ticker_id, settings):
        return self._fetch("fetch_live", ticker_id, settings)

    def fetch_batch_for_tickers(self, settings_by_ticker, *, live_only=False):
        """Read bounded ticker batches with one shared game table per response."""
        selected = tuple(settings_by_ticker)
        results = {}
        for offset in range(0, len(selected), MAX_BATCH):
            identifiers = selected[offset:offset + MAX_BATCH]
            started = time.time() * 1000.0
            response = request(self.socket, {"protocol": 1, "contract": contract_id(), "op": "fetch_batch",
                                            "live_only": live_only,
                                            "tickers": {key: encode(settings_by_ticker[key]) for key in identifiers}})
            if response.get("error"):
                raise RuntimeError(response["error"])
            results.update(decode_batch(response["batch"], identifiers,
                                        receipt={"source": self.name, "request_started_ms": started,
                                                 "core_received_at_ms": time.time() * 1000.0}))
        return results

    def wait_for_changes(self, after, timeout):
        response = request(self.socket, {"protocol": 1, "contract": contract_id(), "op": "changes",
                                         "after": dict(after), "timeout": timeout}, timeout=timeout + 2)
        if response.get("error"):
            raise RuntimeError(response["error"])
        versions = response.get("versions")
        if not isinstance(versions, dict) or len(versions) > 64 or any(
                not isinstance(key, str) or not isinstance(value, str) for key, value in versions.items()):
            raise ValueError("invalid worker source versions")
        return versions

    def _fetch(self, operation, ticker_id, settings):
        started = time.time() * 1000.0
        response = request(self.socket, {"protocol": 1, "contract": contract_id(), "op": operation,
                                        "ticker_id": ticker_id, "settings": encode(settings)})
        if response.get("error"):
            raise RuntimeError(response["error"])
        return decode_result(response["result"], receipt={"source": self.name, "request_started_ms": started,
                                                         "core_received_at_ms": time.time() * 1000.0})

    def close(self):
        """Keep worker lifecycle ownership outside the core server process."""
