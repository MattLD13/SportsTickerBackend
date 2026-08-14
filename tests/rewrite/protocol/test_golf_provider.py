"""Verify the canonical golf round label."""

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.golf import GolfProvider


class Source:
    def fetch(self, settings: DisplaySettings):
        del settings
        return {
            "content": [
                {
                    "id": "golf:1",
                    "type": "golf",
                    "sport": "golf",
                    "status": "Round 1 - In Progress",
                    "golf": {"round": "Round 1 - In Progress"},
                }
            ]
        }


def test_golf_provider_keeps_only_the_round_number() -> None:
    item = GolfProvider(Source()).fetch(DisplaySettings()).content[0]

    assert item.data["status"] == "Round 1"
    assert item.data["golf"]["round"] == "Round 1"
