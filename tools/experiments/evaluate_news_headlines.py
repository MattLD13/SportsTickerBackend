"""Compare standard and Fast GPT-6 Luna labels on one week of ticker headlines."""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sports_ticker.leagues import TEAM_CATALOG_PATHS
from sports_ticker.providers.http import UrllibJsonHttpClient


_ESPN_BASE = "https://site.web.api.espn.com/apis/site/v2/sports"
_ESPN_STORY_BASE = "https://now.core.api.espn.com/v1/sports/news"
_API_URL = "https://api.openai.com/v1/responses"
_MODEL = "gpt-6-luna"
_FEED_LIMIT = 50
_BATCH_SIZE = 40
_MIN_HEADLINE_COUNT = 101
_KINDS = (
    "TRADE",
    "SIGNING",
    "EXTENSION",
    "INJURY",
    "WAIVER",
    "DFA",
    "RELEASE",
    "OPTION",
    "RECALL",
    "ACTIVATED",
    "SUSPENSION",
    "RETIREMENT",
    "NO_TENDER",
    "NEWS",
)
_REGRESSION_ID = "reported-a2f1186af045029cad62"
_REGRESSION_HEADLINE = "Amid trade request, Red Wings move Larkin to injured reserve"
_REGRESSION_URL = (
    "https://www.espn.com/nhl/story/_/id/50087005/"
    "amid-trade-request-red-wings-move-larkin-injured-reserve"
)


def _published_at(article: dict[str, object]) -> datetime | None:
    """Read one ESPN publication timestamp as UTC."""

    value = str(article.get("published") or article.get("lastModified") or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _article_url(article: dict[str, object]) -> str:
    """Return one ESPN web link when the feed provides it."""

    links = article.get("links")
    web = links.get("web") if isinstance(links, dict) else None
    return str(web.get("href") or "") if isinstance(web, dict) else ""


def _week_headlines() -> tuple[list[dict[str, str]], datetime, datetime]:
    """Fetch distinct HeadlineNews articles published in the last seven days."""

    ended_at = datetime.now(timezone.utc)
    started_at = ended_at - timedelta(days=7)
    client = UrllibJsonHttpClient()
    headlines: list[dict[str, str]] = []
    seen: set[str] = set()
    for league, path in TEAM_CATALOG_PATHS.items():
        url = f"{_ESPN_BASE}/{path}/news?limit={_FEED_LIMIT}"
        payload = client.get_json(url, timeout=20.0)
        articles = payload.get("articles", ()) if isinstance(payload, dict) else ()
        for article in articles:
            if not isinstance(article, dict):
                continue
            if str(article.get("type") or "").strip().lower() != "headlinenews":
                continue
            published = _published_at(article)
            if published is None or not started_at <= published <= ended_at:
                continue
            headline = str(article.get("headline") or article.get("title") or "").strip()
            article_id = str(article.get("id") or headline).strip()
            key = article_id.casefold()
            if not headline or key in seen:
                continue
            seen.add(key)
            headlines.append({
                "id": f"{league}-{article_id}",
                "espn_article_id": article_id,
                "sport": league,
                "headline": headline,
                "description": str(article.get("description") or "").strip(),
                "published_at": published.isoformat(),
                "source_url": _article_url(article),
            })

    incident_time = datetime(2026, 10, 2, 23, 29, 25, tzinfo=timezone.utc)
    if started_at <= incident_time <= ended_at and not any(
        item["headline"].casefold() == _REGRESSION_HEADLINE.casefold()
        for item in headlines
    ):
        headlines.append({
            "id": _REGRESSION_ID,
            "espn_article_id": "50087005",
            "sport": "nhl",
            "headline": _REGRESSION_HEADLINE,
            "description": "Detroit places captain Dylan Larkin on injured reserve.",
            "published_at": incident_time.isoformat(),
            "source_url": _REGRESSION_URL,
        })
    else:
        for item in headlines:
            if item["headline"].casefold() == _REGRESSION_HEADLINE.casefold():
                item["id"] = _REGRESSION_ID
                item["source_url"] = _REGRESSION_URL

    if len(headlines) < _MIN_HEADLINE_COUNT:
        raise ValueError(f"Only {len(headlines)} distinct headlines were available in the week window")
    return headlines, started_at, ended_at


class _StoryTextParser(HTMLParser):
    """Extract readable text from ESPN's story HTML field."""

    _BLOCK_TAGS = frozenset(("p", "div", "br", "li", "h1", "h2", "h3", "blockquote"))

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def _fetch_full_article(item: dict[str, str]) -> tuple[str, str, str]:
    """Fetch ESPN's article body without saving its copyrighted text to the report."""

    article_id = item["espn_article_id"]
    request = Request(
        f"{_ESPN_STORY_BASE}/{article_id}",
        headers={"User-Agent": "SportsTicker news evaluation"},
    )
    try:
        with urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return item["id"], "", "fetch_failed"
    stories = payload.get("headlines", ()) if isinstance(payload, dict) else ()
    story = next(
        (
            row.get("story")
            for row in stories
            if isinstance(row, dict) and str(row.get("id")) == article_id
        ),
        "",
    )
    if not isinstance(story, str) or not story.strip():
        return item["id"], "", "story_unavailable"
    parser = _StoryTextParser()
    parser.feed(story)
    text = parser.text()
    if len(text) < 500:
        return item["id"], text, "short_story"
    return item["id"], text, "full_text"


def _schema(headlines: list[dict[str, str]]) -> dict[str, object]:
    """Require exactly one structured result for every input article ID."""

    result_properties = {
        item["id"]: {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(_KINDS)},
                "evidence": {"type": "string"},
            },
            "required": ["kind", "evidence"],
            "additionalProperties": False,
        }
        for item in headlines
    }
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "object",
                "properties": result_properties,
                "required": list(result_properties),
                "additionalProperties": False,
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def _output_text(response: dict[str, object]) -> str:
    """Extract the text block from one Responses API response."""

    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                return str(content.get("text") or "")
    raise ValueError("Responses API returned no output text")


def _classify(
    headlines: list[dict[str, str]],
    full_texts: dict[str, str],
    api_key: str,
    service_tier: str,
) -> dict[str, object]:
    """Classify the same full-article set at the requested processing tier."""

    instructions = (
        "Classify each sports news article independently from its headline, description, and full article text. "
        "A request, rumor, target, or wish list is not a completed trade. Use TRADE only "
        "when the article reports a completed player transfer. A move to injured reserve "
        "is INJURY. Use NEWS when no listed event kind is directly supported. Return every "
        "input ID exactly once. Quote the shortest supporting phrase as evidence."
    )
    model_input = [
        {
            "id": item["id"],
            "sport": item["sport"],
            "headline": item["headline"],
            "description": item["description"],
            "article_text": full_texts[item["id"]],
        }
        for item in headlines
    ]
    body = {
        "model": _MODEL,
        "store": False,
        "service_tier": service_tier,
        "reasoning": {"effort": "low"},
        "input": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(model_input, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "ticker_news_classifications",
                "strict": True,
                "schema": _schema(headlines),
            }
        },
    }
    request = Request(
        _API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    started = perf_counter()
    try:
        with urlopen(request, timeout=120) as result:
            response = json.loads(result.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"OpenAI API returned HTTP {error.code} for {service_tier}") from None
    except URLError as error:
        raise RuntimeError(f"OpenAI API request failed for {service_tier}: {error.reason}") from None
    elapsed = perf_counter() - started
    parsed = json.loads(_output_text(response))
    raw_results = parsed.get("results")
    usage = response.get("usage")
    if not isinstance(raw_results, dict) or not isinstance(usage, dict):
        raise ValueError(f"Responses API returned invalid results or usage for {service_tier}")
    results = [{"id": item_id, **result} for item_id, result in raw_results.items()]
    details = usage.get("input_tokens_details")
    cached_tokens = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    return {
        "results": results,
        "usage": {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "cached_input_tokens": int(cached_tokens or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
        },
        "requested_tier": service_tier,
        "actual_tier": str(response.get("service_tier") or service_tier),
        "elapsed_seconds": elapsed,
    }


def _estimated_cost(run: dict[str, object]) -> float:
    """Estimate cost from actual service tier and token usage."""

    usage = run["usage"]
    if not isinstance(usage, dict):
        return 0.0
    input_tokens = int(usage["input_tokens"])
    cached_tokens = min(input_tokens, int(usage["cached_input_tokens"]))
    output_tokens = int(usage["output_tokens"])
    regular = (input_tokens - cached_tokens) * 0.10 / 1_000_000
    cached = cached_tokens * 0.01 / 1_000_000
    output = output_tokens * 0.50 / 1_000_000
    multiplier = 2 if str(run["actual_tier"]).casefold() in {"fast", "priority"} else 1
    return (regular + cached + output) * multiplier


def _classify_corpus(
    headlines: list[dict[str, str]],
    full_texts: dict[str, str],
    api_key: str,
    service_tier: str,
) -> dict[str, object]:
    """Classify one corpus in bounded batches and combine usage details."""

    combined: dict[str, object] = {
        "results": [],
        "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0},
        "requested_tier": service_tier,
        "actual_tiers": set(),
        "elapsed_seconds": 0.0,
    }
    for start in range(0, len(headlines), _BATCH_SIZE):
        result = _classify(headlines[start:start + _BATCH_SIZE], full_texts, api_key, service_tier)
        combined["results"].extend(result["results"])
        combined["actual_tiers"].add(result["actual_tier"])
        combined["elapsed_seconds"] += result["elapsed_seconds"]
        for name, value in result["usage"].items():
            combined["usage"][name] += value
    tiers = sorted(combined.pop("actual_tiers"))
    combined["actual_tier"] = ",".join(tiers)
    return combined


def _index_results(run: dict[str, object], expected_ids: set[str]) -> dict[str, dict[str, str]]:
    """Validate and index model labels by headline ID."""

    results = run.get("results")
    if not isinstance(results, list):
        raise ValueError("Model output has no results list")
    indexed = {str(item.get("id")): item for item in results if isinstance(item, dict)}
    if set(indexed) != expected_ids:
        missing = expected_ids - set(indexed)
        unexpected = set(indexed) - expected_ids
        raise ValueError(
            f"Model returned {len(indexed)} IDs for {len(expected_ids)} articles "
            f"({len(missing)} missing, {len(unexpected)} unexpected)"
        )
    return indexed


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not available to this process.", file=sys.stderr)
        return 2

    try:
        headlines, started_at, ended_at = _week_headlines()
        with ThreadPoolExecutor(max_workers=8) as pool:
            fetched = list(pool.map(_fetch_full_article, headlines))
        full_texts = {article_id: body for article_id, body, status in fetched if status == "full_text"}
        article_status = {article_id: status for article_id, _body, status in fetched}
        full_headlines = [item for item in headlines if item["id"] in full_texts]
        if len(full_headlines) < _MIN_HEADLINE_COUNT:
            raise ValueError(
                f"Only {len(full_headlines)} full article bodies were available from "
                f"{len(headlines)} one-week headlines"
            )
        expected_ids = {item["id"] for item in full_headlines}
        normal = _classify_corpus(full_headlines, full_texts, api_key, "default")
        fast = _classify_corpus(full_headlines, full_texts, api_key, "fast")
        normal_by_id = _index_results(normal, expected_ids)
        fast_by_id = _index_results(fast, expected_ids)
    except Exception as error:
        print(f"News AI comparison failed: {error}", file=sys.stderr)
        return 2

    rows = []
    for headline in full_headlines:
        normal_result = normal_by_id[headline["id"]]
        fast_result = fast_by_id[headline["id"]]
        rows.append({
            **headline,
            "article_text_chars": len(full_texts[headline["id"]]),
            "article_fetch_status": article_status[headline["id"]],
            "normal_kind": normal_result["kind"],
            "normal_evidence": normal_result["evidence"],
            "fast_kind": fast_result["kind"],
            "fast_evidence": fast_result["evidence"],
            "same_kind": normal_result["kind"] == fast_result["kind"],
        })

    output_dir = Path("previews")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"news_ai_full_article_week_{ended_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    report = {
        "model": _MODEL,
        "reasoning_effort": "low",
        "window_start_utc": started_at.isoformat(),
        "window_end_utc": ended_at.isoformat(),
        "headline_count": len(headlines),
        "full_article_count": len(full_headlines),
        "article_fetch_status_counts": dict(Counter(article_status.values())),
        "normal": {**normal, "estimated_cost_usd": _estimated_cost(normal)},
        "fast": {**fast, "estimated_cost_usd": _estimated_cost(fast)},
        "agreement_count": sum(row["same_kind"] for row in rows),
        "headlines": rows,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Window: {started_at.isoformat()} to {ended_at.isoformat()}")
    print(
        f"Articles: {len(full_headlines)} full bodies from {len(headlines)} weekly headlines "
        f"across {len(TEAM_CATALOG_PATHS)} ticker feeds"
    )
    print(
        f"Normal: {normal['actual_tier']} service, {normal['elapsed_seconds']:.1f}s, "
        f"{normal['usage']['input_tokens']} input / {normal['usage']['output_tokens']} output tokens, "
        f"${_estimated_cost(normal):.6f}"
    )
    print(
        f"Fast: {fast['actual_tier']} service, {fast['elapsed_seconds']:.1f}s, "
        f"{fast['usage']['input_tokens']} input / {fast['usage']['output_tokens']} output tokens, "
        f"${_estimated_cost(fast):.6f}"
    )
    print(f"Kind agreement: {report['agreement_count']}/{len(headlines)}")
    for row in rows:
        if not row["same_kind"]:
            print(
                f"DIFF [{row['sport']}] normal={row['normal_kind']} fast={row['fast_kind']}: "
                f"{row['headline']}"
            )
    regression = next((row for row in rows if row["id"] == _REGRESSION_ID), None)
    if regression is None:
        print("Regression headline is missing from the one-week window.", file=sys.stderr)
        return 1
    print(
        f"Regression: normal={regression['normal_kind']} fast={regression['fast_kind']} "
        f"for {regression['headline']}"
    )
    print(f"Full outputs: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
