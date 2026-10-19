"""Check bounded discovery commands and sparse bootstrap dependencies."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tools.workspaces.find import main
from tools.workspaces.manage import MANIFEST, ROOT, manifest_read, resolve
from tools.workspaces.start import inventory

pytestmark = pytest.mark.critical


def test_find_lists_matching_paths_without_model_calls(monkeypatch, capsys):
    def prohibited(*_args, **_kwargs):
        raise AssertionError("Discovery started a model")
    monkeypatch.setattr("tools.workspaces.planner.run_codex", prohibited)
    assert main(["--repo", str(ROOT), "--search", "station_retry"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "esp32_hub75/src/mini/platform/station_retry.h" in data["files"]
    assert "tests/native/mini_station_retry.cpp" in data["files"]


def test_find_rejects_credential_excerpt_without_printing_source(capsys):
    assert main(["--repo", str(ROOT), "--excerpt", "esp32_hub75/src/mini/platform/config.h"]) == 1
    output = capsys.readouterr()
    assert not output.out and "outside the source index" in output.err


def test_find_reads_one_named_definition(capsys):
    assert main(["--repo", str(ROOT), "--excerpt", "tools/workspaces/start.py", "--symbol", "prepare"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["symbol_found"]
    assert "def prepare(" in data["source"]
    assert len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()) <= 6000


def test_manifest_build_set_can_import_startup_without_unselected_dependencies(tmp_path):
    manifest = manifest_read(MANIFEST)
    tracked = inventory(ROOT, manifest, "HEAD")
    selected = resolve(manifest, ["instructions"], tracked)
    expected = {"tools/workspaces/start.py", "tools/workspaces/planner.py",
                "tools/workspaces/discovery.py", "tools/workspaces/find.py"}
    assert expected <= set(selected["build_files"])
    # Copy only the declared startup closure. No credentials or production state enter this directory.
    for relative in selected["build_files"]:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    result = subprocess.run([sys.executable, "-I", "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import tools.workspaces.start, tools.workspaces.find", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_symbol_option_requires_excerpt():
    with pytest.raises(SystemExit):
        main(["--search", "station_retry", "--symbol", "render"])
