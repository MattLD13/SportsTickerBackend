import os

from sports_ticker.fetchers.stock_news import _is_about, _is_subject
from sports_ticker.services.headline_filter import build_prompt, keep_relevant, parse_reply


class _Reply:
    def __init__(self, status=200, content='[1, 3]'):
        self.status_code = status
        self._content = content

    def json(self):
        return {'choices': [{'message': {'content': self._content}}]}


class _Session:
    """Stands in for requests, so the parsing is testable without a key."""

    def __init__(self, reply=None, boom=False):
        self.reply, self.boom = reply or _Reply(), boom
        self.sent, self.headers = None, {}

    def post(self, url, headers=None, json=None, timeout=None):
        if self.boom:
            raise RuntimeError('network down')
        self.sent, self.headers = json, headers or {}
        return self.reply


PAIRS = [
    ('JPM', 'AEye to Participate in J.P. Morgan Auto Conference'),
    ('AAPL', "Tim Cook Says There's No Better Person to Take Over at Apple"),
    ('NVDA', 'Nvidia ends week up more than 10%'),
]


def test_the_word_rule_separates_naming_from_being_about():
    """Naming a company is not the same as being about it."""
    # The bank is five words in, and the headline is about AEye. These are the
    # real words the name lookup returns for JPM.
    assert _is_about(PAIRS[0][1], 'JPM', {'morgan', 'chase'})
    assert not _is_subject(PAIRS[0][1], 'JPM', {'morgan', 'chase'})
    # The company leads, so it is the subject.
    assert _is_subject(PAIRS[2][1], 'NVDA', {'nvidia'})
    # The rule's known cost: this one is about Apple and gets dropped anyway,
    # because the company arrives at the end. The model layer recovers it.
    assert _is_about(PAIRS[1][1], 'AAPL', {'apple'})
    assert not _is_subject(PAIRS[1][1], 'AAPL', {'apple'})


def test_the_model_layer_reads_a_reply_and_fails_safe():
    # A small model wraps the array in prose or a fence often enough to matter.
    assert parse_reply('Here you go:\n```json\n[2, 3]\n```', 3) == {1, 2}
    assert parse_reply('[1]', 3) == {0}
    assert parse_reply('out of range [9]', 3) == set()
    assert parse_reply('no array here', 3) is None

    session = _Session(_Reply(content='[3]'))
    assert keep_relevant(PAIRS, session) == {2}
    assert '1. [JPM]' in session.sent['messages'][0]['content']

    # Anything that goes wrong returns None, which hands the decision back to
    # the word rule rather than dropping the whole feed.
    assert keep_relevant(PAIRS, _Session(boom=True)) is None
    assert keep_relevant(PAIRS, _Session(_Reply(status=429))) is None

    # The anonymous tier answers 429 when it is busy. That is normal, and it
    # means no opinion rather than an empty feed.
    assert keep_relevant(PAIRS, _Session(_Reply(status=429))) is None

    # No key is sent unless one is configured, because the default endpoint
    # takes none.
    session = _Session()
    keep_relevant(PAIRS, session)
    assert session.headers.get('Authorization') is None
