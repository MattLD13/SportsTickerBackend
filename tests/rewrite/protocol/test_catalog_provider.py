"""Verify the controller receives current college conference options."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from sports_ticker.leagues import TEAM_CATALOG_PATHS
from sports_ticker.providers.catalog import EspnTeamCatalog


pytestmark = pytest.mark.critical


class ConferenceCatalogClient:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.children = {"80": ("4", "1"), "81": ("20", "32")}
        self.labels = {
            "1": "ACC",
            "4": "Big 12",
            "20": "Big Sky",
            "32": "FCS Independents",
        }

    def get_json(self, url: str, *, timeout: float):
        del timeout
        self.urls.append(url)
        if "site.web.api.espn.com" in url:
            return {
                "sports": [
                    {
                        "leagues": [
                            {
                                "season": {"year": 2026},
                                "teams": [],
                            }
                        ]
                    }
                ]
            }
        path = urlparse(url).path
        if path.endswith("/groups/80/children"):
            group = "80"
        elif path.endswith("/groups/81/children"):
            group = "81"
        else:
            group = path.rstrip("/").rpartition("/")[2]
        if path.endswith("/children"):
            return {
                "items": [
                    {
                        "$ref": (
                            "http://sports.core.api.espn.com/v2/sports/football/"
                            f"leagues/college-football/seasons/2026/types/2/groups/{group_id}"
                        )
                    }
                    for group_id in self.children[group]
                ]
            }
        return {
            "id": group,
            "isConference": True,
            "midsizeName": self.labels[group],
        }


def test_college_conferences_are_existing_controller_league_options() -> None:
    client = ConferenceCatalogClient()
    catalog = EspnTeamCatalog(TEAM_CATALOG_PATHS, client=client, cache_seconds=60)

    values = {item["id"]: item for item in catalog.leagues()}

    assert values["ncf_fbs"]["my_teams_enabled"] is True
    assert values["ncf_fbs:1"] == {
        "id": "ncf_fbs:1",
        "label": "NCAA (FBS) / ACC",
        "type": "sport",
        "enabled": True,
        "my_teams_enabled": False,
        "conference_id": "1",
        "conference_parent": "ncf_fbs",
    }
    assert values["ncf_fbs:4"]["label"] == "NCAA (FBS) / Big 12"
    assert values["ncf_fcs:20"]["label"] == "NCAA (FCS) / Big Sky"
    assert values["ncf_fcs:32"]["my_teams_enabled"] is False
    assert "conferences" not in values["ncf_fbs"]
    assert "conferences" not in values["nfl"]

    first_call_count = len(client.urls)
    catalog.leagues()
    assert len(client.urls) == first_call_count
