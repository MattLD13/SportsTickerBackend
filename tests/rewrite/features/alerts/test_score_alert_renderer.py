"""Verify baseball inning markers in score-alert banners."""

from ticker_core.features.alerts.score_alert_port import PreparedScoreAlertRenderer
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
