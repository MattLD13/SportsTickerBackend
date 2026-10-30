"""Verify pinned Git workspaces, expansion records, and ordinary staging."""
import json
from pathlib import Path
import sys

import pytest

from tools.workspaces.manage import (
    MANIFEST, ROOT, WorkspaceError, audit, create, expand, git, load,
    input_digest, main, manifest_read, resolve, run_check, safe_path, select, tree,
)
from tools.workspaces.start import inventory

pytestmark = pytest.mark.critical


def test_local_inventory_excludes_deleted_files_without_changing_the_revision_tree(source):
    root, base, path = source
    (root / "mini/pane.h").unlink()
    assert "mini/pane.h" in tree(root, base)
    assert "mini/pane.h" not in inventory(root, manifest_read(path), base)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Workspace Test")
    git(root, "config", "user.email", "workspace@example.invalid")
    git(root, "config", "uploadpack.allowFilter", "true")
    files = {"AGENTS.md": "Read the contract.\n", "mini/pane.h": "int score = 1;\n",
             "mini/AGENTS.md": "Render without I/O.\n", "shared/model.py": "SCORE = 1\n",
             "six/pane.py": "SCORE = 1\n", "ios/model.swift": "let score = 1\n",
             "unrelated/file.py": "VALUE = 5\n", "test_score.py": "assert 1 + 1 == 2\n",
             ".env": "SYNTHETIC_TEST_ONLY=1\n"}
    for name, value in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "Record test source")
    base = git(root, "rev-parse", "HEAD").strip()
    (root / "mini/pane.h").write_text("int score = 2;\n", encoding="utf-8")
    git(root, "commit", "--quiet", "-am", "Advance remote source")
    components = {
        "server-core": {"owner": "Shared contract", "owned": ["shared/*"],
                        "context": ["shared/model.py"], "build": ["AGENTS.md", "test_score.py"], "checks": ["test"]},
        "sports-server": {"owner": "Sports facts", "dependencies": ["server-core"]},
        "mini-firmware": {"owner": "Mini", "owned": ["mini/*"], "dependencies": ["sports-server"],
                          "context": ["mini/pane.h"]},
        "six-runtime": {"owner": "Six", "owned": ["six/*"], "context": ["six/pane.py"]},
        "app-contracts": {"owner": "App", "owned": ["ios/*"], "context": ["ios/model.swift"]},
    }
    manifest = {"version": 1, "components": components, "slices": {"mini-sports": ["mini-firmware"]},
                "shared_owners": ["server-core", "sports-server"],
                "shared_consumers": ["mini-firmware", "six-runtime", "app-contracts"],
                "checks": {"test": {"argv": ["{python}", "test_score.py"], "files": ["test_score.py"]}}}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return root, base, path


def prepare(source, tmp_path):
    root, base, manifest = source
    destination = tmp_path / "workspace"
    state = create(destination, root.as_uri(), base, manifest, "mini-sports", "Fix shootout rendering")
    return destination, state


def test_pin_filter_packet_and_staging_preserve_omitted_files(source, tmp_path):
    destination, state = prepare(source, tmp_path)
    assert git(destination, "rev-parse", "HEAD").strip() == source[1]
    assert (destination / "mini/pane.h").read_text() == "int score = 1;\n"
    assert not (destination / "six/pane.py").exists()
    assert not (destination / ".env").exists()
    excluded_blob = git(source[0], "rev-parse", f"{source[1]}:.env").strip()
    missing = git(destination, "rev-list", "--objects", "--missing=print", source[1])
    assert "?" + excluded_blob in missing
    assert "mini/AGENTS.md" in state["context_files"]
    assert state["filter_supported"]
    git(destination, "add", "-A")
    assert git(destination, "diff", "--cached", "--name-status") == ""
    (destination / "mini/pane.h").write_text("int score = 7;\n")
    git(destination, "add", "-A")
    assert git(destination, "diff", "--cached", "--name-status").strip() == "M\tmini/pane.h"
    assert audit(destination)["changed_files"] == ["mini/pane.h"]
    packet = Path(git(destination, "rev-parse", "--absolute-git-dir").strip()) / "agent-workspace/task.md"
    assert "Fix shootout rendering" in packet.read_text()
    assert "six/pane.py" not in packet.read_text()


def test_expansion_preserves_dirty_files_and_records_reason(source, tmp_path):
    destination, _ = prepare(source, tmp_path)
    (destination / "mini/pane.h").write_text("int score = 9;\n")
    state = expand(destination, ["six-runtime"], [], "Check both renderers")
    assert (destination / "mini/pane.h").read_text() == "int score = 9;\n"
    assert (destination / "six/pane.py").is_file()
    assert state["expansions"][0]["reason"] == "Check both renderers"
    assert state["expansions"][0]["files"] == ["six/pane.py"]
    assert "six/pane.py" not in state["initial_context_files"]
    assert audit(destination)["ok"]


def test_shared_edits_require_every_consumer_even_after_commit(source, tmp_path):
    destination, _ = prepare(source, tmp_path)
    git(destination, "config", "user.name", "Workspace Test")
    git(destination, "config", "user.email", "workspace@example.invalid")
    (destination / "shared/model.py").write_text("SCORE = 4\n")
    git(destination, "add", "-A")
    git(destination, "commit", "--quiet", "-m", "Change the shared contract")
    assert not audit(destination)["ok"]
    state = expand(destination, ["sports-server"], [], "Validate the changed contract in each consumer")
    assert set(state["components"]) >= {"mini-firmware", "six-runtime", "app-contracts"}
    assert audit(destination)["ok"]


def test_new_files_and_unknown_ownership_expand_conservatively(source, tmp_path):
    destination, _ = prepare(source, tmp_path)
    state = expand(destination, [], ["mini/new.h"], "Add a pane helper")
    (destination / "mini/new.h").write_text("int width = 64;\n")
    assert audit(destination)["ok"]
    state = expand(destination, [], ["unrelated/file.py"], "Inspect an unclassified import")
    assert "six-runtime" in state["components"] and "app-contracts" in state["components"]
    assert "unrelated/file.py" in state["expansions"][-1]["files"]
    (destination / "mini/unrecorded.h").write_text("int width = 32;\n")
    assert not audit(destination)["ok"]


@pytest.mark.parametrize("path", ["../secret", "/absolute", "C:/secret", ".git/config", ".env",
                                 "ticker_data/state.json", "logs/device.log", "keys/device.pem",
                                 "esp32_hub75/src/mini/platform/config.h", "mini/./a.h", "mini/*.h"])
def test_private_runtime_and_unsafe_paths_are_rejected(path):
    with pytest.raises(WorkspaceError):
        safe_path(path)


def test_checks_record_commands_results_and_failures(source, tmp_path):
    destination, _ = prepare(source, tmp_path)
    assert run_check(destination, "test") == 0
    (destination / "test_score.py").write_text("raise SystemExit(3)\n")
    # Unknown ownership requires every consumer before this test changes.
    expand(destination, ["sports-server"], [], "Validate test changes across consumers")
    assert run_check(destination, "test") == 3
    location, state, _ = load(destination)
    assert [entry["exit_code"] for entry in state["runs"]] == [0, 3]
    assert state["runs"][0]["argv"][0] == sys.executable
    assert (location / state["runs"][0]["log"]).is_file()


def test_reject_existing_destination_bad_sha_and_manifest_mutation(source, tmp_path):
    destination, _ = prepare(source, tmp_path)
    with pytest.raises(WorkspaceError, match="already exists"):
        create(destination, source[0].as_uri(), source[1], source[2], "mini-sports", "task")
    with pytest.raises(WorkspaceError, match="40-character"):
        create(tmp_path / "bad", source[0].as_uri(), "main", source[2], "mini-sports", "task")
    location, _, _ = load(destination)
    (location / "manifest.json").write_text(json.dumps({"version": 1}))
    with pytest.raises(WorkspaceError, match="manifest changed"):
        load(destination)


def test_filter_capability_is_required_before_fetch(source, tmp_path):
    root, base, manifest = source
    git(root, "config", "uploadpack.allowFilter", "false")
    destination = tmp_path / "unfiltered"
    with pytest.raises(WorkspaceError, match="no blob filter"):
        create(destination, root.as_uri(), base, manifest, "mini-sports", "task")
    assert not destination.exists()


def test_manifest_slice_paths_checks_and_initial_context_are_real():
    manifest = manifest_read(MANIFEST)
    tracked = inventory(ROOT, manifest, "HEAD")
    for name in manifest["slices"]:
        plan = resolve(manifest, select(manifest, name, False), tracked)
        assert all((ROOT / path).is_file() for path in plan["build_files"])
    plan = resolve(manifest, select(manifest, "mini-sports", False), tracked)
    assert "tests/native/mini_hockey_panes.cpp" in plan["context_files"]
    assert not any(path.startswith(("TickerControlApp/", "ticker_core/ui/", "ticker3/web/"))
                   for path in plan["context_files"])
    assert not any(any(word in path for word in ("music", "weather", "stocks", "flights"))
                   for path in plan["context_files"])
    assert "esp32_hub75/src/mini/platform/config.h" not in plan["build_files"]
    assert not any(path.startswith("ticker_core/ui/sports/") for path in plan["build_files"])


def test_manifest_cycles_and_empty_patterns_fail(source):
    manifest = manifest_read(source[2])
    manifest["components"]["server-core"]["dependencies"] = ["mini-firmware"]
    with pytest.raises(WorkspaceError, match="cycle"):
        resolve(manifest, ["mini-firmware"], tree(source[0], source[1]))
    manifest = manifest_read(source[2])
    manifest["components"]["server-core"]["build"] += ["missing.py"]
    with pytest.raises(WorkspaceError, match="no files"):
        resolve(manifest, ["mini-firmware"], tree(source[0], source[1]))


def test_cli_rejects_non_github_credentials(tmp_path):
    assert main(["create", "--slice", "mini-sports", "--sha", "a" * 40, "--dest", str(tmp_path / "out"),
                 "--task", "task", "--remote", "https://token@github.com/org/repo.git"]) == 2


def test_check_input_digest_includes_new_files_and_staged_content(source, tmp_path):
    destination, _ = prepare(source, tmp_path)
    state = expand(destination, [], ["mini/new.h"], "Add a pane helper")
    before = input_digest(destination, state)
    (destination / "mini/new.h").write_text("int width = 64;\n")
    added = input_digest(destination, state)
    assert before != added
    git(destination, "add", "mini/new.h")
    assert input_digest(destination, state) != added
