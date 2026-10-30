"""Prove that the static import graph covers every module that each process really loads."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from ticker.ops.components import WORKERS, import_closures

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ("ticker",)

WORKER_PROBE = """
import json, pathlib, sys, tempfile
import ticker.server.worker.__main__
from ticker.server.providers.factory import create_provider
create_provider(sys.argv[1], database_path=pathlib.Path(tempfile.mkdtemp()) / "ticker.sqlite3")
print(json.dumps(sorted(name for name in sys.modules if name.split(".")[0] in %r)))
""" % (PACKAGES,)

CORE_PROBE = """
import json, sys
from ticker.server.main import create_asgi_application
create_asgi_application(sys.argv[1])
print(json.dumps(sorted(name for name in sys.modules if name.split(".")[0] in %r)))
""" % (PACKAGES,)

# The core loads only these provider modules. Each worker owns every other provider module.
CORE_PROVIDER_MODULES = {
    "__init__", "catalog", "clock", "contracts", "http", "logo_overrides", "normalization", "stock_catalog", "weather_location",
}


def _module_file(name):
    """Return the source file of a module, or None for a namespace package."""
    base = ROOT.joinpath(*name.split("."))
    path = base / "__init__.py" if (base / "__init__.py").exists() else base.with_suffix(".py")
    return path.relative_to(ROOT).as_posix() if path.exists() else None


def _loaded(tmp_path, probe, argument):
    environment = {
        **os.environ,
        "TICKER3_SOCKET": str(tmp_path / "t.sock"),
        "SPOTIFY_CLIENT_ID": "client",
        "SPOTIFY_CALLBACK_URI": "https://example.com/spotify/callback",
        "SPOTIFY_APP_RETURN_URI": "sportsticker://spotify",
        "SPOTIFY_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    completed = subprocess.run([sys.executable, "-c", probe, argument], cwd=ROOT, env=environment,
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr
    return {_module_file(name) for name in json.loads(completed.stdout.splitlines()[-1])} - {None}


@pytest.mark.critical
def test_core_closure_excludes_the_worker_factory_branches():
    core = import_closures(ROOT)["core"]
    assert {"ticker/server/main.py", "ticker/server/api/asgi.py", "ticker/server/providers/weather_location.py"} <= core
    assert not {"ticker/server/providers/espn.py", "ticker/server/providers/racing_live.py", "ticker/server/providers/weather.py",
                "ticker/server/providers/news_source.py", "ticker/server/providers/factory.py"} & core


@pytest.mark.critical
@pytest.mark.parametrize("component", WORKERS)
def test_workers_load_no_server_application_code(component):
    closure = import_closures(ROOT)[component]
    assert "ticker/server/worker/runner.py" in closure
    assert not [path for path in closure if path.startswith(("ticker/server/api/", "ticker/server/web/", "ticker/server/core/",
                                                             "ticker/server/services/", "ticker/server/projections/",
                                                             "ticker/six/"))]


@pytest.mark.critical
def test_the_core_process_loads_only_core_provider_modules(tmp_path):
    loaded = _loaded(tmp_path, CORE_PROBE, str(tmp_path / "ticker.sqlite3"))
    providers = {Path(path).stem for path in loaded if path.startswith("ticker/server/providers/")}
    assert providers <= CORE_PROVIDER_MODULES, sorted(providers - CORE_PROVIDER_MODULES)
    assert {"contracts", "normalization", "clock"} <= providers
    assert "ticker/shared/sports_display.py" in loaded
    assert loaded <= import_closures(ROOT)["core"], sorted(loaded - import_closures(ROOT)["core"])


@pytest.mark.parametrize("component", WORKERS)
def test_static_worker_closure_covers_every_module_the_worker_loads(component, tmp_path):
    loaded = _loaded(tmp_path, WORKER_PROBE, component)
    assert loaded <= import_closures(ROOT)[component], sorted(loaded - import_closures(ROOT)[component])
