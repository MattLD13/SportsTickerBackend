import os
import sys
import tempfile
import shutil
import pytest

# 1. Global isolation setup: Change current working directory to a temporary folder
# so that any reads/writes to global_config.json, ticker_data/*, ticker.log,
# game_cache.json, etc. are fully isolated and do not touch production files.
ORIGINAL_CWD = os.path.abspath(os.getcwd())
if ORIGINAL_CWD not in sys.path:
    sys.path.insert(0, ORIGINAL_CWD)

TEMP_DIR = tempfile.mkdtemp(prefix="sportsticker_test_")
os.chdir(TEMP_DIR)

# Re-create ticker_data folder within the temp directory so it exists
os.makedirs("ticker_data", exist_ok=True)


def pytest_unconfigure(config):
    """Restore CWD and clean up the temporary directory after the session completes."""
    os.chdir(ORIGINAL_CWD)
    try:
        shutil.rmtree(TEMP_DIR)
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def setup_environment():
    """Session fixture to verify CWD is properly isolated and mock background services."""
    assert os.path.abspath(os.getcwd()) == os.path.abspath(TEMP_DIR)
    
    # Pre-mock background workers/updates to avoid thread starts or API calls
    import sports_ticker.workers as workers
    from unittest.mock import MagicMock
    
    workers.request_refresh = MagicMock()
    if hasattr(workers, 'flight_tracker') and workers.flight_tracker:
        workers.flight_tracker.force_update = MagicMock()
        workers.flight_tracker.fetch_airport_activity = MagicMock()
        workers.flight_tracker.fetch_visitor_tracking = MagicMock()
        
    yield


@pytest.fixture
def clean_state():
    """Reset Flask application state and ticker registers to defaults between tests."""
    from sports_ticker.core import state, default_state, tickers
    import sports_ticker.workers as workers
    from unittest.mock import MagicMock
    
    # Reset mock call histories
    workers.request_refresh.reset_mock()
    if hasattr(workers, 'flight_tracker') and workers.flight_tracker:
        workers.flight_tracker.force_update.reset_mock()
        workers.flight_tracker.fetch_airport_activity.reset_mock()
        workers.flight_tracker.fetch_visitor_tracking.reset_mock()

    state.clear()
    state.update(default_state.copy())
    tickers.clear()
    yield state


@pytest.fixture
def client(clean_state):
    """Provide a configured Flask test client."""
    from sports_ticker import create_app, create_runtime
    
    app = create_app(create_runtime())
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
