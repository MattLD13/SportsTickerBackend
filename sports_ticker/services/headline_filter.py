"""Decide whether a headline is actually about a company.

The problem is not whether a headline mentions a company. It is whether the
company is what the headline is *about*. "AEye to Participate in J.P. Morgan
Auto Conference" names the bank and is about AEye.

Two layers answer that, and the second needs no account.

* A word rule keeps a headline only when the company appears near the front,
  where a subject sits. Free, instant, and it drops the AEye case. It also
  drops a few good ones, such as "Tim Cook Says There's No Better Person to
  Take Over at Apple", where the company arrives last.
* A model reads the shortlist and answers properly, recovering those.

The model runs on OVHcloud's anonymous tier: no key, no signup, no credit card,
and an OpenAI-compatible endpoint. The anonymous limit is two requests a minute
per address, against the one request per ten-minute poll this makes.

Every setting can be overridden, and a key is sent only when one is set, so any
OpenAI-compatible provider works if the anonymous tier ever goes away:

    HEADLINE_AI_URL=...        # default: OVHcloud, anonymous
    HEADLINE_AI_MODEL=...      # default: Meta-Llama-3_3-70B-Instruct
    HEADLINE_AI_KEY=...        # optional, only if the endpoint wants one
"""

import json
import os
import re

import requests

DEFAULT_URL = ('https://llama-3-3-70b-instruct.endpoints.kepler.ai.cloud.ovh.net'
               '/api/openai_compat/v1/chat/completions')
DEFAULT_MODEL = 'Meta-Llama-3_3-70B-Instruct'
TIMEOUT = 20

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
    """Read the environment on every call, so a change needs no restart."""
    return (
        os.getenv('HEADLINE_AI_URL') or DEFAULT_URL,
        os.getenv('HEADLINE_AI_MODEL') or DEFAULT_MODEL,
        os.getenv('HEADLINE_AI_KEY') or '',
    )


def build_prompt(pairs):
    """One numbered line per candidate, so a single request covers the poll."""
    lines = [f"{i + 1}. [{symbol}] {headline}" for i, (symbol, headline) in enumerate(pairs)]
    return _PROMPT + "\n".join(lines)


def parse_reply(reply, count):
    """Pull the kept numbers out of a reply and turn them into indices.

    A model will sometimes wrap the array in prose or a code fence, so the
    first array in the text is taken rather than the whole reply parsed.
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

    Returns None when the call fails for any reason, including the anonymous
    rate limit. The caller keeps its own rule-filtered set in that case, so a
    model that is busy or down costs relevance rather than the whole feed.
    """
    if not pairs:
        return set()
    url, model, key = _settings()

    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = f'Bearer {key}'

    try:
        post = (session or requests).post
        r = post(
            url,
            headers=headers,
            json={
                'model': model,
                'temperature': 0,
                'max_tokens': 200,
                'messages': [{'role': 'user', 'content': build_prompt(pairs)}],
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            # 429 is the anonymous tier saying "not right now", which is normal
            # and not worth a stack trace.
            print(f"[HEADLINE AI] {r.status_code} from {url.split('/')[2]}")
            return None
        reply = r.json()['choices'][0]['message']['content']
    except Exception as exc:
        print(f"[HEADLINE AI] call failed: {exc}")
        return None

    return parse_reply(reply, len(pairs))
