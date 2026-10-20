"""Share public provider data without reading personal ticker settings."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import logging
from threading import Lock
from time import monotonic

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.markets import selected_market_groups
from sports_ticker.projections import project_data_v2


PUBLIC_SETTINGS = DisplaySettings(
    active_sports={"stock_tech_ai": True},
    airport_code_iata="EWR", airport_code_icao="KEWR", airport_name="Newark Liberty International",
)


class PublicDemoData:
    """Cache bounded public refreshes through the existing production provider ports."""

    def __init__(self, providers, *, clock=monotonic):
        self._providers = {name: providers[name] for name in ("stock", "flights") if name in providers}
        self._clock = clock
        self._lock = Lock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="public-demo")
        self._pending = set()
        self._attempted = {}
        self._content = {}
        self._updated = {}
        self._healthy = {}
        self._closed = False

    def content(self, mode):
        """Return prepared public facts and start at most one due refresh."""
        name = "flights" if mode == "airports" else mode
        now = self._clock()
        with self._lock:
            if name in self._providers and not self._closed and name not in self._pending and now - self._attempted.get(name, -float("inf")) >= 30:
                self._pending.add(name)
                self._attempted[name] = now
                self._pool.submit(self._refresh, name)
            age = now - self._updated.get(name, -float("inf"))
            records = self._content.get(mode, ()) if age < 600 else ()
            state = "live" if records and self._healthy.get(name) else "stale" if records else "unavailable"
            return {mode: list(records)}, state

    def _fetch(self, name, settings):
        provider = self._providers[name]
        scoped = getattr(provider, "fetch_for_ticker", None)
        return scoped("public-demo", settings) if callable(scoped) else provider.fetch(settings)

    def _refresh(self, name):
        try:
            result = self._fetch(name, PUBLIC_SETTINGS)
            if not result.health.healthy:
                raise RuntimeError("Public provider refresh failed")
            projected = self._project(result)
            content = {}
            if name == "flights":
                boards = projected["airports"]
                content["airports"] = boards
                arrivals = [row for item in boards for row in item["data"].get("arrivals", ()) if row.get("flight_number")]
                arrivals.sort(key=lambda row: (not row.get("is_live", False), bool(row.get("actual_timestamp"))))
                content["flights"] = []
                if arrivals:
                    number = arrivals[0]["flight_number"]
                    tracked = self._fetch(name, replace(PUBLIC_SETTINGS, track_flight_id=number, track_guest_name=number))
                    if tracked.health.healthy:
                        content["flights"] = [item for item in self._project(tracked)["flights"]
                            if "EWR" in (item["data"].get("origin_iata"), item["data"].get("dest_iata"))]
            else:
                groups = {group.id for group in selected_market_groups(PUBLIC_SETTINGS.active_sports)}
                content[name] = [
                    item for item in projected[name]
                    if name != "stock" or item["data"].get("market_group") in groups
                ]
            with self._lock:
                self._content.update(content)
                self._updated[name] = self._clock()
                self._healthy[name] = True
        except Exception as error:
            logging.getLogger(__name__).warning("Public %s refresh failed (%s)", name, type(error).__name__)
            with self._lock:
                self._healthy[name] = False
        finally:
            with self._lock:
                self._pending.discard(name)

    @staticmethod
    def _project(result):
        snapshot = TickerSnapshot("public-demo", 0, result.observed_at, result.content, (), (), PUBLIC_SETTINGS)
        return project_data_v2(snapshot, result.health, {})["content"]

    def close(self):
        """Stop public refresh work before production providers close."""
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=True, cancel_futures=True)
