"""Deterministic controller state and scheduling policies."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, TypeVar

from .model import (
    Content,
    ContentClassification,
    FrameDecision,
    FrameKind,
    ModeRequest,
    PayloadSnapshot,
    RuntimeConfig,
    StripLayout,
    UpdateRequest,
    frozen_mapping,
)


T = TypeVar("T")
CANONICAL_MODES = frozenset({"sports", "sports_full", "weather", "music", "flights", "clock"})


def _value(source: object, name: str, default: T) -> T | Any:
    """Read one named value from a mapping or object."""
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _mapping(source: object) -> Mapping[str, Any]:
    """Return an item mapping from protocol data."""
    if isinstance(source, Mapping):
        return source
    data = getattr(source, "data", None)
    if isinstance(data, Mapping):
        return data
    return {}


def _content(source: object) -> Content:
    """Normalize one protocol content item."""
    data = _mapping(source)
    return Content(
        id=str(_value(source, "id", data.get("id", ""))),
        type=str(_value(source, "type", data.get("type", ""))),
        sport=str(_value(source, "sport", data.get("sport", ""))),
        data=frozen_mapping(data),
    )


def _event(source: object) -> tuple[str, Mapping[str, Any]]:
    """Normalize one alert or news item."""
    data = _mapping(source)
    identifier = str(_value(source, "id", data.get("id", "")))
    return identifier, frozen_mapping(data)


def _fingerprint(response: object, content: tuple[Content, ...]) -> str:
    """Build a stable key when the protocol does not provide one."""
    provided = _value(response, "payload_key", None)
    if not provided:
        provided = _value(response, "fingerprint", None)
    if provided:
        return str(provided)
    values = [dict(item.data) for item in content]
    encoded = json.dumps(values, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _strip_fingerprint(content: tuple[Content, ...], mode: str) -> str:
    """Build one key for scrolling pixels, excluding alerts and settings."""
    values = {
        "mode": mode,
        "content": [
            {
                "id": item.id,
                "type": item.type,
                "sport": item.sport,
                "data": _plain_json(item.data),
            }
            for item in content
        ],
    }
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _plain_json(value: object) -> object:
    """Convert immutable protocol values into stable JSON values."""
    if isinstance(value, Mapping):
        return {str(key): _plain_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(child) for child in value]
    if isinstance(value, list):
        return [_plain_json(child) for child in value]
    return value


def classify_content(items: tuple[Content, ...] | tuple[object, ...], mode: str) -> ContentClassification:
    """Classify content for one canonical app mode."""
    selected_mode = _canonical_mode(mode)
    normalized = tuple(entry if isinstance(entry, Content) else _content(entry) for entry in items)
    weather: Content | None = None
    arrivals: list[Content] = []
    departures: list[Content] = []
    others: list[Content] = []
    for item in normalized:
        if item.type == "flight_weather":
            weather = item
        elif item.type == "flight_arrival":
            arrivals.append(item)
        elif item.type == "flight_departure":
            departures.append(item)
        else:
            others.append(item)

    if weather or arrivals or departures:
        aggregate = {
            "id": "airport_hud",
            "type": "flight_airport_hud",
            "sport": "flight",
            "weather": weather.data if weather else None,
            "arrivals": tuple(item.data for item in arrivals),
            "departures": tuple(item.data for item in departures),
        }
        others.append(Content("airport_hud", "flight_airport_hud", "flight", frozen_mapping(aggregate)))

    if selected_mode == "weather":
        return ContentClassification((), tuple(item for item in others if _is_weather(item)))
    if selected_mode == "music":
        return ContentClassification((), tuple(item for item in others if _is_music(item)))
    if selected_mode == "flights":
        return ContentClassification((), tuple(item for item in others if _is_flight(item)))
    if selected_mode == "clock":
        return ContentClassification((), tuple(item for item in others if _is_clock(item)))
    sports = tuple(item for item in others if _is_sports(item))
    if selected_mode == "sports_full":
        return ContentClassification((), sports)
    return ContentClassification(sports, ())


def remap_strip_offset(previous: StripLayout, offset: int, current: StripLayout) -> int:
    """Keep the visible item stable when a strip changes."""
    old_offset = max(0, min(offset, previous.width - 1))
    position = 0
    item_id = ""
    item_delta = 0
    for segment in previous.segments:
        if old_offset < position + segment.width:
            item_id = segment.item_id
            item_delta = old_offset - position
            break
        position += segment.width
    new_position = 0
    for segment in current.segments:
        if segment.item_id == item_id:
            return min(new_position + item_delta, new_position + segment.width - 1)
        new_position += segment.width
    progress = old_offset / previous.width
    return min(int(progress * current.width), current.width - 1)


@dataclass(slots=True)
class _QueuedEvent:
    received_at: float
    data: Mapping[str, Any]


@dataclass(slots=True)
class _ActiveEvent:
    started_at: float
    data: Mapping[str, Any]


class TickerRuntime:
    """Own controller state without device, network, or thread ownership."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float],
        wall_clock: Callable[[], datetime],
        config: RuntimeConfig | None = None,
    ) -> None:
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self.config = config or RuntimeConfig()
        self._running = True
        self._last_contact = monotonic()
        self._disconnected_at: float | None = None
        self._content_expires_at: float | None = None
        self._snapshot: PayloadSnapshot | None = None
        self._classification = ContentClassification((), ())
        self._mode = "sports"
        self._mode_override: str | None = None
        self._mode_requests: deque[ModeRequest] = deque()
        self._update: UpdateRequest | None = None
        self._update_request_pending = False
        self._strip: StripLayout | None = None
        self._strip_key: str | None = None
        self._strip_offset = 0
        self._static_index = 0
        self._static_until = 0.0
        self._active_static: Content | None = None
        self._alerts: deque[_QueuedEvent] = deque()
        self._news: deque[_QueuedEvent] = deque()
        self._seen_alerts: dict[str, float] = {}
        self._seen_news: dict[str, float] = {}
        self._active_alert: _ActiveEvent | None = None
        self._active_news: _ActiveEvent | None = None

    @property
    def running(self) -> bool:
        """Report if the outer loop can continue."""
        return self._running

    @property
    def snapshot(self) -> PayloadSnapshot | None:
        """Return the latest complete payload snapshot."""
        return self._snapshot

    @property
    def classification(self) -> ContentClassification:
        """Return the current content classification."""
        return self._classification

    @property
    def mode(self) -> str:
        """Return the effective mode."""
        return self._mode

    def stop(self) -> None:
        """Stop new frame decisions and clear transient work."""
        self._running = False
        self._alerts.clear()
        self._news.clear()
        self._active_alert = None
        self._active_news = None

    def request_mode(self, mode: str) -> None:
        """Select a mode locally and queue one backend request."""
        selected = _canonical_mode(mode)
        self._mode = selected
        self._mode_override = selected
        self._mode_requests.append(ModeRequest(selected))
        if self._snapshot is not None:
            self._classification = classify_content(self._snapshot.content, self._mode)
        self._clear_strip()

    def take_mode_request(self) -> ModeRequest | None:
        """Return the next requested mode once."""
        return self._mode_requests.popleft() if self._mode_requests else None

    def take_update_request(self) -> UpdateRequest | None:
        """Return the next updater request once."""
        if not self._update_request_pending or self._update is None:
            return None
        self._update_request_pending = False
        return self._update

    def finish_update(self) -> None:
        """Leave the update state after the external updater returns."""
        self._update = None
        self._update_request_pending = False

    def accept_response(self, response: object) -> PayloadSnapshot:
        """Accept one parsed backend response without polling it."""
        return self._accept_response(response, stale=False, stale_for=0.0, expires_in=None)

    def mark_disconnected(self, *, expires_in: float) -> None:
        """Show connection loss while retaining valid content until expiry."""
        if expires_in < 0:
            raise ValueError("Content expiry cannot be negative.")
        now = self._monotonic()
        if self._disconnected_at is None:
            self._disconnected_at = now
        self._content_expires_at = now + expires_in

    def accept_cached_response(
        self,
        response: object,
        *,
        stale_for: float,
        expires_in: float,
    ) -> PayloadSnapshot:
        """Accept cached content after a failed backend poll."""
        if stale_for < 0 or expires_in < 0:
            raise ValueError("Cached content times cannot be negative.")
        snapshot = self._accept_response(response, stale=True, stale_for=stale_for, expires_in=expires_in)
        self.mark_disconnected(expires_in=expires_in)
        return snapshot

    def _accept_response(
        self,
        response: object,
        *,
        stale: bool,
        stale_for: float,
        expires_in: float | None,
    ) -> PayloadSnapshot:
        """Apply fresh or cached parsed data without external I/O."""
        now = self._monotonic()
        if not stale:
            self._last_contact = now
            self._disconnected_at = None
            self._content_expires_at = None
        status = str(_value(response, "status", "active")).lower()
        local = _value(response, "local_config", {})
        global_config = _value(response, "global_config", {})
        source_content = _value(response, "content", ())
        if isinstance(source_content, Mapping):
            source_content = source_content.get("sports", ())
        content = tuple(_content(item) for item in source_content if _mapping(item))
        previous_mode = self._mode
        previous_classification = self._classification
        server_mode = _canonical_mode(str(_value(local, "mode", "sports")))
        if self._mode_override is None:
            self._mode = server_mode
        elif server_mode == self._mode_override:
            self._mode_override = None
        brightness = 0.0 if status == "sleep" else _brightness(_value(local, "brightness", 100))
        scroll_interval = _interval(_value(local, "scroll_speed", 0.05), 0.05)
        snapshot = PayloadSnapshot(
            key=_fingerprint(response, content),
            strip_key=_strip_fingerprint(content, self._mode),
            received_at=now,
            status=status,
            pairing_code=str(_value(response, "pairing_code", _value(response, "code", "------"))),
            mode=self._mode,
            brightness=brightness,
            scroll_interval=scroll_interval,
            inverted=bool(_value(local, "inverted", False)),
            content=content,
            source_received_at=now - stale_for,
            stale=stale,
            cache_expires_at=now + expires_in if expires_in is not None else None,
        )
        self._snapshot = snapshot
        classification = classify_content(content, self._mode)
        self._classification = classification
        if previous_mode != self._mode or previous_classification.static != classification.static:
            self._active_static = None
            self._static_until = 0.0
            self._static_index = 0
        if previous_mode != self._mode or (not classification.scrolling and self._strip is not None):
            self._clear_strip()
        if bool(_value(global_config, "update", False)) and self._update is None:
            version = str(_value(global_config, "update_version", ""))
            self._update = UpdateRequest(version)
            self._update_request_pending = True
        if not stale:
            self._queue_events(_value(response, "alerts", ()), self._alerts, self._seen_alerts, self.config.alert_dedupe_age)
            self._queue_events(_value(response, "news", ()), self._news, self._seen_news, self.config.news_dedupe_age)
        return snapshot

    def install_strip(self, strip_key: str, strip: StripLayout | None) -> bool:
        """Install a completed strip only for the current payload."""
        if self._snapshot is None or strip_key not in {self._snapshot.strip_key, self._snapshot.key}:
            return False
        previous = self._strip
        previous_offset = self._strip_offset
        self._strip = strip
        self._strip_key = self._snapshot.strip_key if strip else None
        if strip is None:
            self._strip_offset = 0
        elif previous is None:
            self._strip_offset = 0
        else:
            self._strip_offset = remap_strip_offset(previous, previous_offset, strip)
        self._static_index = 0
        self._active_static = None
        self._static_until = 0.0
        return True

    def next_frame(self) -> FrameDecision:
        """Advance the state machine and return one render decision."""
        now = self._monotonic()
        wall_time = self._wall_clock()
        if not self._running:
            return self._decision(FrameKind.STOPPED, 0.0, wall_time)
        if self._update is not None:
            return self._decision(FrameKind.UPDATE, self.config.frame_interval, wall_time, update_version=self._update.version)
        snapshot = self._snapshot
        if snapshot is not None and snapshot.status == "pairing":
            return self._decision(FrameKind.PAIRING, self.config.pairing_interval, wall_time, pairing_code=snapshot.pairing_code)
        brightness = snapshot.brightness if snapshot else 1.0
        if snapshot is not None and brightness <= 0.001:
            return self._decision(FrameKind.SLEEP, self.config.sleep_interval, wall_time, brightness=0)
        offline_for = now - self._last_contact
        content_expired = self._disconnected_at is not None and (self._content_expires_at is None or now >= self._content_expires_at)
        cached_expired = snapshot is not None and snapshot.stale and (snapshot.cache_expires_at is None or now >= snapshot.cache_expires_at)
        if content_expired or cached_expired or (snapshot is None and offline_for >= self.config.offline_after):
            return self._decision(FrameKind.OFFLINE, self.config.frame_interval, wall_time, offline_for=offline_for)
        if self._active_alert is not None and now - self._active_alert.started_at >= self.config.alert_duration:
            self._active_alert = None
        self._activate_news(now)
        if self._active_alert is None:
            item = self._pop_fresh(self._alerts, self.config.alert_max_age, now)
            if item is not None:
                self._active_alert = _ActiveEvent(now, item)
        if self._active_alert is not None:
            return self._decision(
                FrameKind.SCORE_ALERT,
                self.config.frame_interval,
                wall_time,
                alert=self._active_alert.data,
                alert_elapsed=now - self._active_alert.started_at,
            )
        if self._active_static is not None and now < self._static_until:
            return self._decision(FrameKind.STATIC, self.config.frame_interval, wall_time, content=self._active_static)
        self._active_static = None
        if self._strip is not None:
            decision = self._scroll_decision(now, wall_time)
            if decision is not None:
                return decision
        static = self._next_static(now)
        if static is not None:
            return self._decision(FrameKind.STATIC, self.config.frame_interval, wall_time, content=static)
        return self._decision(FrameKind.EMPTY, self.config.frame_interval, wall_time)

    def _scroll_decision(self, now: float, wall_time: datetime) -> FrameDecision | None:
        assert self._strip is not None
        offset = self._strip_offset
        self._strip_offset += 1
        if self._strip_offset >= self._strip.width:
            self._strip_offset = 0
            static = self._next_static(now)
            if static is not None:
                return self._decision(FrameKind.STATIC, self.config.frame_interval, wall_time, content=static)
        return self._decision(
            FrameKind.SCROLL,
            self._snapshot.scroll_interval if self._snapshot else self.config.frame_interval,
            wall_time,
            scroll_offset=offset,
        )

    def _next_static(self, now: float) -> Content | None:
        items = self._classification.static
        if not items:
            return None
        item = items[self._static_index % len(items)]
        self._static_index = (self._static_index + 1) % len(items)
        self._active_static = item
        hold = 2.0 if item.type.lower() == "music" else self.config.static_hold
        self._static_until = now + hold
        return item

    def _activate_news(self, now: float) -> None:
        """Start the next fresh news overlay over any base scene."""
        if self._active_news is not None and now - self._active_news.started_at >= self.config.news_duration:
            self._active_news = None
        if self._active_news is None:
            item = self._pop_fresh(self._news, self.config.news_max_age, now)
            if item is not None:
                self._active_news = _ActiveEvent(now, item)

    def _decision(
        self,
        kind: FrameKind,
        interval: float,
        wall_time: datetime,
        *,
        brightness: int | None = None,
        **values: Any,
    ) -> FrameDecision:
        snapshot = self._snapshot
        selected_brightness = brightness
        if selected_brightness is None:
            selected_brightness = round((snapshot.brightness if snapshot else 1.0) * 100)
        return FrameDecision(
            kind=kind,
            interval=interval,
            brightness=max(0, min(100, selected_brightness)),
            inverted=snapshot.inverted if snapshot else False,
            wall_time=wall_time,
            mode=snapshot.mode if snapshot else self._mode,
            payload_key=snapshot.strip_key if snapshot else None,
            news=self._active_news.data if self._active_news else None,
            news_elapsed=self._monotonic() - self._active_news.started_at if self._active_news else None,
            stale=snapshot.stale if snapshot else False,
            stale_for=max(0.0, self._monotonic() - snapshot.source_received_at) if snapshot else 0.0,
            connection_lost=self._disconnected_at is not None,
            disconnected_for=max(0.0, self._monotonic() - self._disconnected_at) if self._disconnected_at is not None else 0.0,
            **values,
        )

    def _clear_strip(self) -> None:
        self._strip = None
        self._strip_key = None
        self._strip_offset = 0
        self._static_index = 0
        self._active_static = None
        self._static_until = 0.0

    def _queue_events(
        self,
        source: object,
        queue: deque[_QueuedEvent],
        seen: dict[str, float],
        dedupe_age: float,
    ) -> None:
        if not isinstance(source, (list, tuple)):
            return
        now = self._monotonic()
        for raw in source:
            identifier, data = _event(raw)
            if identifier and identifier not in seen:
                seen[identifier] = now
                queue.append(_QueuedEvent(now, data))
        cutoff = now - dedupe_age
        for identifier in tuple(seen):
            if seen[identifier] < cutoff:
                del seen[identifier]

    @staticmethod
    def _pop_fresh(queue: deque[_QueuedEvent], max_age: float, now: float) -> Mapping[str, Any] | None:
        while queue:
            event = queue.popleft()
            if now - event.received_at <= max_age:
                return event.data
        return None


def _brightness(raw: object) -> float:
    """Convert a server brightness value to a safe fraction."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 100.0
    return max(0.0, min(1.0, value / 100.0))


def _interval(raw: object, fallback: float) -> float:
    """Read one nonnegative frame interval."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    return value if value >= 0 else fallback


def _canonical_mode(value: object) -> str:
    """Validate one app mode at the runtime boundary."""
    mode = str(value).strip().lower()
    if mode not in CANONICAL_MODES:
        raise ValueError(f"Unsupported ticker mode {mode!r}.")
    return mode


def _is_weather(item: Content) -> bool:
    """Return if one item belongs to weather mode."""
    return item.type.lower() == "weather" or item.sport.lower() == "weather"


def _is_music(item: Content) -> bool:
    """Return if one item belongs to music mode."""
    return item.type.lower() == "music" or item.sport.lower() == "music"


def _is_flight(item: Content) -> bool:
    """Return if one item belongs to flights mode."""
    return item.type.lower() in {"flight_visitor", "flight_airport_hud"}


def _is_clock(item: Content) -> bool:
    """Return if one item belongs to clock mode."""
    return item.sport.lower() == "clock" or item.sport.lower().startswith("clock")


def _is_sports(item: Content) -> bool:
    """Return if one item belongs to either sports mode."""
    return not (_is_weather(item) or _is_music(item) or _is_flight(item) or _is_clock(item))
