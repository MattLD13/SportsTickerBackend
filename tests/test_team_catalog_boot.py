"""Startup behavior for the team-selection catalog."""

from unittest.mock import MagicMock, patch


def test_startup_refreshes_team_catalog_before_workers_start():
    """Load current division rosters before worker threads run."""
    import sports_ticker.workers as workers

    old_started = workers._background_workers_started
    workers._background_workers_started = False
    mock_fetch = MagicMock(return_value=True)

    try:
        with patch.object(workers.fetcher, 'fetch_all_teams', mock_fetch), \
             patch('sports_ticker.workers.threading.Thread') as thread, \
             patch.object(workers.spotify_fetcher, 'start'), \
             patch.object(workers, 'purge_stale_tickers'), \
             patch.object(workers, 'request_refresh'):
            workers.start_background_workers()

        mock_fetch.assert_called_once_with()
        assert thread.call_count == 6
    finally:
        workers._background_workers_started = old_started
