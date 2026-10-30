"""Render distinct score-alert layouts from recorded provider responses."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import os
import sys

sys.path[:0] = [os.path.join(str(Path(__file__).resolve().parents[2]), name) for name in ("shared", "server", "six", "")]
from ticker.shared.domain import DisplaySettings, TickerSnapshot
from ticker.server.projections.data_api import project_data_v2
from ticker.server.providers.espn_events import _content_item
from ticker.server.providers.espn_details import _event_plays, _event_scoring_details, _soccer_event_details, _event_football_details
from ticker.server.providers.espn_mlb import _mlb_statsapi_summary
from ticker.server.providers.score_alerts import _describe, _extract_alert_facts
from ticker.six.assets import AssetPlanner, LogoAssetView
from ticker.six.ui.score_alert import ScoreAlert, fact_layout
from ticker.six.platform import AssetCoordinator
from ticker.six.protocol import TickerResponse
from ticker.six.ui import load_default_font_set


GROUPS = {
    "mlb": "MLB", "nhl": "NHL", "nfl": "NFL", "ncf_fbs": "FBS",
    "ncf_fcs": "FCS", "soccer_epl": "Soccer", "nba": "Basketball Â· disabled",
}


def _scores(raw):
    if raw.get("homeScore") is not None and raw.get("awayScore") is not None:
        return int(raw["homeScore"]), int(raw["awayScore"])
    match = re.search(r"(?:Goal! |\.\s+).+? (\d+), .+? (\d+)\.", str(raw.get("text") or ""))
    return (int(match[1]), int(match[2])) if match else None


def _game_data(sport, event_id, summary):
    competitions = summary["header"]["competitions"]
    event = {
        "id": event_id, "competitions": competitions,
        "status": competitions[0].get("status", {}),
    }
    return dict(_content_item(sport, event).data)


def _status(sport, raw):
    period = raw.get("period", {})
    number = int(period.get("number") or 1)
    clock = str(raw.get("clock", {}).get("displayValue") or "")
    if sport == "nhl":
        return f"P{number} {clock}".strip()
    if sport.startswith("soccer"):
        return clock
    return f"Q{number} {clock}".strip()


def _alert(sport, event_id, data, play, raw, situation, *, kind="", headline=""):
    team = str(play.get("team") or "").upper()
    side = next((side for side in ("home", "away") if team == data[f"{side}_abbr"]), "")
    scores = _scores(raw)
    if not side or scores is None:
        return None
    home, away = scores
    points = int(play.get("score_value", 1))
    if not kind:
        kind, headline = _describe(sport, points, play)
    game = {
        **data, "id": event_id, "kind": "scoreboard", "state": "in",
        "home_score": home, "away_score": away, "status": _status(sport, raw),
        "situation": situation,
    }
    other = "away" if side == "home" else "home"
    return {
        "id": f"gallery:{event_id}:{raw.get('id', '')}:{kind}",
        "game_id": event_id, "sport": sport, "kind": kind, "headline": headline,
        "side": side, "ts": 100.0, "points": points,
        **_extract_alert_facts(sport, game, side, alert_kind=kind),
        "team_abbr": team, "opp_abbr": data[f"{other}_abbr"],
        "home_abbr": data["home_abbr"], "away_abbr": data["away_abbr"],
        "home_score": home, "away_score": away, "status": game["status"],
        **{f"team_{key}": data.get(f"{side}_{key}", "") for key in ("logo", "color", "alt_color")},
    }


def collect_espn(sources):
    examples = []
    for source in json.loads((sources / "source-index.json").read_text(encoding="utf-8")):
        if source.get("error") or source["sport"] == "march_madness":
            continue
        sport, event_id = source["sport"], source["id"]
        summary = json.loads((sources / f"{sport}-{event_id}.json").read_text(encoding="utf-8"))
        data = _game_data(sport, event_id, summary)
        drive_plays = [play for drive in summary.get("drives", {}).get("previous", []) for play in drive.get("plays", [])]
        drive_index = {str(play.get("id")): play for play in drive_plays}
        records = _event_plays(summary)
        scoring_ids = {str(play.get("id")) for play in summary.get("scoringPlays", [])}
        for raw in records:
            if sport.startswith("soccer") or sport in {"nhl", "nba"}:
                own_goal = sport.startswith("soccer") and "own goal" in str(raw.get("type", {})).lower()
                if not raw.get("scoringPlay") and not own_goal:
                    continue
            rich = deepcopy(raw)
            drive = drive_index.get(str(raw.get("id")), {})
            for key in ("start", "end", "isTurnover", "statYardage"):
                if key in drive:
                    rich[key] = drive[key]
            single = {"header": summary["header"], "boxscore": summary.get("boxscore", {}), "plays": [rich]}
            if str(raw.get("id")) in scoring_ids:
                single["scoringPlays"] = [rich]
            if sport.startswith("soccer"):
                situation = _soccer_event_details(single, data)
                goals = situation.get("goal_events", [])
                if not goals:
                    continue
                goal = goals[0]
                play = {
                    "team": data["home_abbr" if goal["is_home"] else "away_abbr"],
                    "type": raw.get("type", {}).get("text", "Goal"), "text": raw.get("text", ""),
                    "score_value": 1,
                }
            else:
                situation = _event_scoring_details(single, data)
                if sport in {"nfl", "ncf_fbs", "ncf_fcs"}:
                    situation.update(_event_football_details(single, data))
                plays = situation.get("scoring_plays", [])
                if not plays:
                    continue
                play = plays[0]
                start = rich.get("start", {})
                if start.get("down") in {1, 2, 3, 4}:
                    play.update(down=start["down"], distance=start.get("distance"))
                if sport == "nhl" and raw.get("period", {}).get("displayValue") == "SO":
                    continue
            alert = _alert(sport, event_id, data, play, raw, situation)
            if alert:
                examples.append({"alert": alert, "source": source["url"], "source_play_id": str(raw.get("id", ""))})
        if sport in {"nfl", "ncf_fbs", "ncf_fcs"}:
            previous_score = (0, 0)
            for raw in drive_plays:
                scores = _scores(raw)
                if scores is None:
                    continue
                delta_home, delta_away = scores[0] - previous_score[0], scores[1] - previous_score[1]
                previous_score = scores
                if not raw.get("scoringPlay") or str(raw.get("id")) in scoring_ids:
                    continue
                side = "home" if delta_home > 0 else "away" if delta_away > 0 else ""
                if not side:
                    continue
                rich = {**raw, "team": {"abbreviation": data[f"{side}_abbr"]}}
                single = {"header": summary["header"], "boxscore": summary.get("boxscore", {}), "scoringPlays": [rich]}
                situation = _event_scoring_details(single, data)
                if sport in {"nfl", "ncf_fbs", "ncf_fcs"}:
                    situation.update(_event_football_details(single, data))
                plays = situation.get("scoring_plays", [])
                if not plays:
                    continue
                play = plays[0]
                play["score_value"] = max(delta_home, delta_away)
                start = rich.get("start", {})
                if start.get("down") in {1, 2, 3, 4}:
                    play.update(down=start["down"], distance=start.get("distance"))
                alert = _alert(sport, event_id, data, play, raw, situation)
                if alert:
                    examples.append({"alert": alert, "source": source["url"], "source_play_id": str(raw.get("id", ""))})
            for raw in drive_plays:
                rich = deepcopy(raw)
                if not rich.get("team"):
                    rich["team"] = rich.get("end", {}).get("team") or rich.get("start", {}).get("team")
                single = {"header": summary["header"], "boxscore": summary.get("boxscore", {}), "plays": [rich]}
                situation = _event_scoring_details(single, data)
                if sport in {"nfl", "ncf_fbs", "ncf_fcs"}:
                    situation.update(_event_football_details(single, data))
                for play in situation.get("football_plays", []):
                    if play.get("is_scoring"):
                        continue
                    kind = play["football_kind"]
                    alert = _alert(
                        sport, event_id, data, {**play, "score_value": 0}, raw, situation,
                        kind=kind, headline="INTERCEPTION" if kind == "interception" else "FUMBLE",
                    )
                    if alert:
                        examples.append({"alert": alert, "source": source["url"], "source_play_id": str(raw.get("id", ""))})
    return examples


def collect_mlb(feed_path, team_path):
    source = json.loads(feed_path.read_text(encoding="utf-8"))
    event_id = str(source["gamePk"])
    normalized = _mlb_statsapi_summary(source, event_id)
    teams = source["gameData"]["teams"]
    metadata = json.loads(team_path.read_text(encoding="utf-8"))
    team_index = {
        entry["team"]["abbreviation"]: entry["team"]
        for sport in metadata["sports"] for league in sport["leagues"] for entry in league["teams"]
    }
    competition = {"competitors": [
        {
            "homeAway": side, "score": source["liveData"]["linescore"]["teams"][side]["runs"],
            "team": team_index[teams[side]["abbreviation"]],
        }
        for side in ("home", "away")
    ]}
    data = dict(_content_item("mlb", {
        "id": event_id, "competitions": [competition],
        "status": {"type": {"state": "post", "shortDetail": "Final"}},
    }).data)
    examples = []
    for raw in normalized.get("scoringPlays", []):
        plays = _event_scoring_details({**normalized, "scoringPlays": [raw]}, data).get("scoring_plays", [])
        if not plays:
            continue
        play = plays[0]
        original = next((p for p in source["liveData"]["plays"]["allPlays"] if str(p["about"].get("atBatIndex")) == str(raw.get("id"))), None)
        if original is None:
            original = next((p for p in source["liveData"]["plays"]["allPlays"] if p.get("matchup", {}).get("batter", {}).get("id") == int(play.get("player_id") or 0) and p["result"]["description"].startswith(str(raw.get("text") or "")[:40])), None)
        if original is None:
            continue
        score_raw = {**raw, "homeScore": original["result"]["homeScore"], "awayScore": original["result"]["awayScore"]}
        alert = _alert("mlb", event_id, data, play, score_raw, {"scoring_plays": [play]})
        if alert:
            half, inning = original["about"]["halfInning"], original["about"]["inning"]
            alert["status"] = f"{half.title()} {inning}"
            examples.append({"alert": alert, "source": f"https://statsapi.mlb.com/api/v1.1/game/{event_id}/feed/live", "source_play_id": str(original["about"]["atBatIndex"])})
    return examples


def render_gallery(examples, output):
    output.mkdir(parents=True, exist_ok=True)
    unique = {}
    for example in examples:
        alert = example["alert"]
        layout = fact_layout(alert, 42, 283)
        fields = tuple(kind for kind, _, _, _ in layout)
        assists = sum(bool(alert.get(key)) for key in ("primary_assist", "secondary_assist"))
        zone = alert.get("is_red_zone") if alert.get("down_distance") else "no down"
        key = (alert["sport"], alert["kind"], fields, assists, bool(alert.get("down_distance")), zone)
        if key not in unique:
            unique[key] = example
    selected = list(unique.values())
    groups = {sport: [] for sport in GROUPS}
    assets = AssetCoordinator(output / "assets")
    try:
        renderer = ScoreAlert(load_default_font_set(), LogoAssetView(assets))
        for index, example in enumerate(selected, 1):
            alert = example["alert"]
            settings = DisplaySettings(mode="sports", score_alerts=True, my_teams=(f"{alert['sport']}:{alert['team_abbr']}",))
            snapshot = TickerSnapshot("gallery", index, datetime.now(timezone.utc), (), (alert,), (), settings)
            payload = project_data_v2(snapshot, {}, {})
            response = TickerResponse.from_payload(payload)
            for future in assets.prefetch(AssetPlanner().plan(response).requests):
                future.result()
            frame = renderer.frame(response.alerts[0].data, 3.0)
            assert frame.size == (384, 32)
            assert all(x >= 42 and x + width <= 283 for _, _, x, width in fact_layout(alert, 42, 283))
            image_path = output / f"alert-{index:02d}.png"
            frame.save(image_path)
            (output / f"alert-{index:02d}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            fields = " + ".join(kind for kind, _, _, _ in fact_layout(alert, 42, 283)) or "headline only"
            zone = " Â· red zone" if alert.get("is_red_zone") is True else " Â· outside red zone" if alert.get("is_red_zone") is False and alert.get("down_distance") else ""
            label = f"{alert['headline']} Â· {fields}{zone}"
            title = f"{alert['away_abbr']} {alert['away_score']} â€” {alert['home_abbr']} {alert['home_score']} Â· {alert['status']}"
            groups[alert["sport"]].append(
                f'<figure><figcaption><span>{html.escape(label)}</span><br><span class="text-small text-muted">{html.escape(title)}</span></figcaption>'
                f'<img alt="{html.escape(label + "; " + title)}" src="data:image/png;base64,{encoded}">'
                f'<a class="text-small" href="{html.escape(example["source"], quote=True)}">Recorded play {html.escape(example["source_play_id"])}</a></figure>'
            )
    finally:
        assets.close()
    tabs, panels = [], []
    for index, (sport, label) in enumerate(GROUPS.items()):
        if not groups[sport]:
            continue
        active = not tabs
        tabs.append(f'<button type="button" class="nav-link{" active" if active else ""}" role="tab" id="combo-tab-{sport}" aria-controls="combo-panel-{sport}" aria-selected="{str(active).lower()}">{html.escape(label)} ({len(groups[sport])})</button>')
        panels.append(f'<div id="combo-panel-{sport}" role="tabpanel" aria-labelledby="combo-tab-{sport}"{"" if active else " hidden"}>'+"".join(groups[sport])+"</div>")
    fragment = '<div id="all-score-alert-combos"><style>#all-score-alert-combos [role="tabpanel"]{display:grid;gap:20px}#all-score-alert-combos [hidden]{display:none}#all-score-alert-combos figure{display:grid;gap:5px;margin:0;min-width:0}#all-score-alert-combos img{display:block;width:100%;height:auto;image-rendering:pixelated}</style><div class="nav nav-pills" role="tablist" aria-label="Sport">'+"".join(tabs)+"</div>"+"".join(panels)+"</div>"
    assert len(fragment.encode()) < 1_000_000
    target = output / "all-score-alert-combinations.html"
    target.write_text(fragment, encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
    print(json.dumps({"examples": len(selected), "by_sport": Counter(e["alert"]["sport"] for e in selected), "gallery": str(target)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--mlb-feed", type=Path, action="append", required=True)
    parser.add_argument("--mlb-teams", type=Path, required=True)
    parser.add_argument("--shootout-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    examples = collect_espn(args.sources)
    for feed in args.mlb_feed:
        examples.extend(collect_mlb(feed, args.mlb_teams))
    shootout = TickerResponse.from_payload(json.loads(args.shootout_snapshot.read_text(encoding="utf-8")))
    examples.append({"alert": dict(shootout.alerts[0].data), "source": "https://www.espn.com/nhl/game/_/gameId/401802398", "source_play_id": "final shootout result"})
    render_gallery(examples, args.output)


if __name__ == "__main__":
    main()
