"""Consume ESPN scoreboard updates from the official Fastcast channel."""

from __future__ import annotations

import base64
import json
import math
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from threading import Condition, Event, RLock, Thread, current_thread
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from sports_ticker.tls import verified_https_context


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
        wall_clock: Callable[[], float] = time.time,
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
        self._wall_clock = wall_clock
        self._snapshots: dict[str, Any] = {}
        self._subscribed: set[str] = set()
        self._resync_required: set[str] = set()
        self._last_message_ids: dict[str, int] = {}
        self._last_topic_message_at: dict[str, float] = {}
        self._event_updated_at: dict[tuple[str, str], float] = {}
        self._event_timings: dict[tuple[str, str], Mapping[str, Any]] = {}
        self._errors: dict[str, str] = {}
        self._socket: _FastcastSocket | None = None
        self._last_message_at = 0.0
        self._worker: Thread | None = None
        self._stop = Event()
        self._lock = RLock()
        self._changed = Condition(self._lock)
        self._generation = uuid4().hex
        self._revisions = {league: 0 for league in normalized}

    def versions(self) -> dict[str, str]:
        """Return source versions, including an identity for this worker lifetime."""
        with self._lock:
            return {league: f"{self._generation}:{revision}" for league, revision in self._revisions.items()}

    def wait_for_changes(self, after: Mapping[str, str], timeout: float) -> dict[str, str]:
        """Wait for a source change without holding the provider fetch lock."""
        deadline = time.monotonic() + timeout
        with self._changed:
            self._changed.wait_for(lambda: self._stop.is_set() or self.versions() != after, timeout)
            if after and self.versions() != after:
                self._changed.wait_for(self._stop.is_set, min(0.025, max(0.0, deadline - time.monotonic())))
            return self.versions()

    def capture(self) -> tuple[dict[str, str], dict[str, tuple[Any, Mapping[str, Mapping[str, Any]]]]]:
        """Capture matching league versions and immutable input views for one consumer batch."""
        with self._lock:
            return self.versions(), {league: self.timed_snapshot(league) for league in self.topics}

    def _source_changed(self, league: str) -> None:
        self._revisions[league] += 1
        self._changed.notify_all()

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
        with self._changed:
            self._changed.notify_all()
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
        snapshot = _freeze_snapshot(payload)
        event_ids = _snapshot_event_ids(snapshot)
        updated_at = self._monotonic()
        with self._lock:
            self._snapshots[identifier] = snapshot
            self._resync_required.discard(identifier)
            self._errors.pop(identifier, None)
            for key in tuple(self._event_updated_at):
                if key[0] == identifier and key[1] not in event_ids:
                    self._event_updated_at.pop(key, None)
                    self._event_timings.pop(key, None)
            for event_id in event_ids:
                self._event_updated_at[(identifier, event_id)] = updated_at
                self._event_timings[(identifier, event_id)] = self._input_timing("espn_http", event_id)
            self._source_changed(identifier)

    def prime_event(
        self,
        league: str,
        event: Mapping[str, Any],
        *,
        if_updated_at: float | None = None,
    ) -> None:
        """Merge one HTTP event refresh into the Fastcast snapshot."""

        identifier = str(league).strip().lower()
        event_id = str(event.get("id") or "").strip() if isinstance(event, Mapping) else ""
        if identifier not in self.topics or not event_id:
            return
        with self._lock:
            key = (identifier, event_id)
            if (
                if_updated_at is not None
                and self._event_updated_at.get(key) != if_updated_at
            ):
                return
            snapshot = self._snapshots.get(identifier)
            if snapshot is None:
                return
            updated_snapshot = _replace_snapshot_event(snapshot, event)
            if updated_snapshot is None:
                return
            self._snapshots[identifier] = updated_snapshot
            self._event_updated_at[key] = self._monotonic()
            self._event_timings[key] = self._input_timing("espn_http", event_id)
            self._source_changed(identifier)

    def snapshot(self, league: str) -> Any | None:
        """Return one immutable scoreboard view that remains valid after later updates."""

        identifier = str(league).strip().lower()
        with self._lock:
            return self._snapshots.get(identifier)

    def event_updated_at(self, league: str, event_id: str) -> float | None:
        """Return the monotonic time when Fastcast last updated one event."""

        key = (str(league).strip().lower(), str(event_id).strip())
        with self._lock:
            return self._event_updated_at.get(key)

    def timed_snapshot(self, league: str) -> tuple[Any, Mapping[str, Mapping[str, Any]]]:
        """Read one immutable snapshot and its matching input timings atomically."""
        identifier = str(league).strip().lower()
        with self._lock:
            return self._snapshots.get(identifier), MappingProxyType({
                event_id: timing for (name, event_id), timing in self._event_timings.items() if name == identifier
            })

    def _input_timing(self, source: str, event_id: str) -> Mapping[str, Any]:
        return MappingProxyType({"trace_id": uuid4().hex + ":" + event_id, "source": source,
                                 "ingested_at_ms": self._wall_clock() * 1000.0, "input_boundary": "http_snapshot_applied"})

    def active(self, league: str) -> bool:
        """Return whether one league has a fresh subscribed stream."""

        identifier = str(league).strip().lower()
        with self._lock:
            worker = self._worker
            last_message_at = self._last_topic_message_at.get(identifier, 0.0)
            return bool(
                identifier in self._subscribed
                and identifier not in self._resync_required
                and identifier in self._snapshots
                and self._socket is not None
                and worker is not None
                and worker.is_alive()
                and last_message_at > 0
                and self._monotonic() - last_message_at <= _STALE_SECONDS
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
        received_at_ms = self._wall_clock() * 1000.0
        decoded = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(decoded, Sequence) and not isinstance(decoded, (str, bytes)):
            for message in decoded:
                if isinstance(message, Mapping):
                    self._handle_message(message, received_at_ms=received_at_ms)
            return
        self._handle_message(_json_object(decoded), received_at_ms=received_at_ms)

    def _handle_message(self, message: Mapping[str, Any], *, received_at_ms: float | None = None) -> None:
        """Apply one Fastcast acknowledgement, checkpoint, or patch update."""

        received_at_ms = self._wall_clock() * 1000.0 if received_at_ms is None else received_at_ms
        topic = str(message.get("tc") or "").strip()
        league = self._league_by_topic.get(topic)
        if league is None:
            return
        with self._lock:
            self._last_topic_message_at[league] = self._monotonic()
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
        if not isinstance(payload, Mapping) and not _is_patch_sequence(payload):
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
                updated_at = self._monotonic()
                event_ids = _patch_event_ids(payload, current)
                event_ids.update(_patch_event_ids(payload, updated))
                published = fastcast_published_at_ms(message)
                message_id = message.get("mid")
                trace_prefix = f"{topic}:{message_id if message_id is not None else uuid4().hex}"
                for event_id in event_ids:
                    self._event_updated_at[(league, event_id)] = updated_at
                    timing = {"trace_id": f"{trace_prefix}:{event_id}",
                              "source": "espn_fastcast", "ingested_at_ms": received_at_ms, "input_boundary": "fastcast_socket_received"}
                    if published is not None:
                        timing.update(source_published_at_ms=published, source_timestamp_kind="publisher_envelope")
                    self._event_timings[(league, event_id)] = MappingProxyType(timing)
                self._errors.pop(league, None)
                self._source_changed(league)

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


def _freeze_snapshot(value: Any) -> Any:
    """Detach incoming JSON once before sharing immutable snapshot branches."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_snapshot(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_snapshot(child) for child in value)
    raise TypeError(f"unsupported Fastcast JSON value: {type(value).__name__}")


def _snapshot_events(value: Any) -> tuple[Mapping[str, Any], ...]:
    """Read events from one complete ESPN scoreboard snapshot."""

    if not isinstance(value, Mapping):
        return ()
    events = value.get("events")
    if events is None:
        leagues = value.get("leagues")
        first_league = leagues[0] if isinstance(leagues, Sequence) and leagues else None
        events = first_league.get("events") if isinstance(first_league, Mapping) else ()
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        return ()
    return tuple(event for event in events if isinstance(event, Mapping))


def _snapshot_event_ids(value: Any) -> tuple[str, ...]:
    """Return unique event identifiers from one scoreboard snapshot."""

    return tuple(
        dict.fromkeys(
            str(event.get("id") or "").strip()
            for event in _snapshot_events(value)
            if str(event.get("id") or "").strip()
        )
    )


def _replace_snapshot_event(
    snapshot: Any,
    update: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    """Replace one event in a top-level or first-league scoreboard collection."""

    if not isinstance(snapshot, Mapping):
        return None
    event_id = str(update.get("id") or "").strip()
    if not event_id:
        return None
    result = dict(snapshot)
    frozen_update = _freeze_snapshot(update)
    events = result.get("events")
    if isinstance(events, Sequence) and not isinstance(events, (str, bytes)):
        updated_events = list(events)
        for index, event in enumerate(updated_events):
            if isinstance(event, Mapping) and str(event.get("id") or "").strip() == event_id:
                updated_events[index] = frozen_update
                result["events"] = tuple(updated_events)
                return MappingProxyType(result)
        updated_events.append(frozen_update)
        result["events"] = tuple(updated_events)
        return MappingProxyType(result)

    leagues = result.get("leagues")
    if not isinstance(leagues, Sequence) or isinstance(leagues, (str, bytes)) or not leagues:
        return None
    updated_leagues = list(leagues)
    for league_index, league in enumerate(updated_leagues):
        if not isinstance(league, Mapping):
            continue
        league_events = league.get("events")
        if not isinstance(league_events, Sequence) or isinstance(league_events, (str, bytes)):
            continue
        updated_events = list(league_events)
        for event_index, event in enumerate(updated_events):
            if isinstance(event, Mapping) and str(event.get("id") or "").strip() == event_id:
                updated_league = dict(league)
                updated_events[event_index] = frozen_update
                updated_league["events"] = tuple(updated_events)
                updated_leagues[league_index] = MappingProxyType(updated_league)
                result["leagues"] = tuple(updated_leagues)
                return MappingProxyType(result)
    return None


def _patch_event_ids(payload: Any, document: Any) -> set[str]:
    """Identify events touched by one Fastcast patch payload."""

    if not _is_patch_sequence(payload):
        return set(_snapshot_event_ids(payload)) or set(_snapshot_event_ids(document))
    event_ids: set[str] = set()
    known_event_ids = set(_snapshot_event_ids(document))
    for patch in payload:
        if not isinstance(patch, Mapping):
            continue
        for key in ("path", "from"):
            if key == "from" and str(patch.get("op") or "").lower() not in {"move", "copy"}:
                continue
            raw_path = str(patch.get(key) or "")
            if not raw_path:
                event_ids.update(known_event_ids)
                continue
            if raw_path.startswith("/"):
                event_ids.update(_absolute_patch_event_ids(document, raw_path, known_event_ids))
                continue
            uid = raw_path.split("/", 1)[0]
            uid = uid.replace("~0l:", "~l:").replace("~0e:", "~e:")
            target = _find_uid(document, uid)
            if isinstance(target, Mapping):
                event_id = str(target.get("id") or "").strip()
                if event_id:
                    event_ids.add(event_id)
                    continue
            if "~e:" in uid:
                event_id = uid.rsplit("~e:", 1)[-1].split("~", 1)[0].strip()
                if event_id in known_event_ids:
                    event_ids.add(event_id)
        value = patch.get("value")
        if isinstance(value, Mapping):
            event_id = str(value.get("id") or "").strip()
            if event_id:
                event_ids.add(event_id)
    return event_ids


def _absolute_patch_event_ids(
    document: Any,
    path: str,
    known_event_ids: set[str],
) -> set[str]:
    """Identify event records addressed by one absolute JSON pointer."""

    try:
        tokens = _pointer_parts(path)
    except ValueError:
        return set()
    node = document
    for index, token in enumerate(tokens):
        if token == "events":
            if index + 1 >= len(tokens):
                return set(known_event_ids)
            event_index = tokens[index + 1]
            try:
                event = node.get("events")[int(event_index)] if isinstance(node, Mapping) else None
            except (AttributeError, IndexError, TypeError, ValueError):
                return set()
            event_id = str(event.get("id") or "").strip() if isinstance(event, Mapping) else ""
            return {event_id} if event_id else set()
        if isinstance(node, Mapping):
            node = node.get(token)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            try:
                node = node[int(token)]
            except (IndexError, TypeError, ValueError):
                return set()
        else:
            return set()
    return set()


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
    with urlopen(request, timeout=timeout, context=verified_https_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_object(value: Any) -> Mapping[str, Any]:
    """Require one decoded Fastcast message object."""

    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise TypeError("Fastcast message must be an object")
    return value


def fastcast_published_at_ms(value: Any) -> float | None:
    """Read epoch milliseconds from publication wrappers, never from the sequence or game clock."""
    for _ in range(8):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return None
        if not isinstance(value, Mapping):
            return None
        timestamp = value.get("ts")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            if math.isfinite(timestamp) and 946684800000 <= timestamp <= 4102444800000:
                return float(timestamp)
        if "pl" not in value or value.get("~c"):
            return None
        value = value["pl"]
    return None


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
            return _freeze_snapshot(payload.get("data", payload))
        raise TypeError("Fastcast payload is not a JSON patch")
    result = document if isinstance(document, MappingProxyType) else _freeze_snapshot(document)
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
    """Copy only changed ancestors while applying one atomic JSON patch."""
    operation = str(patch.get("op") or "").strip().lower()
    if operation not in {"add", "remove", "replace", "copy", "move", "test"}:
        raise ValueError(f"unsupported Fastcast patch operation: {operation}")
    path = _resolve_patch_path(document, str(patch.get("path") or ""))
    if operation == "test":
        if _read_path(document, path) != _freeze_snapshot(patch.get("value")):
            raise ValueError("Fastcast patch test failed")
        return document
    if operation in {"copy", "move"}:
        source = _resolve_patch_path(document, str(patch.get("from") or ""))
        value = _read_path(document, source)
        if operation == "move":
            if len(path) > len(source) and path[:len(source)] == source:
                raise ValueError("Fastcast cannot move a value inside itself")
            document = _change_path(document, source, "remove")
            path = _resolve_patch_path(document, str(patch.get("path") or ""))
        return _change_path(document, path, "add", value)
    if operation == "remove":
        return _change_path(document, path, operation)
    return _change_path(document, path, operation, _freeze_snapshot(patch.get("value")))


def _resolve_patch_path(document: Any, path: str) -> tuple[str, ...]:
    """Resolve a UID-relative pointer into one path from the snapshot root."""
    if not path or path.startswith("/"):
        return _pointer_parts(path)
    parts = path.split("/", 1)
    uid = parts[0].replace("~0l:", "~l:").replace("~0e:", "~e:")
    base = _find_uid_path(document, uid)
    if base is None:
        return _pointer_parts(f"/{path}")
    return base + _pointer_parts(f"/{parts[1]}" if len(parts) > 1 else "")


def _find_uid_path(value: Any, uid: str) -> tuple[str, ...] | None:
    """Find the path of the first nested object with one matching ESPN UID."""
    if not uid:
        return None
    if isinstance(value, Mapping):
        if str(value.get("uid") or "") == uid:
            return ()
        children = value.items()
    elif isinstance(value, (list, tuple)):
        children = ((str(index), child) for index, child in enumerate(value))
    else:
        return None
    for key, child in children:
        path = _find_uid_path(child, uid)
        if path is not None:
            return (key, *path)
    return None


def _find_uid(value: Any, uid: str) -> Any | None:
    """Read a matching UID through the shared path resolver."""
    path = _find_uid_path(value, uid)
    return _read_path(value, path) if path is not None else None


def _pointer_parts(pointer: str) -> tuple[str, ...]:
    """Decode a JSON pointer into unescaped path tokens."""
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError("Fastcast JSON pointer must start with slash")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _read_path(value: Any, path: tuple[str, ...]) -> Any:
    """Read one path from an immutable snapshot."""
    for token in path:
        if isinstance(value, Mapping):
            value = value[token]
        elif isinstance(value, (list, tuple)):
            value = value[int(token)]
        else:
            raise KeyError(token)
    return value


def _change_path(node: Any, path: tuple[str, ...], operation: str, value: Any = None) -> Any:
    """Retain unchanged branches and rebuild only the path to one changed value."""
    if not path:
        if operation == "remove":
            raise ValueError("Fastcast cannot remove the document root")
        return value
    token, rest = path[0], path[1:]
    if isinstance(node, Mapping):
        changed = dict(node)
        if rest:
            changed[token] = _change_path(node[token], rest, operation, value)
        elif operation == "remove":
            del changed[token]
        else:
            if operation == "replace" and token not in node:
                raise KeyError(token)
            changed[token] = value
        return MappingProxyType(changed)
    if isinstance(node, (list, tuple)):
        changed = list(node)
        if rest:
            index = int(token)
            changed[index] = _change_path(node[index], rest, operation, value)
        elif operation == "add":
            if token == "-":
                changed.append(value)
            else:
                changed.insert(int(token), value)
        elif operation == "remove":
            del changed[int(token)]
        else:
            changed[int(token)] = value
        return tuple(changed)
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
