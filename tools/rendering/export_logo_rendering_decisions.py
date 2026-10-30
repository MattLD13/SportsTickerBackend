"""Export saved old/new logo choices for the ticker and review workflow."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import requests


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "server/ticker/server/projections/logo_rendering_decisions.json"
DEFAULT_TARGET_TICKER_ID = "722c59f4-fce3-4735-b072-faaa2f579a0a"
CSV_COLUMNS = (
    "target_ticker_id",
    "team_key",
    "league_id",
    "league",
    "abbr",
    "logo_url",
    "status",
    "choice",
    "old_method",
    "old_outline",
    "old_cutoff",
    "new_method",
    "new_outline",
    "new_cutoff",
    "saved_at",
)


def build_manifest(
    teams: list[dict],
    picks: dict,
    target_ticker_id: str = DEFAULT_TARGET_TICKER_ID,
) -> dict:
    """Build one rendering manifest from the live catalog and saved choices."""
    if not isinstance(teams, list) or not isinstance(picks, dict):
        raise ValueError("The comparison API returned invalid data.")

    decisions: list[dict[str, object]] = []
    for team in teams:
        league_id = str(team.get("league_id") or "").strip().lower()
        abbreviation = str(team.get("abbr") or "").strip().upper()
        if not league_id or not abbreviation:
            continue
        key = f"{league_id}:{abbreviation}"
        saved = picks.get(key)
        if not isinstance(saved, dict):
            saved = {}
        selected = str(saved.get("choice") or "").strip().lower()
        if selected not in {"old", "new"}:
            selected = ""
        legacy_outline = str(saved.get("outline") or "off").strip().lower()
        legacy_cutoff = int(saved.get("cutoff", 35))
        decision = {
            "team_key": key,
            "league_id": league_id,
            "league": str(team.get("league") or ""),
            "abbr": abbreviation,
            "logo_url": str(team.get("logo") or ""),
            "status": "saved_for_later" if selected else "unreviewed",
            "choice": selected,
            "old": {
                "method": "ticker_renderer",
                "outline": str(saved.get("old_outline") or legacy_outline),
                "cutoff": int(saved.get("old_cutoff", legacy_cutoff)),
            },
            "new": {
                "method": "native_grid",
                "outline": str(saved.get("new_outline") or legacy_outline),
                "cutoff": int(saved.get("new_cutoff", legacy_cutoff)),
            },
            "saved_at": saved.get("saved_at"),
        }
        decisions.append(decision)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_ticker_id": str(target_ticker_id).strip(),
        "count": len(decisions),
        "decisions": decisions,
    }


def export_decisions(
    base_url: str,
    output_dir: Path,
    target_ticker_id: str = DEFAULT_TARGET_TICKER_ID,
) -> tuple[Path, Path, int]:
    """Fetch live choices and write JSON and CSV exports."""
    base_url = base_url.rstrip("/")
    teams_response = requests.get(f"{base_url}/api/catalog", timeout=30)
    teams_response.raise_for_status()
    picks_response = requests.get(f"{base_url}/api/comparison-picks", timeout=30)
    picks_response.raise_for_status()
    export = build_manifest(teams_response.json(), picks_response.json(), target_ticker_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(export, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    decisions = export["decisions"]
    flat_rows = [
        {
            "team_key": item["team_key"],
            "target_ticker_id": export["target_ticker_id"],
            "league_id": item["league_id"],
            "league": item["league"],
            "abbr": item["abbr"],
            "logo_url": item["logo_url"],
            "status": item["status"],
            "choice": item["choice"],
            "old_method": item["old"]["method"],
            "old_outline": item["old"]["outline"],
            "old_cutoff": item["old"]["cutoff"],
            "new_method": item["new"]["method"],
            "new_outline": item["new"]["outline"],
            "new_cutoff": item["new"]["cutoff"],
            "saved_at": item["saved_at"],
        }
        for item in decisions
    ]
    download = {
        "schema_version": export["schema_version"],
        "generated_at": export["generated_at"],
        "target_ticker_id": export["target_ticker_id"],
        "count": len(flat_rows),
        "decisions": flat_rows,
    }
    download_json_path = output_dir / "logo-rendering-decisions.json"
    download_json_path.write_text(json.dumps(download, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    csv_path = output_dir / "logo-rendering-decisions.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(flat_rows)
    return download_json_path, csv_path, len(flat_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output-dir", type=Path, default=Path.home() / "Downloads")
    parser.add_argument("--target-ticker-id", default=DEFAULT_TARGET_TICKER_ID)
    args = parser.parse_args()
    try:
        json_path, csv_path, count = export_decisions(args.base_url, args.output_dir, args.target_ticker_id)
    except (OSError, requests.RequestException, ValueError) as error:
        print(f"Could not export logo decisions: {error}", file=sys.stderr)
        return 1
    print(f"Exported {count} logos")
    print(json_path)
    print(csv_path)
    print(MANIFEST_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
