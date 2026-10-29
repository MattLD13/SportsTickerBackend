import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from backend_ops.components import import_closures, packaged
from backend_ops.worker_contract import PROVIDERS

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import json, pathlib, sys, tempfile
import backend_ops.worker
from sports_ticker.providers.factory import create_provider
create_provider(sys.argv[1], database_path=pathlib.Path(tempfile.mkdtemp()) / "ticker.sqlite3")
print(json.dumps(sorted(name for name in sys.modules if name.split(".")[0] in ("sports_ticker", "ticker_core", "backend_ops"))))
"""


def _module_file(name):
    base = ROOT.joinpath(*name.split("."))
    path = base / "__init__.py" if (base / "__init__.py").exists() else base.with_suffix(".py")
    return path.relative_to(ROOT).as_posix()


@pytest.mark.critical
@pytest.mark.parametrize("component", PROVIDERS)
def test_each_worker_package_carries_its_import_closure(component):
    closure = import_closures(ROOT)[component]

    assert "backend_ops/worker.py" in closure
    assert not [path for path in closure if not packaged(component, path)]


@pytest.mark.critical
def test_core_closure_excludes_the_worker_factory_branches():
    core = import_closures(ROOT)["core"]

    assert "sports_ticker/server.py" in core
    assert "sports_ticker/providers/weather_location.py" in core
    assert not {"sports_ticker/providers/espn.py", "sports_ticker/providers/racing_live.py",
                "sports_ticker/providers/weather.py", "sports_ticker/providers/news_source.py"} & core


@pytest.mark.parametrize("component", PROVIDERS)
def test_static_worker_closure_covers_every_module_the_worker_loads(component, tmp_path):
    environment = {
        **os.environ,
        "SPOTIFY_CLIENT_ID": "client",
        "SPOTIFY_CALLBACK_URI": "https://example.com/callback",
        "SPOTIFY_APP_RETURN_URI": "sportsticker://spotify",
        "SPOTIFY_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    completed = subprocess.run([sys.executable, "-c", PROBE, component], cwd=ROOT, env=environment,
                               capture_output=True, text=True, timeout=120)

    assert completed.returncode == 0, completed.stderr
    loaded = {_module_file(name) for name in json.loads(completed.stdout.splitlines()[-1])}
    assert loaded <= import_closures(ROOT)[component], sorted(loaded - import_closures(ROOT)[component])
