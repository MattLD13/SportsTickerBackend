#!/usr/bin/env python3
"""Probe every upstream feed and every worker fetch path, and report the cost of each.

The report gives the facts that decide how workers are split and how often they
poll: latency, payload size, cache headers, how often data changes, Fastcast
push activity, and the time and memory of each worker's production fetch.

Examples:
  python tools/diagnostics/upstream_probe.py --all
  python tools/diagnostics/upstream_probe.py --http --samples 5 --interval 5
  python tools/diagnostics/upstream_probe.py --fastcast 120 --leagues nfl,nba
  python tools/diagnostics/upstream_probe.py --workers espn,racing

The tool sends only read requests. It writes its report under
previews/upstream-probe/ and prints no credentials. Behind a TLS-inspecting
proxy, pass --ca-bundle with the proxy CA bundle.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [os.path.join(str(ROOT), name) for name in ("shared", "server", "six", "")]
USER_AGENT = "SportsTickerBackend/8"
REPORT_DIRECTORY = ROOT / "previews" / "upstream-probe"
FINNHUB_KEY_NAMES = ("FINNHUB_API_KEY", "FINNHUB_KEY_1", "FINNHUB_KEY_2", "FINNHUB_KEY_3", "FINNHUB_KEY_4", "FINNHUB_KEY_5")
CACHE_HEADERS = ("etag", "last-modified", "cache-control", "age", "expires", "retry-after")


@dataclass(frozen=True)
class Endpoint:
    """Describe one upstream request that a worker part makes."""

    worker: str
    part: str
    name: str
    url: str
    accept: str = "application/json"
    secret_query: tuple[str, tuple[str, ...]] | None = None


@dataclass
class Sample:
    """Record one request to one endpoint."""

    status: int | None
    milliseconds: float
    wire_bytes: int
    body_bytes: int
    body_hash: str | None
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def use_ca_bundle(path: Path | None) -> None:
    """Point the production TLS context at another CA bundle for this process only."""

    if path is None:
        return
    import certifi

    bundle = str(path)
    certifi.where = lambda: bundle


def endpoint_catalog(now: datetime | None = None) -> list[Endpoint]:
    """Return each upstream request the workers make, built from production constants."""

    from ticker.shared.leagues import ESPN_SCOREBOARD_PATHS, TEAM_CATALOG_PATHS, league_for
    from ticker.server.providers.espn import _MLB_SCHEDULE_URL
    from ticker.server.providers.espn_college import _NCAA_COLLEGE_FOOTBALL_RANKING_URLS
    from ticker.server.providers.espn_fastcast import _DISCOVERY_URL
    from ticker.server.providers.fotmob import _MATCHES_URL
    from ticker.server.providers.golf_source import ESPN_GOLF_URL
    from ticker.server.providers.news_transactions import _tracker_url
    from ticker.server.providers.nhl_live import _SCORE_URL
    from ticker.server.providers.racing_endurance import _WEC
    from ticker.server.providers.racing_live import _F1_ESPN_URL, _INDYCAR_BLOB_BASE, _INDYCAR_ESPN_URL
    from ticker.server.providers.stock_source import FINNHUB_QUOTE_URL
    from ticker.server.providers.weather import _AIR_QUALITY_URL, _FORECAST_URL, _NWS_POINTS_URL
    from ticker.server.providers.weather_location import _GEOCODING_URL

    current = now or datetime.now(timezone.utc)
    espn = "https://site.web.api.espn.com/apis/site/v2/sports"
    endpoints: list[Endpoint] = []
    for league, path in ESPN_SCOREBOARD_PATHS.items():
        query = urlencode(dict(league_for(league).scoreboard_query))
        url = f"{espn}/{path}/scoreboard" + (f"?{query}" if query else "")
        endpoints.append(Endpoint("espn", "Scoreboards", f"{league} scoreboard", url))
    endpoints += [
        Endpoint("espn", "Live push", "Fastcast host lookup", _DISCOVERY_URL),
        Endpoint("espn", "MLB live", "MLB schedule", _MLB_SCHEDULE_URL.format(current.strftime("%Y-%m-%d"))),
        Endpoint("espn", "NHL live", "NHL scores", _SCORE_URL),
    ]
    for league, url in _NCAA_COLLEGE_FOOTBALL_RANKING_URLS.items():
        endpoints.append(Endpoint("espn", "College", f"{league} rankings", url))
    endpoints += [
        Endpoint("fotmob", "Soccer scores", "FotMob matches", f"{_MATCHES_URL}?date={current:%Y%m%d}&timezone=UTC&ccode3=USA"),
        Endpoint("golf", "Leaderboards", "PGA scoreboard", ESPN_GOLF_URL),
        Endpoint("racing", "F1", "F1 scoreboard", _F1_ESPN_URL),
        Endpoint("racing", "F1", "Jolpica F1 season", f"https://api.jolpi.ca/ergast/f1/{current.year}.json"),
        Endpoint("racing", "IndyCar", "IndyCar scoreboard", _INDYCAR_ESPN_URL),
        Endpoint("racing", "IndyCar", "IndyCar timing feed", f"{_INDYCAR_BLOB_BASE}/timingscoring-ris.json"),
        Endpoint("racing", "IndyCar", "IndyCar drivers feed", f"{_INDYCAR_BLOB_BASE}/driversfeed.json"),
        Endpoint("racing", "NASCAR Cup", "NASCAR race list", f"https://cf.nascar.com/cacher/{current.year}/race_list_basic.json"),
        Endpoint("racing", "WEC", "Griiip season calendar", f"{_WEC}/meta/series/10/active-season-calendar"),
    ]
    for league, path in TEAM_CATALOG_PATHS.items():
        endpoints.append(Endpoint("news", "Headlines", f"{league} news", f"{espn}/{path}/news"))
    endpoints += [
        Endpoint("news", "Trades", "NHL trade tracker", _tracker_url(current), accept="text/html"),
        Endpoint("news", "Team catalog", "NFL teams", f"{espn}/football/nfl/teams"),
        Endpoint("weather", "U.S. forecast", "NWS points", f"{_NWS_POINTS_URL}/40.7128,-74.006", accept="application/geo+json"),
        Endpoint("weather", "World forecast", "Open-Meteo forecast",
                 f"{_FORECAST_URL}?latitude=40.7128&longitude=-74.006&current=temperature_2m&daily=temperature_2m_max&timezone=auto"),
        Endpoint("weather", "Air quality", "Open-Meteo air quality", f"{_AIR_QUALITY_URL}?latitude=40.7128&longitude=-74.006&current=us_aqi"),
        Endpoint("core", "Place lookup", "Open-Meteo geocoding", f"{_GEOCODING_URL}?name=Boston&count=1"),
        Endpoint("stock", "Quotes and charts", "Finnhub quote", f"{FINNHUB_QUOTE_URL}?symbol=AAPL",
                 secret_query=("token", FINNHUB_KEY_NAMES)),
        Endpoint("flights", "Airline logos", "Google site icon", "https://www.google.com/s2/favicons?domain=united.com&sz=64", accept="image/*"),
    ]
    return endpoints


def _secret(names: tuple[str, ...]) -> str | None:
    return next((value for name in names if (value := os.environ.get(name, "").strip())), None)


def fetch_once(endpoint: Endpoint, *, timeout: float, opener: Callable = urlopen, conditional: dict[str, str] | None = None) -> Sample:
    """Send one GET request and measure it. A secret query value never enters the sample."""

    from ticker.server.tls import verified_https_context

    url = endpoint.url
    if endpoint.secret_query is not None:
        parameter, names = endpoint.secret_query
        url += ("&" if "?" in url else "?") + urlencode({parameter: _secret(names) or ""})
    headers = {"Accept": endpoint.accept, "Accept-Encoding": "gzip", "User-Agent": USER_AGENT, **(conditional or {})}
    started = time.perf_counter()
    try:
        with opener(Request(url, headers=headers), timeout=timeout, context=verified_https_context()) as response:
            raw = response.read()
            status = response.status
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as error:
        raw = error.read() if error.fp is not None else b""
        status = error.code
        response_headers = {key.lower(): value for key, value in (error.headers or {}).items()}
    except (URLError, OSError, ValueError) as error:
        return Sample(None, (time.perf_counter() - started) * 1000, 0, 0, None, error=_clean_error(error))
    milliseconds = (time.perf_counter() - started) * 1000
    body = gzip.decompress(raw) if response_headers.get("content-encoding") == "gzip" and raw else raw
    kept = {key: value for key, value in response_headers.items() if key in CACHE_HEADERS or "ratelimit" in key}
    return Sample(status, milliseconds, len(raw), len(body), hashlib.sha256(body).hexdigest()[:16] if body else None, kept)


def _clean_error(error: BaseException) -> str:
    text = str(getattr(error, "reason", None) or error) or type(error).__name__
    for name in FINNHUB_KEY_NAMES:
        if value := os.environ.get(name, "").strip():
            text = text.replace(value, "***")
    return text[:200]


def probe_endpoint(endpoint: Endpoint, *, samples: int, interval: float, timeout: float,
                   opener: Callable = urlopen, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Sample one endpoint, test conditional requests, and summarize the results."""

    if endpoint.secret_query is not None and _secret(endpoint.secret_query[1]) is None:
        return {**_identity(endpoint), "skipped": f"set one of {', '.join(endpoint.secret_query[1])}"}
    taken: list[Sample] = []
    for index in range(samples):
        if index:
            sleep(interval)
        taken.append(fetch_once(endpoint, timeout=timeout, opener=opener))
    summary = summarize(taken)
    last = taken[-1]
    validators = {}
    if "etag" in last.headers:
        validators["If-None-Match"] = last.headers["etag"]
    if "last-modified" in last.headers:
        validators["If-Modified-Since"] = last.headers["last-modified"]
    if validators and last.status == 200:
        check = fetch_once(endpoint, timeout=timeout, opener=opener, conditional=validators)
        summary["conditional_status"] = check.status
    summary["cache_headers"] = last.headers
    return {**_identity(endpoint), **summary}


def _identity(endpoint: Endpoint) -> dict[str, str]:
    return {"worker": endpoint.worker, "part": endpoint.part, "name": endpoint.name, "url": endpoint.url}


def summarize(samples: list[Sample]) -> dict[str, Any]:
    """Reduce raw samples to the figures that size a polling worker."""

    good = [sample for sample in samples if sample.status is not None and 200 <= sample.status < 400]
    times = sorted(sample.milliseconds for sample in good)
    hashes = [sample.body_hash for sample in good if sample.body_hash]
    return {
        "samples": len(samples),
        "ok": len(good),
        "statuses": sorted({sample.status for sample in samples if sample.status is not None}),
        "errors": sorted({sample.error for sample in samples if sample.error}),
        "median_ms": round(statistics.median(times), 1) if times else None,
        "max_ms": round(times[-1], 1) if times else None,
        "wire_kb": round(statistics.median(sample.wire_bytes for sample in good) / 1024, 1) if good else None,
        "body_kb": round(statistics.median(sample.body_bytes for sample in good) / 1024, 1) if good else None,
        "changes": max(0, len(dict.fromkeys(hashes)) - 1),
    }


def probe_fastcast(leagues: list[str], seconds: float, *, clock: Callable[[], float] = time.monotonic,
                   sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Run the production Fastcast client and count pushed changes for each league."""

    from ticker.shared.leagues import ESPN_SCOREBOARD_PATHS
    from ticker.server.providers.espn_fastcast import EspnFastcastSource, fastcast_topic

    espn = "https://site.web.api.espn.com/apis/site/v2/sports"
    topics = {league: fastcast_topic(f"{espn}/{ESPN_SCOREBOARD_PATHS[league]}/scoreboard") for league in leagues}
    source = EspnFastcastSource(topics)
    started = clock()
    first_active: dict[str, float] = {}
    changes = {league: 0 for league in leagues}
    errors: dict[str, str] = {}
    last_versions: dict[str, str] = {}
    source.start()
    try:
        while clock() - started < seconds:
            versions = source.versions()
            for league in leagues:
                if source.active(league) and league not in first_active:
                    first_active[league] = round(clock() - started, 1)
                if league in versions and last_versions.get(league) not in (None, versions[league]):
                    changes[league] += 1
                if error := source.error(league):
                    errors[league] = error
            last_versions = dict(versions)
            sleep(1.0)
    finally:
        source.close()
    return {
        "seconds": seconds,
        "topics": topics,
        "seconds_until_active": first_active,
        "pushed_changes": changes,
        "errors": errors,
    }


def probe_worker(name: str, *, timeout: float, ca_bundle: Path | None, settle: float = 15.0) -> dict[str, Any]:
    """Run one worker's production fetch in its own process, like the deployed split."""

    command = [sys.executable, str(Path(__file__).resolve()), "--worker-child", name, "--settle", str(settle)]
    if ca_bundle is not None:
        command += ["--ca-bundle", str(ca_bundle)]
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return {"worker": name, "error": f"no answer within {timeout:.0f} s"}
    elapsed = round(time.perf_counter() - started, 2)
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if completed.returncode != 0 or not lines:
        tail = (completed.stderr.strip().splitlines() or ["no output"])[-1]
        return {"worker": name, "error": f"exit {completed.returncode}: {_clean_error(RuntimeError(tail))}", "process_seconds": elapsed}
    return {**json.loads(lines[-1]), "process_seconds": elapsed}


WORKER_MODES = {"weather": "weather", "stock": "stock", "flights": "flights", "music": "music", "clock": "clock"}


def representative_settings(worker: str):
    """Return settings for the worker's own mode, with every league enabled and teams followed."""

    from ticker.shared.domain import DisplaySettings

    return DisplaySettings(
        mode=WORKER_MODES.get(worker, "sports"),
        my_teams=("nfl:nyg", "nba:nyk", "nhl:nyr", "mlb:nyy", "soccer_epl:ars"),
        custom_stock_symbols=("AAPL", "MSFT", "NVDA"),
        track_flight_id=os.environ.get("TICKER_PROBE_FLIGHT", "UA1"),
    )


def worker_child(name: str, settle: float = 15.0) -> dict[str, Any]:
    """Create one production worker, fetch until it has data, and report time, size, and memory.

    Some workers refresh in a background thread and answer from a cache, so the
    first fetch can be empty. The probe asks again once a second for up to
    `settle` seconds and records when the first data arrived.
    """

    import resource

    from ticker.server.providers.factory import create_provider
    from ticker.server.providers.normalization import normalize_provider_result

    if name == "music":
        return {"worker": name, "skipped": "needs a linked Spotify account and the fleet database"}
    settings = representative_settings(name)
    created = time.perf_counter()
    provider = create_provider(name)
    setup_seconds = time.perf_counter() - created
    def fetch():
        started = time.perf_counter()
        # The deployed worker normalizes each result the same way before it answers core.
        value = normalize_provider_result(provider.fetch(settings), settings, provider=name)
        return time.perf_counter() - started, value

    first_request = time.perf_counter()
    try:
        cold, result = fetch()
        data_after = 0.0 if _has_records(result) else None
        while data_after is None and time.perf_counter() - first_request < settle:
            time.sleep(1.0)
            _, result = fetch()
            if _has_records(result):
                data_after = time.perf_counter() - first_request
        warm, _ = fetch()
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    records = (*result.content, *result.alerts, *result.news)
    health = result.health
    encoded = json.dumps([dict(getattr(item, "data", item)) for item in records], default=str)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "worker": name,
        "setup_seconds": round(setup_seconds, 2),
        "cold_seconds": round(cold, 2),
        "warm_seconds": round(warm, 2),
        "seconds_until_data": None if data_after is None else round(data_after, 1),
        "items": len(records),
        "result_kb": round(len(encoded.encode()) / 1024, 1),
        "healthy": health.healthy,
        "health_error": health.error,
        "peak_memory_mb": round(usage.ru_maxrss / 1024, 1),
        "cpu_seconds": round(usage.ru_utime + usage.ru_stime, 2),
    }


def _has_records(result) -> bool:
    return bool(result.content or result.alerts or result.news)


def print_report(report: dict[str, Any]) -> None:
    """Print each section as an aligned table."""

    if report.get("http"):
        print("\nUPSTREAM ENDPOINTS")
        print(f"{'worker':8} {'part':18} {'endpoint':26} {'ok':>5} {'median':>8} {'max':>8} {'wire KB':>8} {'body KB':>8} {'chg':>4}  cache")
        for row in report["http"]:
            if "skipped" in row:
                print(f"{row['worker']:8} {row['part'][:18]:18} {row['name'][:26]:26}  skipped: {row['skipped']}")
                continue
            cache = ",".join(key for key in row.get("cache_headers", {}) if key in ("etag", "last-modified", "cache-control"))
            if "conditional_status" in row:
                cache += f" ({row['conditional_status']} on repeat)"
            failure = f"  {row['statuses']} {'; '.join(row['errors'])[:60]}" if row["ok"] < row["samples"] else ""
            print(f"{row['worker']:8} {row['part'][:18]:18} {row['name'][:26]:26} {row['ok']:>2}/{row['samples']:<2} "
                  f"{_num(row['median_ms']):>8} {_num(row['max_ms']):>8} {_num(row['wire_kb']):>8} {_num(row['body_kb']):>8} "
                  f"{row['changes']:>4}  {cache}{failure}")
    if report.get("fastcast"):
        fast = report["fastcast"]
        print(f"\nFASTCAST ({fast['seconds']:.0f} s)")
        for league in fast["topics"]:
            active = fast["seconds_until_active"].get(league)
            state = f"active after {active} s" if active is not None else "never active"
            print(f"  {league:16} {state:22} pushed changes: {fast['pushed_changes'][league]:<4} {fast['errors'].get(league, '')}")
    if report.get("workers"):
        print("\nWORKERS (production fetch, one process each)")
        print(f"{'worker':8} {'cold s':>7} {'warm s':>7} {'data s':>7} {'items':>6} {'result KB':>10} {'memory MB':>10} {'cpu s':>6}  health")
        for row in report["workers"]:
            if "skipped" in row or "error" in row:
                print(f"{row['worker']:8}  {row.get('skipped') or row.get('error')}")
                continue
            health = "ok" if row["healthy"] else f"unhealthy: {str(row['health_error'])[:70]}"
            print(f"{row['worker']:8} {row['cold_seconds']:>7} {row['warm_seconds']:>7} {_num(row['seconds_until_data']):>7} {row['items']:>6} {row['result_kb']:>10} "
                  f"{row['peak_memory_mb']:>10} {row['cpu_seconds']:>6}  {health}")


def _num(value: object) -> str:
    return "-" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    from ticker.server.contract import WORKERS as PROVIDERS

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="Run the HTTP, Fastcast, and worker probes.")
    parser.add_argument("--http", action="store_true", help="Sample every upstream endpoint.")
    parser.add_argument("--fastcast", type=float, metavar="SECONDS", help="Listen to ESPN Fastcast for this long.")
    parser.add_argument("--workers", metavar="NAMES", help="Comma-separated workers to run, or 'all'.")
    parser.add_argument("--leagues", default="nfl,nba,nhl,mlb", help="Fastcast leagues to subscribe.")
    parser.add_argument("--samples", type=int, default=3, help="Requests per endpoint.")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between requests to one endpoint.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Seconds before one request fails.")
    parser.add_argument("--worker-timeout", type=float, default=180.0, help="Seconds before one worker probe fails.")
    parser.add_argument("--settle", type=float, default=15.0, help="Seconds a worker may take to produce its first data.")
    parser.add_argument("--ca-bundle", type=Path, help="Trust this CA bundle instead of Certifi, for TLS-inspecting proxies.")
    parser.add_argument("--worker-child", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help="Write the JSON report here.")
    args = parser.parse_args(argv)
    use_ca_bundle(args.ca_bundle)

    if args.worker_child:
        print(json.dumps(worker_child(args.worker_child, args.settle)))
        return 0
    if not (args.all or args.http or args.fastcast or args.workers):
        parser.error("choose --all, --http, --fastcast, or --workers")

    report: dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if args.all or args.http:
        report["http"] = [
            probe_endpoint(endpoint, samples=args.samples, interval=args.interval, timeout=args.timeout)
            for endpoint in endpoint_catalog()
        ]
    if args.all or args.fastcast:
        report["fastcast"] = probe_fastcast([value.strip() for value in args.leagues.split(",") if value.strip()], args.fastcast or 60.0)
    if args.all or args.workers:
        names = PROVIDERS if args.all or args.workers == "all" else tuple(value.strip() for value in args.workers.split(","))
        report["workers"] = [probe_worker(name, timeout=args.worker_timeout, ca_bundle=args.ca_bundle, settle=args.settle) for name in names]

    output = args.output or REPORT_DIRECTORY / f"{report['started_at'].replace(':', '')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print_report(report)
    print(f"\nReport: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
