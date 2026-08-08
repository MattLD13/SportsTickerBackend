"""Decide whether a headline is actually about a company.

The problem is not whether a headline mentions a company. It is whether the
company is what the headline is *about*. "AEye to Participate in J.P. Morgan
Auto Conference" names the bank and is not about the bank.

Two layers answer that, and the second is optional.

* A word rule keeps a headline only when the company appears near the front.
  Free, instant, and it catches the case above, because "AEye" is the subject
  and the bank arrives five words later. It also drops a few good ones, such as
  "Tim Cook Says There's No Better Person to Take Over at Apple".
* A model reads the shortlist and answers properly. It fixes the ones the rule
  loses. It is optional, and when it is absent or fails the rule stands.

Any OpenAI-compatible endpoint works, so the provider is a matter of which key
is set. Groq's free tier is the default because it needs no credit card and
allows 14,400 requests a day, against the one request per poll this makes.

    HEADLINE_AI_KEY=...        # or GROQ_API_KEY
    HEADLINE_AI_URL=...        # default: Groq
    HEADLINE_AI_MODEL=...      # default: llama-3.1-8b-instant

Cerebras and OpenRouter both speak the same protocol. Point the URL and the
model at either and nothing else changes.
"""

import json
import os
import re

import requests

DEFAULT_URL = 'https://api.groq.com/openai/v1/chat/completions'
DEFAULT_MODEL = 'llama-3.1-8b-instant'
TIMEOUT = 12

_PROMPT = (
    "You decide whether a news headline is about a specific company.\n"
    "It is ABOUT the company when the company is the subject: its results, "
    "stock, products, leadership, legal matters, or deals it is making.\n"
    "It is NOT about the company when the company is only mentioned in "
    "passing, such as another firm presenting at its conference, an index it "
    "belongs to, or an analyst who works there commenting on something else.\n\n"
    "Reply with a JSON array of the numbers that ARE about their company. "
    "No other text.\n\n"
)


def _settings():
    """Read the environment on every call, so a new key needs no restart."""
    return (
        os.getenv('HEADLINE_AI_KEY') or os.getenv('GROQ_API_KEY') or '',
        os.getenv('HEADLINE_AI_URL') or DEFAULT_URL,
        os.getenv('HEADLINE_AI_MODEL') or DEFAULT_MODEL,
    )


def is_enabled():
    return bool(_settings()[0])


def build_prompt(pairs):
    """One numbered line per candidate, so a single request covers the poll."""
    lines = [f"{i + 1}. [{symbol}] {headline}" for i, (symbol, headline) in enumerate(pairs)]
    return _PROMPT + "\n".join(lines)


def parse_reply(reply, count):
    """Pull the kept numbers out of a reply and turn them into indices.

    A small model will sometimes wrap the array in prose or a code fence, so
    the first array in the text is taken rather than the whole reply parsed.
    Anything unreadable returns None, which means "no opinion" and leaves the
    word rule in charge.
    """
    match = re.search(r'\[[^\]]*\]', str(reply or ''), re.S)
    if not match:
        return None
    try:
        numbers = json.loads(match.group(0))
    except Exception:
        return None
    if not isinstance(numbers, list):
        return None
    kept = set()
    for value in numbers:
        try:
            index = int(value) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < count:
            kept.add(index)
    return kept


def keep_relevant(pairs, session=None):
    """Return the indices of ``[(symbol, headline)]`` that are about the company.

    Returns None when no key is set, or when the call fails for any reason. The
    caller keeps its own rule-filtered set in that case, so a model that is
    down or slow costs relevance rather than the whole feed.
    """
    if not pairs:
        return set()
    key, url, model = _settings()
    if not key:
        return None

    try:
        post = (session or requests).post
        r = post(
            url,
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={
                'model': model,
                'temperature': 0,
                'max_tokens': 200,
                'messages': [{'role': 'user', 'content': build_prompt(pairs)}],
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            print(f"[HEADLINE AI] {r.status_code} from {url}")
            return None
        reply = r.json()['choices'][0]['message']['content']
    except Exception as exc:
        print(f"[HEADLINE AI] call failed: {exc}")
        return None

    return parse_reply(reply, len(pairs))
