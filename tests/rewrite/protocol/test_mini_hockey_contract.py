from __future__ import annotations

import json
from pathlib import Path

import pytest

from sports_ticker.providers.sports_display import nhl_shootout_display, nhl_manpower_situation
from ticker_core.rendering.pixels import PANE
from tools.generate_mini_ui import header


pytestmark = pytest.mark.critical


def test_mini_hockey_vectors_use_the_shared_shootout_projection() -> None:
    rows = json.loads((Path(__file__).parents[1] / "debug/mini_hockey_panes.json").read_text(encoding="utf-8"))
    for row in rows:
        assert row["game"]["situation"]["shootout"] == nhl_shootout_display(row["facts"])
        if "expected_power_label" in row:
            game = row["game"]
            expected = nhl_manpower_situation(row["facts"], home_abbr=game["home_abbr"], away_abbr=game["away_abbr"])
            assert game["situation"]["manpower"] == expected["manpower"]
    late = next(row for row in rows if row["name"] == "round-twelve-home-next")
    assert late["game"]["situation"]["shootout"]["roundLabel"] == "R10-12"


def test_compact_hash_has_crossbar_extensions_and_exports_width(monkeypatch) -> None:
    assert PANE["#"] == [[0, 1, 0, 1, 0], [1, 1, 1, 1, 1], [0, 1, 0, 1, 0], [1, 1, 1, 1, 1], [0, 1, 0, 1, 0]]
    assert "paneWidths[95]" in header()
    monkeypatch.setitem(PANE, "#", [[0, 1, 0], [1, 1]])
    with pytest.raises(ValueError, match="consistent rows"):
        header()
