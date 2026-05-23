# SportsTickerBackend Testing Guide

This project includes a robust, isolated unit and integration testing suite built on **pytest**. The testing suite is designed to verify the core state machines, API routes, data pairing workflows, and fetcher parsing logic without hitting live APIs or impacting your production config/data files.

---

## Quickstart

### 1. Install Testing Dependencies
To install the required testing dependencies in your virtual environment:

```bash
.venv\Scripts\pip install pytest pytest-mock pytest-cov responses
```

### 2. Run the Entire Test Suite
Execute the entire test suite from the root of the workspace:

```bash
.venv\Scripts\pytest
```

### 3. Run with Coverage Reporting
Generate a code coverage report for the `sports_ticker` backend package:

```bash
.venv\Scripts\pytest --cov=sports_ticker tests/
```

---

## Test Organization

The tests are located in the `tests/` directory:

```
tests/
├── conftest.py         # Global test configuration, environment isolation, and fixtures
├── test_core.py        # Core state, normalization, purging, and pairing logic tests
├── test_routes.py      # Flask API route, configuration updates, and security tests
└── test_fetchers.py    # TestMode, WeatherFetcher, and StockFetcher parsing & simulation tests
```

---

## Architecture & Isolation Design

### 1. Filesystem Isolation
To prevent tests from creating or modifying production files (like `global_config.json`, `game_cache.json`, or ticker databases in `ticker_data/`), `tests/conftest.py` configures a **session-wide temporary directory**.
- Before any package imports, the working directory is changed to a temporary path (`pytest`'s temp directory).
- All relative file reads/writes automatically redirect to this temp directory.
- The temp folder is automatically deleted when the test session ends.

### 2. Background Thread Prevention
The Sports Ticker server starts background worker threads in production to poll APIs. During testing, calling `create_app()` does **not** launch background threads. Additionally, `conftest.py` pre-mocks the `request_refresh` queue and flight tracker update triggers so that tests run completely synchronously and without side effects.

### 3. Network Mocking
We use the `responses` library to intercept HTTP requests made by fetchers. This ensures that the fetcher integration tests run **completely offline, deterministic, and fast**.

---

## Writing New Tests

### Fixtures

- **`clean_state`**: Resets the global Flask config, default state, and registered tickers dictionary before and after each test.
- **`client`**: Yields a pre-configured Flask test client using the application's runtime.

### Example: Testing a New Route

```python
def test_my_new_endpoint(client, clean_state):
    # Set up some state
    from sports_ticker.core import state
    state["debug_mode"] = True
    
    # Make request
    response = client.get("/my/new/endpoint")
    
    # Assertions
    assert response.status_code == 200
    assert response.get_json() == {"success": True}
```

### Example: Mocking an External HTTP Fetch

```python
import responses

@responses.activate
def test_my_fetcher():
    # Register mock endpoint
    responses.add(
        responses.GET,
        "https://api.external.com/data",
        json={"status": "all-green"},
        status=200
    )
    
    # Run fetcher code
    # ...
```

---

## Visual & Hardware Verification

Since the display target is `384x32` pixels, visual layout details are extremely important. Use the local render utilities for visual checks before pushing code changes:

- **Render racing previews**:
  ```bash
  python tools\render_racing_previews.py --mode both --out-dir previews
  ```
- **Render a live frame snapshot**:
  ```bash
  python tools\fetch_and_render.py --mode indycar --view pin --save indycar_pin_live.png
  ```
