"""Verify baseball inning markers in score-alert banners."""

from ticker_core.features.alerts.score_alert_port import PreparedScoreAlertRenderer, score_alert_duration
from ticker_core.features.alerts.news_banner_port import PreparedNewsBannerRenderer
from ticker_core.rendering import load_default_font_set


class EmptyLogos:
    """Provide deterministic missing logos."""

    def get(self, url, size):
        del url, size
        return None


def test_baseball_alert_shows_top_bottom_and_mid_inning_markers() -> None:
    renderer = PreparedScoreAlertRenderer(load_default_font_set(), EmptyLogos())

    assert renderer._alert_status_label({"sport": "mlb", "status": "Top 7th"}) == ("▲", "7")
    assert renderer._alert_status_label({"sport": "mlb", "status": "Bottom 7th"}) == ("▼", "7")
    assert renderer._alert_status_label({"sport": "mlb", "status": "Mid 7th"}) == ("-", "7")


def test_baseball_alert_keeps_final_status_without_an_inning_marker() -> None:
    renderer = PreparedScoreAlertRenderer(load_default_font_set(), EmptyLogos())

    assert renderer._alert_status_label({"sport": "mlb", "status": "Final"}) == ("", "FINAL")


def test_score_alert_render_duration_matches_runtime_residence() -> None:
    assert score_alert_duration({"big": False}) == 8.0
    assert score_alert_duration({"big": True}) == 8.0


def test_sports_news_kinds_use_distinct_banner_accents() -> None:
    renderer = PreparedNewsBannerRenderer()
    colors = [
        renderer.draw_news_banner({
            "kind": kind,
            "from_abbr": "VAN",
            "to_abbr": "NYR",
            "text": "ACQUIRE PLAYER",
        }).getpixel((0, 0))
        for kind in ("TRADE", "SIGNING", "EXTENSION", "INJURY")
    ]

    assert len(set(colors)) == 4
