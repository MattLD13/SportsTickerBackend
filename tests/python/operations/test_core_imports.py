import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

pytestmark = pytest.mark.critical

# Core owns these provider modules. Each worker owns every other provider module.
CORE_PROVIDER_MODULES = {
    "catalog", "contracts", "http", "logo_overrides", "normalization", "payloads",
    "racing_session", "sports_display", "stock_catalog", "weather_location",
}

PROBE = """
import json, sys
from sports_ticker.production import create_production_application
create_production_application(sys.argv[1])
prefix = "sports_ticker.providers."
print(json.dumps(sorted(name[len(prefix):] for name in sys.modules if name.startswith(prefix))))
"""


def test_core_with_worker_processes_loads_only_core_provider_modules(tmp_path):
    environment = {
        **os.environ,
        "TICKER_WORKER_DIRECTORY": str(tmp_path / "sockets"),
        "SPOTIFY_CLIENT_ID": "client",
        "SPOTIFY_CALLBACK_URI": "https://example.com/callback",
        "SPOTIFY_APP_RETURN_URI": "sportsticker://spotify",
        "SPOTIFY_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    completed = subprocess.run(
        [sys.executable, "-c", PROBE, str(tmp_path / "ticker.sqlite3")],
        cwd=Path(__file__).resolve().parents[3], env=environment, capture_output=True, text=True, timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    loaded = set(json.loads(completed.stdout.splitlines()[-1]))
    assert loaded <= CORE_PROVIDER_MODULES, sorted(loaded - CORE_PROVIDER_MODULES)
    assert {"contracts", "normalization", "sports_display"} <= loaded
