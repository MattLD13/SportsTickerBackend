"""Render sourced score-alert examples as a Codex gallery fragment."""

from __future__ import annotations

import base64
import html
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from ticker_core.features.alerts.score_alert import PreparedScoreAlertRenderer
from ticker_core.rendering import load_default_font_set


class EmptyLogos:
    """Use ticker acronym badges for offline gallery renders."""

    def get(self, url, size):
        del url, size
        return None


EXAMPLES = (
    {
        "title": "Yankees · Home Run · Aaron Judge",
        "source": "MLB StatsAPI · Yankees–Brewers, Mar 29 2025",
        "url": "https://statsapi.mlb.com/api/v1.1/game/778538/feed/live",
        "sport": "mlb", "headline": "HOME RUN", "player": "Aaron Judge",
        "data": "468FT 115EV 30LA", "status": "Bottom 1st",
        "home_abbr": "NYY", "away_abbr": "MIL", "home_score": 3, "away_score": 0,
        "team_abbr": "NYY", "team_color": "#132448", "team_alt_color": "#C4CED4",
    },
    {
        "title": "Yankees · Grand Slam · Aaron Judge",
        "source": "MLB StatsAPI · Yankees–Brewers, Mar 29 2025",
        "url": "https://statsapi.mlb.com/api/v1.1/game/778538/feed/live",
        "sport": "mlb", "headline": "GRAND SLAM", "player": "Aaron Judge",
        "data": "396FT 99EV 29LA", "status": "Bottom 3rd",
        "home_abbr": "NYY", "away_abbr": "MIL", "home_score": 12, "away_score": 3,
        "team_abbr": "NYY", "team_color": "#132448", "team_alt_color": "#C4CED4",
    },
    {
        "title": "Yankees · RBI Single · Cody Bellinger",
        "source": "MLB StatsAPI · Yankees–Brewers, Mar 29 2025",
        "url": "https://statsapi.mlb.com/api/v1.1/game/778538/feed/live",
        "sport": "mlb", "headline": "RBI SINGLE", "player": "Cody Bellinger",
        "status": "Bottom 3rd",
        "home_abbr": "NYY", "away_abbr": "MIL", "home_score": 8, "away_score": 3,
        "team_abbr": "NYY", "team_color": "#132448", "team_alt_color": "#C4CED4",
    },
    {
        "title": "Yankees · Sac Fly · Cody Bellinger",
        "source": "MLB StatsAPI · Yankees–Brewers, Mar 29 2025",
        "url": "https://statsapi.mlb.com/api/v1.1/game/778538/feed/live",
        "sport": "mlb", "headline": "SAC FLY", "player": "Cody Bellinger",
        "status": "Bottom 4th",
        "home_abbr": "NYY", "away_abbr": "MIL", "home_score": 14, "away_score": 4,
        "team_abbr": "NYY", "team_color": "#132448", "team_alt_color": "#C4CED4",
    },
    {
        "title": "Yankees · RBI Double · Aaron Judge",
        "source": "MLB StatsAPI · Yankees–Brewers, Mar 29 2025",
        "url": "https://statsapi.mlb.com/api/v1.1/game/778538/feed/live",
        "sport": "mlb", "headline": "RBI DOUBLE", "player": "Aaron Judge",
        "status": "Bottom 6th",
        "home_abbr": "NYY", "away_abbr": "MIL", "home_score": 18, "away_score": 6,
        "team_abbr": "NYY", "team_color": "#132448", "team_alt_color": "#C4CED4",
    },
    {
        "title": "Rangers · Short-handed Goal · Mika Zibanejad",
        "source": "NHL Gamecenter · Rangers–Penguins, Oct 11 2025",
        "url": "https://api-web.nhle.com/v1/gamecenter/2025020029/play-by-play",
        "sport": "nhl", "headline": "SHORT-HANDED GOAL", "player": "Mika Zibanejad",
        "primary_assist": "Sam Carrick", "secondary_assist": "Adam Fox", "status": "P1 07:40",
        "home_abbr": "PIT", "away_abbr": "NYR", "home_score": 0, "away_score": 1,
        "team_abbr": "NYR", "team_color": "#0038A8", "team_alt_color": "#C8102E",
    },
    {
        "title": "Rangers · Goal · Adam Fox · One Assist",
        "source": "NHL Gamecenter · Rangers–Sabres, Oct 9 2025",
        "url": "https://api-web.nhle.com/v1/gamecenter/2025020009/play-by-play",
        "sport": "nhl", "headline": "GOAL", "player": "Adam Fox",
        "primary_assist": "Sam Carrick", "status": "P3 17:25",
        "home_abbr": "BUF", "away_abbr": "NYR", "home_score": 0, "away_score": 4,
        "team_abbr": "NYR", "team_color": "#0038A8", "team_alt_color": "#C8102E",
    },
    {
        "title": "Giants · Pass TD · Darius Slayton",
        "source": "Giants.com · Giants–Washington, Oct 18 2020",
        "url": "https://www.giants.com/news/tae-crowder-defensive-td-propels-giants-to-20-19-victory-washington-joe-judge",
        "sport": "nfl", "headline": "PASS TD", "player": "Darius Slayton",
        "data": "23YD PASS Daniel Jones", "status": "Q1 01:36",
        "home_abbr": "NYG", "away_abbr": "WAS", "home_score": 10, "away_score": 0,
        "team_abbr": "NYG", "team_color": "#0B2265", "team_alt_color": "#A71930",
    },
    {
        "title": "Giants · Fumble TD · Tae Crowder",
        "source": "Giants.com · Giants–Washington, Oct 18 2020",
        "url": "https://www.giants.com/news/tae-crowder-defensive-td-propels-giants-to-20-19-victory-washington-joe-judge",
        "sport": "nfl", "headline": "FUMBLE TD", "player": "Tae Crowder",
        "data": "FUMBLE 43YD RET", "status": "Q4 03:29",
        "home_abbr": "NYG", "away_abbr": "WAS", "home_score": 20, "away_score": 13,
        "team_abbr": "NYG", "team_color": "#0B2265", "team_alt_color": "#A71930",
    },
    {
        "title": "Lehigh · Rush TD · Luke Yoder · 2&1",
        "source": "Lehigh Athletics · Lehigh–Dartmouth, Sep 19 2026",
        "url": "https://lehighsports.com/sports/football/stats/2026/dartmouth/boxscore/15826",
        "sport": "ncf_fcs", "headline": "RUSH TD", "player": "Luke Yoder",
        "data": "RUSH 1YD", "down_distance": "2&1", "is_red_zone": True, "status": "Q1 08:29",
        "home_abbr": "LEH", "away_abbr": "DAR", "home_score": 7, "away_score": 0,
        "team_abbr": "LEH", "team_color": "#4B2E83", "team_alt_color": "#D3D3D3",
    },
    {
        "title": "Lehigh · Field Goal · Owen Zalc · 4&7",
        "source": "Lehigh Athletics · Lehigh–Dartmouth, Sep 19 2026",
        "url": "https://lehighsports.com/sports/football/stats/2026/dartmouth/boxscore/15826",
        "sport": "ncf_fcs", "headline": "FIELD GOAL", "player": "Owen Zalc",
        "data": "50YD FIELD GOAL", "down_distance": "4&7", "is_red_zone": False, "status": "Q1 04:54",
        "home_abbr": "LEH", "away_abbr": "DAR", "home_score": 7, "away_score": 3,
        "team_abbr": "DAR", "team_color": "#00693E", "team_alt_color": "#FFFFFF",
    },
    {
        "title": "Lehigh · Interception · D.J. Brown · 2&10",
        "source": "Lehigh Athletics · Lehigh–Dartmouth, Sep 19 2026",
        "url": "https://lehighsports.com/sports/football/stats/2026/dartmouth/boxscore/15826",
        "sport": "ncf_fcs", "headline": "INTERCEPTION", "player": "D.J. Brown",
        "data": "INTERCEPTION", "down_distance": "2&10", "is_red_zone": False, "status": "Q4 00:13",
        "home_abbr": "LEH", "away_abbr": "DAR", "home_score": 24, "away_score": 20,
        "team_abbr": "LEH", "team_color": "#4B2E83", "team_alt_color": "#D3D3D3",
    },
)


def render_gallery(output_dir: Path) -> Path:
    renderer = PreparedScoreAlertRenderer(load_default_font_set(), EmptyLogos())
    sections = []
    for index, example in enumerate(EXAMPLES, 1):
        title = example["title"]
        alert = {key: value for key, value in example.items() if key not in {"title", "source", "url"}}
        frame = renderer.draw_score_alert(alert, 2.0)
        path = output_dir / f"score-alert-{index:02d}.png"
        frame.save(path)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        alt = "; ".join(
            str(alert.get(key) or "")
            for key in ("player", "data", "primary_assist", "secondary_assist", "down_distance")
        ).strip("; ")
        sections.append(
            "<figure>"
            f'<img alt="{html.escape(title + ": " + alt, quote=True)}" '
            f'src="data:image/png;base64,{encoded}">'
            f"<figcaption><strong>{html.escape(title)}</strong><br>"
            f'<a href="{html.escape(example["url"], quote=True)}">{html.escape(example["source"])}</a>'
            "</figcaption></figure>"
        )
    fragment = (
        '<div id="score-alert-gallery-v2">'
        "<style>#score-alert-gallery-v2{display:grid;gap:12px;max-width:736px;"
        "font:14px/1.35 system-ui,sans-serif;color:var(--foreground)}"
        "#score-alert-gallery-v2 figure{margin:0;display:grid;gap:4px}"
        "#score-alert-gallery-v2 img{display:block;width:100%;height:auto;image-rendering:pixelated}"
        "#score-alert-gallery-v2 figcaption{font-size:12px;color:var(--muted-foreground)}"
        "#score-alert-gallery-v2 strong{color:var(--foreground)}"
        "#score-alert-gallery-v2 a{color:var(--primary)}</style>"
        + "".join(sections)
        + "</div>"
    )
    html_path = output_dir / "score-alert-gallery.html"
    html_path.write_text(fragment, encoding="utf-8")
    if len(fragment.encode("utf-8")) >= 1_000_000:
        raise ValueError("The score-alert gallery exceeds 1 MB.")
    if re.search(r"<\s*(?:!doctype|html|head|body)\b", fragment, re.IGNORECASE):
        raise ValueError("The gallery must remain an HTML fragment.")
    return html_path


if __name__ == "__main__":
    output = Path(sys.argv[1]).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    print(render_gallery(output))
