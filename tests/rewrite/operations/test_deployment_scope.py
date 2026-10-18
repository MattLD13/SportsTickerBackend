import json
from pathlib import Path
import subprocess

import pytest

from tools.deployment_scope import recovery_needed

pytestmark = pytest.mark.critical


def test_recovery_compares_backend_changes_only(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    def commit(path, text):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git("add", path)
        git("commit", "-m", "Update fixture")
        return git("rev-parse", "HEAD")

    git("init")
    git("config", "user.name", "Deployment Test")
    git("config", "user.email", "deployment@example.invalid")
    scope = Path(__file__).resolve().parents[3] / ".github/deployment-paths.json"
    commit(".github/deployment-paths.json", scope.read_text(encoding="utf-8"))
    deployed = commit("sports_ticker/server.py", "version = 1")
    commit("docs/report.md", "Report")
    commit("esp32_hub75/src/main.cpp", "Mini")
    commit("TickerControlApp/View.swift", "App")
    commit("docs/example.json", json.dumps({"example": True}))
    assert not recovery_needed(tmp_path, deployed[:7])
    documentation_deploy = git("rev-parse", "HEAD")
    commit("docs/report.md", "Updated report")
    assert not recovery_needed(tmp_path, documentation_deploy)
    commit("configuration.json", "{}")
    assert recovery_needed(tmp_path, deployed)
    deployed = git("rev-parse", "HEAD")
    commit("sports_ticker/server.py", "version = 2")
    assert recovery_needed(tmp_path, deployed)
    assert not recovery_needed(tmp_path, git("rev-parse", "HEAD"))
    assert recovery_needed(tmp_path, "unknown")
    assert recovery_needed(tmp_path, "f" * 40)
    for path in ("esp32_hub75/src/mini/rendering/music_pane.h", "docs/contracts/demo-layouts.json", "tools/render_mini_ui.cpp"):
        deployed = git("rev-parse", "HEAD")
        commit(path, "Updated demo source")
        assert recovery_needed(tmp_path, deployed)
