import gzip
from datetime import datetime, timezone
from email.message import Message
from urllib.error import URLError

from tools.diagnostics.upstream_probe import Endpoint, Sample, endpoint_catalog, probe_endpoint, summarize


class FakeResponse:
    def __init__(self, status, body, headers):
        self.status = status
        self._body = body
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_catalog_covers_each_polling_worker_from_production_constants():
    from ticker.shared.leagues import ESPN_SCOREBOARD_PATHS

    endpoints = endpoint_catalog(datetime(2026, 10, 29, tzinfo=timezone.utc))
    workers = {endpoint.worker for endpoint in endpoints}

    assert workers == {"core", "espn", "fotmob", "golf", "racing", "news", "weather", "stock", "flights"}
    scoreboards = [endpoint for endpoint in endpoints if endpoint.part == "Scoreboards"]
    assert len(scoreboards) == len(ESPN_SCOREBOARD_PATHS)
    assert all(endpoint.url.startswith("https://") for endpoint in endpoints)
    assert len({endpoint.name for endpoint in endpoints}) == len(endpoints)
    fotmob = next(endpoint for endpoint in endpoints if endpoint.worker == "fotmob")
    assert "date=20261029" in fotmob.url


def test_probe_measures_gzip_bodies_and_checks_conditional_requests():
    body = b'{"events": []}' * 40
    requests = []

    def opener(request, *, timeout, context):
        requests.append(dict(request.header_items()))
        if request.get_header("If-none-match") == '"v1"':
            return FakeResponse(304, b"", {"ETag": '"v1"'})
        return FakeResponse(200, gzip.compress(body), {"Content-Encoding": "gzip", "ETag": '"v1"', "Set-Cookie": "drop"})

    endpoint = Endpoint("espn", "Scoreboards", "nfl scoreboard", "https://example.test/nfl")
    result = probe_endpoint(endpoint, samples=2, interval=5, timeout=1, opener=opener, sleep=lambda _seconds: None)

    assert len(requests) == 3
    assert requests[0]["Accept-encoding"] == "gzip"
    assert result["ok"] == 2
    assert result["statuses"] == [200]
    assert result["body_kb"] == round(len(body) / 1024, 1)
    assert result["wire_kb"] < result["body_kb"]
    assert result["changes"] == 0
    assert result["conditional_status"] == 304
    assert result["cache_headers"] == {"etag": '"v1"'}


def test_probe_skips_keyed_endpoint_without_a_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    for index in range(1, 6):
        monkeypatch.delenv(f"FINNHUB_KEY_{index}", raising=False)

    def opener(*_args, **_kwargs):
        raise AssertionError("no request without a key")

    endpoint = Endpoint("stock", "Quotes", "Finnhub quote", "https://example.test/quote?symbol=AAPL",
                        secret_query=("token", ("FINNHUB_API_KEY",)))

    result = probe_endpoint(endpoint, samples=1, interval=0, timeout=1, opener=opener)

    assert result["skipped"] == "set one of FINNHUB_API_KEY"


def test_probe_keeps_the_key_out_of_urls_and_errors(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "secret-key-value")
    seen = []

    def opener(request, *, timeout, context):
        seen.append(request.full_url)
        raise URLError(f"refused {request.full_url}")

    endpoint = Endpoint("stock", "Quotes", "Finnhub quote", "https://example.test/quote?symbol=AAPL",
                        secret_query=("token", ("FINNHUB_API_KEY",)))

    result = probe_endpoint(endpoint, samples=1, interval=0, timeout=1, opener=opener)

    assert seen == ["https://example.test/quote?symbol=AAPL&token=secret-key-value"]
    assert "secret-key-value" not in repr(result)
    assert result["ok"] == 0
    assert result["errors"] == ["refused https://example.test/quote?symbol=AAPL&token=***"]


def test_summary_counts_distinct_bodies_and_ignores_failed_samples():
    samples = [
        Sample(200, 100.0, 10, 100, "a"),
        Sample(200, 300.0, 10, 100, "a"),
        Sample(200, 200.0, 10, 100, "b"),
        Sample(None, 5000.0, 0, 0, None, error="timed out"),
    ]

    summary = summarize(samples)

    assert summary["samples"] == 4
    assert summary["ok"] == 3
    assert summary["median_ms"] == 200.0
    assert summary["max_ms"] == 300.0
    assert summary["changes"] == 1
    assert summary["errors"] == ["timed out"]
