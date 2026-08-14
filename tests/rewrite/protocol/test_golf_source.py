"""Verify the source-owned golf palette brand."""

from sports_ticker.providers.live_sources import _golf_brand


def test_golf_source_assigns_masters_or_pga_brand() -> None:
    assert _golf_brand("Masters Tournament") == "masters"
    assert _golf_brand("PGA Championship") == "pga"
