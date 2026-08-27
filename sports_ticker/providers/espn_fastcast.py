"""Consume ESPN scoreboard updates from the official Fastcast channel."""

from __future__ import annotations

import base64
import copy
import json
import math
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from threading import Event, RLock, Thread, current_thread
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen


_DISCOVERY_URL = "https://fastcast.semfs.engsvc.go.com/public/websockethost"
_PROFILE_ID = 12000
_DEFAULT_TIMEOUT = 10.0
_RECEIVE_TIMEOUT = 5.0
_STALE_SECONDS = 45.0
_MAX_RECONNECT_WAIT = 30.0
_USER_AGENT = "SportsTickerBackend/8"


class _FastcastSocket(Protocol):
    """Expose the WebSocket methods used by the feed worker."""

    def send(self, payload: str) -> Any:
        """Send one JSON message."""

    def recv(self) -> str:
        """Receive one JSON message."""

    def settimeout(self, timeout: float) -> Any:
        """Set the receive timeout."""

    def close(self) -> Any:
        """Close the socket."""


DiscoveryReader = Callable[[float], Mapping[str, Any]]
SocketConnector = Callable[[str, float], _FastcastSocket]


class EspnFastcastSource:
    """Keep one shared ESPN scoreboard stream for all configured leagues."""

    def __init__(
        self,
        topics: Mapping[str, str],
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        discovery_reader: DiscoveryReader | None = None,
        socket_connector: SocketConnector | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(topics, Mapping):
            raise TypeError("topics must be a mapping")
        normalized = {
            str(league).strip().lower(): str(topic).strip()
            for league, topic in topics.items()
            if str(league).strip() and str(topic).strip()
        }
        if not normalized:
            raise ValueError("topics must contain one league")
        request_timeout = float(timeout)
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.topics = normalized
        self._league_by_topic = {topic: league for league, topic in normalized.items()}
        self._timeout = request_timeout
        self._discover = discovery_reader or _discover_fastcast
        self._connect = socket_connector or _connect_fastcast
        self._monotonic = monotonic
        self._snapshots: dict[str, Any] = {}
        self._subscribed: set[str] = set()
        self._resync_required: set[str] = set()
        self._last_message_ids: dict[str, int] = {}
        self._errors: dict[str, str] = {}
        self._socket: _FastcastSocket | None = None
        self._last_message_at = 0.0
        self._worker: Thread | None = None
        self._stop = Event()
        self._lock = RLock()

    def start(self) -> None:
        """Start the one background stream worker when it is not running."""

        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = Thread(
                target=self._run,
                name="espn-fastcast",
                daemon=True,
            )
            self._worker.start()

    def close(self) -> None:
        """Stop the stream worker and close its current socket."""

        self._stop.set()
        with self._lock:
            socket = self._socket
            worker = self._worker
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass
        if worker is not None and worker is not current_thread():
            worker.join(timeout=2.0)
        with self._lock:
            self._socket = None
            self._subscribed.clear()

    def prime(self, league: str, payload: Any) -> None:
        """Set the complete HTTP scoreboard used as the patch base."""

        identifier = str(league).strip().lower()
        if identifier not in self.topics:
            return
        if not isinstance(payload, Mapping):
            raise TypeError("Fastcast snapshots must be objects")
        with self._lock:
            self._snapshots[identifier] = copy.deepcopy(payload)
            self._resync_required.discard(identifier)
            self._errors.pop(identifier, None)

    def snapshot(self, league: str) -> Any | None:
        """Return one immutable-by-copy scoreboard snapshot when available."""

        identifier = str(league).strip().lower()
        with self._lock:
            value = self._snapshots.get(identifier)
            return copy.deepcopy(value) if value is not None else None

    def active(self, league: str) -> bool:
        """Return whether one league has a fresh subscribed stream."""

        identifier = str(league).strip().lower()
        with self._lock:
            worker = self._worker
            return bool(
                identifier in self._subscribed
                and identifier not in self._resync_required
                and identifier in self._snapshots
                and self._socket is not None
                and worker is not None
                and worker.is_alive()
                and self._last_message_at > 0
                and self._monotonic() - self._last_message_at <= _STALE_SECONDS
            )

    def error(self, league: str) -> str | None:
        """Return the latest nonfatal stream error for one league."""

        with self._lock:
            return self._errors.get(str(league).strip().lower())

    def _run(self) -> None:
        reconnect_wait = 1.0
        while not self._stop.is_set():
            socket: _FastcastSocket | None = None
            try:
                discovery = self._discover(self._timeout)
                endpoint = _fastcast_socket_url(discovery)
                socket = self._connect(endpoint, self._timeout)
                socket.settimeout(_RECEIVE_TIMEOUT)
                with self._lock:
                    self._socket = socket
                    self._subscribed.clear()
                    self._last_message_at = self._monotonic()
                socket.send(json.dumps({"op": "C"}, separators=(",", ":")))
                session_id = self._connect_session(socket)
                self._subscribe(socket, session_id)
                reconnect_wait = 1.0
                while not self._stop.is_set():
                    try:
                        raw = socket.recv()
                    except Exception as error:
                        if _is_socket_timeout(error):
                            with self._lock:
                                stale = (
                                    self._last_message_at <= 0
                                    or self._monotonic() - self._last_message_at > _STALE_SECONDS
                                )
                            if not stale:
                                continue
                        raise
                    with self._lock:
                        self._last_message_at = self._monotonic()
                    self._handle_wire_message(raw)
            except Exception as error:
                if self._stop.is_set():
                    break
                self._mark_disconnected(str(error) or type(error).__name__)
                if self._stop.wait(reconnect_wait):
                    break
                reconnect_wait = min(_MAX_RECONNECT_WAIT, reconnect_wait * 1.65)
            finally:
                if socket is not None:
                    try:
                        socket.close()
                    except Exception:
                        pass
                with self._lock:
                    if self._socket is socket:
                        self._socket = None
                        self._subscribed.clear()

    def _connect_session(self, socket: _FastcastSocket) -> str:
        """Read the Fastcast connection acknowledgement and return its session ID."""

        while True:
            raw = socket.recv()
            with self._lock:
                self._last_message_at = self._monotonic()
            message = _json_object(raw)
            if int(message.get("rc") or 0) >= 400:
                raise RuntimeError(f"Fastcast connect returned {message.get('rc')}")
            if str(message.get("op") or "") == "C":
                session_id = str(message.get("sid") or "").strip()
                if not session_id:
                    raise RuntimeError("Fastcast connect response omitted sid")
                return session_id

    def _subscribe(self, socket: _FastcastSocket, session_id: str) -> None:
        """Subscribe one Fastcast topic for every configured ESPN league."""

        pending = set(self.topics.values())
        for topic in pending:
            socket.send(
                json.dumps(
                    {"op": "S", "sid": session_id, "tc": topic},
                    separators=(",", ":"),
                )
            )
        while pending and not self._stop.is_set():
            raw = socket.recv()
            with self._lock:
                self._last_message_at = self._monotonic()
            message = _json_object(raw)
            topic = str(message.get("tc") or "").strip()
            if str(message.get("op") or "") == "S" and topic in pending:
                pending.discard(topic)
            self._handle_message(message)
        if pending:
            raise RuntimeError("Fastcast subscription stopped")

    def _handle_wire_message(self, raw: str) -> None:
        """Decode one wire frame that contains one message or a message list."""

        decoded = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(decoded, Sequence) and not isinstance(decoded, (str, bytes)):
            for message in decoded:
                if isinstance(message, Mapping):
                    self._handle_message(message)
            return
        self._handle_message(_json_object(decoded))

    def _handle_message(self, message: Mapping[str, Any]) -> None:
        """Apply one Fastcast acknowledgement, checkpoint, or patch update."""

        topic = str(message.get("tc") or "").strip()
        league = self._league_by_topic.get(topic)
        if league is None:
            return
        operation = str(message.get("op") or "").strip().upper()
        try:
            code = int(message.get("rc") or 0)
        except (TypeError, ValueError):
            code = 0
        if code >= 400:
            with self._lock:
                self._errors[league] = f"Fastcast {operation or 'message'} returned {code}"
                self._subscribed.discard(league)
            return
        if operation == "S":
            with self._lock:
                self._subscribed.add(league)
                self._errors.pop(league, None)
            return
        if operation in {"B", "C", "M"}:
            return

        message_gap = self._record_message_id(league, message)
        payload = _decode_fastcast_payload(message)
        if isinstance(payload, Mapping) and payload.get("p"):
            return
        checkpoint_url = _checkpoint_url(message, payload)
        if operation == "H" or checkpoint_url:
            if checkpoint_url:
                try:
                    self.prime(league, _read_json(checkpoint_url, timeout=self._timeout))
                except Exception as error:
                    self._mark_topic_error(league, error)
            elif operation == "H" and isinstance(payload, Mapping):
                self.prime(league, payload)
            return
        if message_gap:
            return
        if payload is None:
            return
        with self._lock:
            current = self._snapshots.get(league)
            if current is None or league in self._resync_required:
                return
            try:
                updated = _apply_fastcast_payload(current, payload)
            except Exception as error:
                self._resync_required.add(league)
                self._errors[league] = str(error) or type(error).__name__
            else:
                self._snapshots[league] = updated
                self._errors.pop(league, None)

    def _mark_topic_error(self, league: str, error: Exception) -> None:
        """Mark one topic stale until a complete scoreboard primes it again."""

        with self._lock:
            self._resync_required.add(league)
            self._errors[league] = str(error) or type(error).__name__

    def _record_message_id(self, league: str, message: Mapping[str, Any]) -> bool:
        """Detect a missing numeric Fastcast message before applying a patch."""

        raw_id = message.get("mid")
        if isinstance(raw_id, bool):
            return False
        try:
            message_id = int(raw_id)
        except (TypeError, ValueError):
            return False
        with self._lock:
            previous = self._last_message_ids.get(league)
            self._last_message_ids[league] = message_id
            if previous is None or message_id == previous + 1:
                return False
            self._resync_required.add(league)
            self._errors[league] = f"Fastcast message gap {previous}->{message_id}"
            return True

    def _mark_disconnected(self, error: str) -> None:
        """Make every topic use the HTTP path while the stream reconnects."""

        with self._lock:
            self._socket = None
            self._subscribed.clear()
            if error:
                for league in self.topics:
                    self._errors[league] = error


def fastcast_topic(scoreboard_url: str) -> str:
    """Build ESPN's scoreboard topic name from one scoreboard endpoint."""

    parsed = urlsplit(str(scoreboard_url).strip())
    parts = tuple(part for part in parsed.path.split("/") if part)
    try:
        index = parts.index("sports")
        sport = parts[index + 1]
        league = parts[index + 2]
    except (ValueError, IndexError) as error:
        raise ValueError("scoreboard URL must contain /sports/{sport}/{league}/") from error
    topic = f"scoreboard-{sport}-{league}"
    group = parse_qs(parsed.query).get("groups", [""])[0].strip()
    return f"{topic}-{group}" if group else topic


def _discover_fastcast(timeout: float) -> Mapping[str, Any]:
    """Resolve one Fastcast host and its short-lived traffic token."""

    return _read_json(_DISCOVERY_URL, timeout=timeout)


def _connect_fastcast(url: str, timeout: float) -> _FastcastSocket:
    """Open one ESPN Fastcast WebSocket with the browser-compatible origin."""

    try:
        import websocket
    except ImportError as error:
        raise RuntimeError("websocket-client is required for ESPN Fastcast") from error
    return websocket.create_connection(
        url,
        timeout=timeout,
        origin="https://www.espn.com",
        header=[f"User-Agent: {_USER_AGENT}"],
        enable_multithread=True,
    )


def _fastcast_socket_url(discovery: Mapping[str, Any]) -> str:
    """Build one authenticated WebSocket URL from the discovery response."""

    host = str(discovery.get("ip") or discovery.get("host") or "").strip()
    if not host:
        raise ValueError("Fastcast discovery omitted host")
    try:
        port = int(discovery.get("securePort") or discovery.get("port") or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("Fastcast discovery returned an invalid port") from error
    if port <= 0:
        raise ValueError("Fastcast discovery omitted port")
    token = str(discovery.get("token") or "").strip()
    if not token:
        raise ValueError("Fastcast discovery omitted token")
    return (
        f"wss://{host}:{port}/FastcastService/pubsub/profiles/{_PROFILE_ID}"
        f"?TrafficManager-Token={quote(token, safe='')}"
    )


def _read_json(url: str, *, timeout: float) -> Any:
    """Read one JSON document with the provider's user agent."""

    request = Request(
        str(url),
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_object(value: Any) -> Mapping[str, Any]:
    """Require one decoded Fastcast message object."""

    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise TypeError("Fastcast message must be an object")
    return value


def _decode_fastcast_payload(value: Any) -> Any:
    """Decode one ESPN plain or compressed payload wrapper."""

    if isinstance(value, Mapping) and "pl" in value:
        payload = value.get("pl")
        if value.get("~c"):
            payload = _inflate_base64(payload)
        return _decode_fastcast_payload(payload)

    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return value
    if not isinstance(decoded, Mapping) or "pl" not in decoded:
        return decoded
    payload = decoded.get("pl")
    if decoded.get("~c"):
        payload = _inflate_base64(payload)
    return _decode_fastcast_payload(payload) if isinstance(payload, str) else payload


def _inflate_base64(value: Any) -> str:
    """Inflate one ESPN compressed base64 payload into UTF-8 JSON text."""

    if not isinstance(value, str):
        raise TypeError("compressed Fastcast payload must be text")
    encoded = value.encode("ascii")
    encoded += b"=" * (-len(encoded) % 4)
    try:
        raw = base64.b64decode(encoded, validate=False)
    except (ValueError, UnicodeEncodeError) as error:
        raise ValueError("invalid compressed Fastcast payload") from error
    for window_bits in (zlib.MAX_WBITS, zlib.MAX_WBITS | 16, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(raw, window_bits).decode("utf-8")
        except (zlib.error, UnicodeDecodeError):
            continue
    raise ValueError("invalid compressed Fastcast payload")


def _checkpoint_url(message: Mapping[str, Any], payload: Any) -> str | None:
    """Read a checkpoint URL from one Fastcast control message."""

    for source in (message, payload if isinstance(payload, Mapping) else {}):
        for key in ("edgeUrl", "checkpointUrl", "url"):
            value = str(source.get(key) or "").strip()
            if value.startswith(("http://", "https://")):
                return value
    if isinstance(payload, str) and payload.startswith(("http://", "https://")):
        return payload
    return None


def _apply_fastcast_payload(document: Any, payload: Any) -> Any:
    """Apply one Fastcast JSON patch payload or replace the current snapshot."""

    patches = payload if _is_patch_sequence(payload) else (payload,)
    if not all(_is_patch(patch) for patch in patches):
        if isinstance(payload, Mapping):
            return copy.deepcopy(payload.get("data", payload))
        raise TypeError("Fastcast payload is not a JSON patch")
    result = copy.deepcopy(document)
    for patch in patches:
        result = _apply_json_patch(result, patch)
    return result


def _is_patch_sequence(value: Any) -> bool:
    """Return whether a value contains JSON patch records."""

    return bool(
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and all(_is_patch(item) for item in value)
    )


def _is_patch(value: Any) -> bool:
    """Return whether a value has the JSON patch operation shape."""

    return isinstance(value, Mapping) and "op" in value and "path" in value


def _apply_json_patch(document: Any, patch: Mapping[str, Any]) -> Any:
    """Apply one JSON patch with ESPN's UID-relative path extension."""

    operation = str(patch.get("op") or "").strip().lower()
    if operation not in {"add", "remove", "replace", "copy", "move", "test"}:
        raise ValueError(f"unsupported Fastcast patch operation: {operation}")
    target, pointer = _resolve_patch_target(document, str(patch.get("path") or ""))
    if operation == "test":
        if _read_pointer(target, pointer) != patch.get("value"):
            raise ValueError("Fastcast patch test failed")
        return document
    if operation in {"copy", "move"}:
        source_target, source_pointer = _resolve_patch_target(
            document,
            str(patch.get("from") or ""),
        )
        value = copy.deepcopy(_read_pointer(source_target, source_pointer))
        if operation == "move":
            document = _remove_pointer(document, source_target, source_pointer)
            target, pointer = _resolve_patch_target(document, str(patch.get("path") or ""))
        return _add_pointer(document, target, pointer, value)
    if operation == "remove":
        return _remove_pointer(document, target, pointer)
    if operation == "replace":
        return _replace_pointer(document, target, pointer, copy.deepcopy(patch.get("value")))
    return _add_pointer(document, target, pointer, copy.deepcopy(patch.get("value")))


def _resolve_patch_target(document: Any, path: str) -> tuple[Any, str]:
    """Resolve ESPN's optional UID prefix before applying a JSON pointer."""

    raw = str(path)
    if raw == "":
        return document, ""
    parts = raw.split("/")
    uid = parts[0].replace("~0l:", "~l:").replace("~0e:", "~e:")
    if raw.startswith("/"):
        return document, raw
    relative = "/" + "/".join(parts[1:]) if len(parts) > 1 else ""
    target = _find_uid(document, uid)
    return (target, relative) if target is not None else (document, f"/{raw}")


def _find_uid(value: Any, uid: str) -> Any | None:
    """Find the first nested object with one matching ESPN UID."""

    if not uid:
        return None
    if isinstance(value, Mapping):
        if str(value.get("uid") or "") == uid:
            return value
        for child in value.values():
            found = _find_uid(child, uid)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            found = _find_uid(child, uid)
            if found is not None:
                return found
    return None


def _pointer_parts(pointer: str) -> tuple[str, ...]:
    """Decode a JSON pointer into unescaped path tokens."""

    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError("Fastcast JSON pointer must start with slash")
    return tuple(
        token.replace("~1", "/").replace("~0", "~")
        for token in pointer[1:].split("/")
    )


def _read_pointer(target: Any, pointer: str) -> Any:
    """Read one JSON pointer from a resolved patch target."""

    value = target
    for token in _pointer_parts(pointer):
        if isinstance(value, Mapping):
            value = value[token]
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            value = value[int(token)]
        else:
            raise KeyError(token)
    return value


def _parent_pointer(target: Any, pointer: str) -> tuple[Any, str]:
    """Return one pointer's parent and final token."""

    parts = _pointer_parts(pointer)
    if not parts:
        return None, ""
    parent = target
    for token in parts[:-1]:
        if isinstance(parent, Mapping):
            parent = parent[token]
        elif isinstance(parent, Sequence) and not isinstance(parent, (str, bytes)):
            parent = parent[int(token)]
        else:
            raise KeyError(token)
    return parent, parts[-1]


def _add_pointer(document: Any, target: Any, pointer: str, value: Any) -> Any:
    """Add one value to a mapping, array, or document root."""

    parent, token = _parent_pointer(target, pointer)
    if parent is None:
        return value
    if isinstance(parent, dict):
        parent[token] = value
        return document
    if isinstance(parent, list):
        if token == "-":
            parent.append(value)
        else:
            parent.insert(int(token), value)
        return document
    raise TypeError("Fastcast patch parent is not a container")


def _replace_pointer(document: Any, target: Any, pointer: str, value: Any) -> Any:
    """Replace one value in a mapping, array, or document root."""

    parent, token = _parent_pointer(target, pointer)
    if parent is None:
        return value
    if isinstance(parent, dict):
        if token not in parent:
            raise KeyError(token)
        parent[token] = value
        return document
    if isinstance(parent, list):
        parent[int(token)] = value
        return document
    raise TypeError("Fastcast patch parent is not a container")


def _remove_pointer(document: Any, target: Any, pointer: str) -> Any:
    """Remove one value from a mapping or array."""

    parent, token = _parent_pointer(target, pointer)
    if parent is None:
        raise ValueError("Fastcast cannot remove the document root")
    if isinstance(parent, dict):
        del parent[token]
        return document
    if isinstance(parent, list):
        del parent[int(token)]
        return document
    raise TypeError("Fastcast patch parent is not a container")


def _is_socket_timeout(error: Exception) -> bool:
    """Identify timeout exceptions from websocket-client without importing its type."""

    return type(error).__name__ in {"WebSocketTimeoutException", "timeout"} or isinstance(
        error,
        TimeoutError,
    )


__all__ = [
    "EspnFastcastSource",
    "fastcast_topic",
    "_apply_fastcast_payload",
    "_decode_fastcast_payload",
    "_fastcast_socket_url",
]
