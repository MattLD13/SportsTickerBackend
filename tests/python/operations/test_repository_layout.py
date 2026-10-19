"""Protect current repository entry points and focused deployment sections."""
from pathlib import Path
import subprocess

import pytest

from tools.deployment.change_scope import mini_code_changed

pytestmark = pytest.mark.critical


def test_firmware_comments_do_not_request_a_replacement_release(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()
    git("init")
    git("config", "user.name", "Scope Test")
    git("config", "user.email", "scope@example.invalid")
    source = tmp_path / "esp32_hub75/src/panel.h"
    source.parent.mkdir(parents=True)
    source.write_text("// Old generator path\nconst int width = 64;\n")
    git("add", ".")
    git("commit", "-m", "Record source")
    baseline = git("rev-parse", "HEAD")
    source.write_text("// New generator path\nconst int width = 64;\n")
    git("add", ".")
    git("commit", "-m", "Update comment")
    assert not mini_code_changed(tmp_path, baseline)
    (tmp_path / "esp32_hub75/README.md").write_text("Updated tool locations\n")
    git("add", ".")
    git("commit", "-m", "Update documentation")
    assert not mini_code_changed(tmp_path, baseline)
    source.write_text("// New generator path\nconst int width = 32;\n")
    git("add", ".")
    git("commit", "-m", "Update width")
    assert mini_code_changed(tmp_path, baseline)


def test_current_layout_has_one_owner_for_tests_tools_and_backend_units():
    for path in ("tests/python", "tests/fixtures/display", "tools/rendering", "tools/mini", "tools/deployment", "deploy/backend"):
        assert Path(path).is_dir()
    workflow = Path(".github/workflows/deploy.yml").read_text()
    for family in ("Ticker Server /", "Ticker Mini /", "Ticker Six /"):
        assert family in workflow
    assert "  validate:" in workflow and "  publish:" in workflow
    assert "  build-mini-firmware:" not in workflow
    assert "  deploy-backend:" not in workflow
    assert "cp deploy/backend/* deployment-staging/" in workflow
