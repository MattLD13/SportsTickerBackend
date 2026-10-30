"""Prove that the Six renderers draw the recorded pixels for every golden case.

`tools/rendering/six_golden.py` owns the corpus and the digests. If a change alters pixels on purpose,
inspect real 384x32 frames, then write new digests with `python tools/rendering/six_golden.py accept`.
"""
import gzip
import json

import pytest

from tools.rendering.six_golden import CORPUS, DIGESTS, case_digest, run_case

pytestmark = pytest.mark.critical


def test_every_golden_case_draws_its_recorded_pixels():
    cases = json.loads(gzip.decompress(CORPUS.read_bytes()))
    expected = json.loads(DIGESTS.read_text(encoding="utf-8"))
    assert len(cases) == len(expected) > 1000
    changed = [(index, case["source"]) for index, case in enumerate(cases) if case_digest(run_case(case)) != expected[index]]
    assert not changed, f"{len(changed)} golden cases changed, first: {changed[:5]}"
