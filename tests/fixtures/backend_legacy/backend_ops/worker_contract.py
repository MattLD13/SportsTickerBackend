"""Own the strict JSON boundary between core and versioned fetcher workers."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import socket

PROVIDERS = ("espn", "fotmob", "weather", "golf", "racing", "stock", "flights", "music", "news", "clock")
MAX_MESSAGE = 8 * 1024 * 1024


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=16)
def contract_id(root: Path | None = None):
    root = root or REPOSITORY_ROOT
    paths = ["backend_ops/worker_contract.py", "sports_ticker/domain/models.py", "sports_ticker/providers/contracts.py"]
    digest = hashlib.sha256()
    for name in paths:
        digest.update(name.encode())
        digest.update((root / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


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


def decode_result(value):
    from sports_ticker.domain import ContentItem
    from sports_ticker.providers.contracts import ProviderHealth, ProviderResult
    required = {"content", "alerts", "news", "observed_at", "health"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("worker result does not match the provider contract")
    return ProviderResult(content=tuple(ContentItem(**item) for item in value["content"]),
                          alerts=tuple(value["alerts"]), news=tuple(value["news"]),
                          observed_at=datetime.fromisoformat(value["observed_at"]),
                          health=ProviderHealth(**value["health"]))


def request(path: Path, message: dict, *, timeout=30.0):
    body = json.dumps(message, separators=(",", ":")).encode() + b"\n"
    if len(body) > MAX_MESSAGE:
        raise ValueError("worker request exceeds the contract limit")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(body)
        with connection.makefile("rb") as source:
            response = source.readline(MAX_MESSAGE + 1)
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
        response = request(self.socket, {"protocol": 1, "contract": contract_id(), "op": "fetch",
                                        "ticker_id": ticker_id, "settings": encode(settings)})
        if response.get("error"):
            raise RuntimeError(response["error"])
        return decode_result(response["result"])

    def close(self):
        """Keep worker lifecycle ownership outside the core server process."""
