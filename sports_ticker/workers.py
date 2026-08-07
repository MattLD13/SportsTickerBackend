# Runtime singleton initialization and background worker loops.

import os
import threading
import time
import traceback
from . import fetchers_runtime as _fetchers
from .core import (
    state, tickers, data_lock,
    SPORTS_UPDATE_INTERVAL, _normalize_single_pin, _STOCK_LISTS,
    Tee, tee_instance, purge_stale_tickers,
)
from .fetchers_runtime import TestMode, SportsFetcher, SpotifyFetcher, FlightTracker

# Restore TestMode from persisted state (only active when debug_mode is on)
if state.get('debug_mode'):
    TestMode.configure(
        enabled=state.get('test_mode', False),
        spotify=state.get('test_spotify', False),
        stocks=state.get('test_stocks', False),
        sports_date=state.get('test_sports_date', False),
        flights=state.get('test_flights', False),
        custom_date=state.get('custom_date'),
    )
    if tee_instance is not None:
        Tee.verbose_debug = True


def sync_test_mode_from_state():
    TestMode.configure(
        enabled=state.get('test_mode', False),
        spotify=state.get('test_spotify', False),
        stocks=state.get('test_stocks', False),
        sports_date=state.get('test_sports_date', False),
        flights=state.get('test_flights', False),
        custom_date=state.get('custom_date'),
    )
    if tee_instance is not None:
        Tee.verbose_debug = state.get('debug_mode', False)

# Initialize Global Fetcher
fetcher = SportsFetcher(
    initial_city=state['weather_city'], 
    initial_lat=state['weather_lat'], 
    initial_lon=state['weather_lon']
)

# Initialize Spotify Fetcher
spotify_fetcher = SpotifyFetcher()
_spotify_thread_started = False

# Initialize Flight Tracker
# FlightTracker itself has no dependency on airportsdata — that package is only
# used by lookup_and_auto_fill_airport() for code validation. Always create the
# tracker so that flights/flight_tracker modes work even without airportsdata.
try:
    flight_tracker = FlightTracker()
    flight_tracker.track_flight_id = state.get('track_flight_id', '')
    flight_tracker.track_guest_name = state.get('track_guest_name', '')
    flight_tracker.airport_code_icao = state.get('airport_code_icao', 'KEWR')
    flight_tracker.airport_code_iata = state.get('airport_code_iata', 'EWR')
    flight_tracker.airport_name = state.get('airport_name', 'Newark')
    flight_tracker.airline_filter = ''  # Force empty - support all airlines
except Exception as e:
    print(f"⚠️ FlightTracker init failed: {e}")
    flight_tracker = None

_fetchers._sports_modes.spotify_fetcher = spotify_fetcher
_fetchers._sports_modes.flight_tracker = flight_tracker

# ── Section K: Worker Threads ──
_refresh_event = threading.Event()
_refresh_state_lock = threading.Lock()
_refresh_requested = False
_refresh_reason = 'startup'
_refresh_thread_started = False
_background_workers_started = False


def _threading_excepthook(args):
    try:
        thread_name = getattr(args.thread, 'name', 'unknown-thread')
        print(f"[THREAD-CRASH] {thread_name}: {args.exc_type.__name__}: {args.exc_value}")
        stack = ''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        if stack.strip():
            print(stack.rstrip())
    except Exception:
        pass


threading.excepthook = _threading_excepthook


def refresh_worker():
    global _refresh_requested
    while True:
        _refresh_event.wait()
        while True:
            with _refresh_state_lock:
                if not _refresh_requested:
                    _refresh_event.clear()
                    break
                _refresh_requested = False
                reason = _refresh_reason

            started = time.time()
            try:
                print(f"[DEBUG][REFRESH] start reason={reason}")
                fetcher.update_current_games()
                print(f"[DEBUG][REFRESH] done reason={reason} took={time.time() - started:.2f}s")
            except Exception as e:
                print(f"[REFRESH] error reason={reason}: {e}")


def _ensure_refresh_thread_running():
    global _refresh_thread_started
    if _refresh_thread_started:
        return
    with _refresh_state_lock:
        if _refresh_thread_started:
            return
        threading.Thread(target=refresh_worker, name='refresh_worker', daemon=True).start()
        _refresh_thread_started = True


def request_refresh(reason='manual'):
    global _refresh_requested, _refresh_reason
    _ensure_refresh_thread_running()
    with _refresh_state_lock:
        _refresh_requested = True
        _refresh_reason = str(reason or 'manual')
    _refresh_event.set()


def _any_ticker_needs(*modes):
    """Return True if the global state or any paired ticker is in one of the given modes."""
    mode_set = set(modes)
    with data_lock:
        # Pinned game override: force sports_full behavior whenever any pin exists.
        if 'sports_full' in mode_set:
            for t in tickers.values():
                s = t.get('settings', {})
                if s.get('pinned_game'):
                    return True
                t_pins = s.get('pinned_games', [])
                if isinstance(t_pins, list) and any(str(p).strip() for p in t_pins):
                    return True

        # Masters pin should keep masters refreshes alive even if ticker mode
        # is currently something else (e.g. clock).
        if 'masters' in mode_set:
            for t in tickers.values():
                s = t.get('settings', {})
                t_single_pin, t_pin_list = _normalize_single_pin(
                    pinned_game=s.get('pinned_game'),
                    pinned_games=s.get('pinned_games', []),
                )
                for _pin in t_pin_list:
                    pin_norm = str(_pin).strip().lower()
                    if not pin_norm:
                        continue
                    if ':' in pin_norm:
                        if pin_norm.split(':', 1)[0] == 'masters':
                            return True
                    elif pin_norm.startswith('masters'):
                        return True

        if state.get('mode') in mode_set:
            return True
        for t in tickers.values():
            if t.get('paired') and t.get('settings', {}).get('mode') in mode_set:
                return True
    return False


def sports_worker():
    try: fetcher.fetch_all_teams()
    except Exception as e: print(f"Team fetch error: {e}")

    while True:
        try:
            start_time = time.time()
            if _any_ticker_needs('sports', 'live', 'my_teams', 'sports_full', 'soccer_full', 'masters'):
                try:
                    request_refresh('sports_worker')
                except Exception as e:
                    print(f"Sports Worker Error: {e}")
            execution_time = time.time() - start_time
            time.sleep(max(0, SPORTS_UPDATE_INTERVAL - execution_time))
        except Exception as e:
            print(f"Sports Worker Fatal Error (recovering): {e}")
            time.sleep(SPORTS_UPDATE_INTERVAL)

def stocks_worker():
    _last_active_key = None
    while True:
        try:
            if _any_ticker_needs('stocks'):
                with data_lock:
                    active_sports = state['active_sports']
                active_key = frozenset(k for k, v in active_sports.items() if k.startswith('stock_') and v)
                if active_key != _last_active_key:
                    _last_active_key = active_key
                    request_refresh('stocks_sector_change')  # Immediate buffer rebuild on sector change
                # Fetch all sectors always so switching is instant; /data and /api/state filter by active_sports
                if fetcher.stocks.update_market_data(list(_STOCK_LISTS.keys())):
                    request_refresh('stocks_market_update')  # Rebuild only when fresh data arrives
        except Exception as e:
            print(f"Stock worker error: {e}")
        time.sleep(1)

def music_worker():
    last_signature = None
    while True:
        try:
            if _any_ticker_needs('music'):
                try:
                    # Only ask for a rebuild when the track or play state
                    # actually changes. This fired unconditionally every second,
                    # and a refresh rebuilds every mode in use — so a music-mode
                    # ticker drove the full sports fetch at 1Hz. The stocks
                    # worker already follows this pattern.
                    signature = _music_signature()
                    if signature != last_signature:
                        last_signature = signature
                        request_refresh('music_worker')
                except Exception as e:
                    print(f"Music Worker Error: {e}")
        except Exception as e:
            print(f"Music worker error: {e}")
        time.sleep(1)


_MUSIC_SIG_UNAVAILABLE = ('__unavailable__',)


def _music_signature():
    """Track identity and play state, as a comparable value.

    Deliberately excludes 'status' and situation['progress'] — those carry the
    elapsed time and change every second, which would make every comparison
    differ and rebuild nothing but the storm this is meant to stop.

    A failure returns a constant rather than a fresh value, so a transient
    Spotify error reads as "no change" instead of triggering a refresh per
    second.
    """
    try:
        item = fetcher.get_music_object(require_enabled=False)
    except Exception:
        return _MUSIC_SIG_UNAVAILABLE
    if not isinstance(item, dict):
        return ('__nothing__',)
    sit = item.get('situation') or {}
    return (item.get('id'), item.get('home_abbr'), item.get('away_abbr'),
            bool(sit.get('is_playing')))

HOUSEKEEPING_INTERVAL = 900   # 15 minutes


def _resource_usage_line():
    """One-line process health snapshot (Linux /proc; degrades elsewhere)."""
    rss_txt = 'n/a'
    fd_txt = 'n/a'
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    rss_txt = f"{int(line.split()[1]) / 1024:.1f}MB"
                    break
    except Exception:
        pass
    try:
        fd_txt = str(len(os.listdir('/proc/self/fd')))
    except Exception:
        pass
    return (f"[HEALTH] rss={rss_txt} threads={threading.active_count()} "
            f"fds={fd_txt} tickers={len(tickers)}")


def housekeeping_worker():
    """Periodic maintenance: purge stale tickers, log resource usage.

    purge_stale_tickers used to run only at startup, so ticker records
    auto-created by unknown /data?id= callers accumulated in memory and on
    disk for as long as the process lived.
    """
    while True:
        time.sleep(HOUSEKEEPING_INTERVAL)
        try:
            purge_stale_tickers()
        except Exception as e:
            print(f"Housekeeping purge error: {e}")
        try:
            print(_resource_usage_line())
        except Exception:
            pass


def transactions_worker():
    """Poll the MLB transaction feed for trades and signings.

    MLB, the NFL, and the NHL are covered. The NBA publishes nothing, so it
    reaches the banner through POST /api/news. See docs/news-banner.md.

    Trades land in bursts around a deadline and are quiet for weeks either
    side, so this runs on a slow loop. Nothing on screen depends on catching
    one within seconds.
    """
    from .fetchers.transactions import (
        fetch_mlb_transactions, fetch_nfl_transactions, fetch_nhl_transactions,
    )
    from .services.news_alerts import news_alerts, pick_team_color

    def _color(league, abbr):
        try:
            return pick_team_color(fetcher.lookup_team_info_from_cache(league, abbr))
        except Exception:
            return '#8B93A3'

    while True:
        for league, fetch in (('MLB', fetch_mlb_transactions),
                              ('NFL', fetch_nfl_transactions),
                              ('NHL', fetch_nhl_transactions)):
            try:
                added = news_alerts.add_many(fetch(days_back=2, lookup_color=_color))
                if added:
                    print(f"[TRANSACTIONS] {len(added)} new {league} item(s)")
            except Exception as e:
                print(f"Transactions worker error ({league}): {e}")
        time.sleep(600)


def start_background_workers():
    """Start all background worker threads. Called once at server startup."""
    global _background_workers_started
    with _refresh_state_lock:
        if _background_workers_started:
            return
        _background_workers_started = True

    workers = [
        ('sports_worker',  sports_worker),
        ('stocks_worker',  stocks_worker),
        ('music_worker',   music_worker),
        ('flights_worker', flights_worker),
        ('transactions_worker', transactions_worker),
        ('housekeeping_worker', housekeeping_worker),
    ]
    for name, target in workers:
        threading.Thread(target=target, name=name, daemon=True).start()
        print(f"  Started worker: {name}")

    spotify_fetcher.start()
    purge_stale_tickers()
    request_refresh('startup')


def flights_worker():
    if not flight_tracker:
        if TestMode.is_enabled('flights'):
            print("[DEBUG] flights_worker: No flight_tracker available")
        return
    if TestMode.is_enabled('flights'):
        print("[DEBUG] flights_worker: Starting")
    while True:
        start_time = time.time()
        try:
            forced = getattr(flight_tracker, '_force_refresh', False)
            if forced:
                flight_tracker._force_refresh = False
                if TestMode.is_enabled('flights'):
                    print("[DEBUG] flights_worker: Force refresh triggered")

            did_fetch = False
            
            # 1. Airport Data: Fetch if in flights mode or forced
            if _any_ticker_needs('flights') or forced:
                if flight_tracker.airport_code_iata:
                    if forced or time.time() - flight_tracker.last_airport_fetch >= 30:
                        flight_tracker.fetch_airport_activity()
                        flight_tracker.last_airport_fetch = time.time()
                        did_fetch = True

            # 2. Visitor Tracking: Fetch if ID exists (Persistent) or mode is explicitly flight_tracker
            # This ensures we keep repolling even if mode is turned 'off' (switched to sports)
            if flight_tracker.track_flight_id:
                if forced or time.time() - flight_tracker.last_visitor_fetch >= 30:
                    flight_tracker.fetch_visitor_tracking()
                    flight_tracker.last_visitor_fetch = time.time()
                    did_fetch = True

            if did_fetch or forced:
                try: request_refresh('flights_worker')
                except Exception: pass
        except Exception as e:
            print(f"Flight worker error: {e}")

        execution_time = time.time() - start_time
        flight_tracker.wake_event.wait(timeout=max(0, 5 - execution_time))
        flight_tracker.wake_event.clear()
