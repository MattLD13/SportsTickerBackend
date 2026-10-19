"""Verify automatic task packets and agent instruction entry points."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from tools.workspaces.manage import MANIFEST, ROOT, WorkspaceError, git, manifest_read, safe_path
from tools.workspaces.start import edit_owners, hook, inventory, main, prepare
from tools.workspaces.planner import MODEL, VERSION

pytestmark = pytest.mark.critical


def decision(slices, paths):
    return {"phase": "ready", "slices": slices,
            "context": [{"path": path, "symbols": [], "reason": "Relevant source"} for path in paths],
            "edit_targets": [], "inspect": [], "checks": [], "shared_change": False,
            "reason": "Focused task scope", "evidence": {"kind": "luna", "model": MODEL, "version": VERSION,
            "seconds": 0, "rounds": 1, "usage": {}, "inspected_files": []}}


@pytest.fixture
def planner_calls(monkeypatch):
    queued, calls = [], []
    def planner(root, task, manifest, tracked, previous=None):
        calls.append(task)
        assert queued, "The test did not provide a planner decision"
        return queued.pop(0)
    monkeypatch.setattr("tools.workspaces.start.plan_task", planner)
    return queued, calls


def test_shared_edit_guards_include_consumers():
    manifest = manifest_read(MANIFEST)
    required = edit_owners(manifest, ["sports_ticker/domain/models.py"], False)
    assert set(manifest["shared_consumers"]) <= required
    assert set(manifest["shared_consumers"]) <= edit_owners(manifest, ["unknown/helper.py"], False)
    with pytest.raises(WorkspaceError):
        edit_owners(manifest, [".env"], False)


@pytest.fixture
def session_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Context Test")
    git(root, "config", "user.email", "context@example.invalid")
    sources = {"AGENTS.md": "Read the task packet.\n", "mini/pane.h": "int score = 1;\n",
               "music/song.py": "TITLE = 'Sample'\n", "shared/model.py": "SCORE = 1\n"}
    for name, text in sources.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    manifest = {"version": 1, "components": {
        "mini": {"owner": "Mini", "context": ["mini/pane.h"], "build": []},
        "music": {"owner": "Music", "context": ["music/song.py"], "build": []},
        "shared": {"owner": "Shared", "context": ["shared/model.py"], "build": []},
    }, "slices": {"mini-sports": ["mini"], "mini-runtime": ["mini"], "music": ["music"],
                  "mini-music": ["mini", "music"], "shared-sports": ["shared", "mini", "music"]},
        "checks": {}, "shared_owners": ["shared"], "shared_consumers": ["mini", "music"]}
    path = root / ".github/agent-workspaces.json"
    path.parent.mkdir()
    path.write_text(json.dumps(manifest))
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "Record context fixture")
    return root


def test_packets_preserve_dirty_source_and_exclude_raw_prompts(session_repo, planner_calls):
    planner_calls[0].append(decision(["mini-sports"], ["mini/pane.h"]))
    root = session_repo
    path = root / "mini/pane.h"
    path.write_text("int score = 9;\n")
    before = git(root, "diff", "--binary")
    task = "Fix Mini hockey. Private task note: synthetic-secret-do-not-copy"
    result = prepare(root, task, "agent-a")
    assert result["slices"] == ["mini-sports"]
    assert result["checkout_kind"] == "existing_checkout"
    assert git(root, "diff", "--binary") == before
    packet = Path(result["packet"])
    assert "music/song.py" not in packet.read_text()
    assert "synthetic-secret" not in packet.read_text()
    state = json.loads(packet.with_name("state.json").read_text())
    assert state["task_sha256"] == hashlib.sha256(task.encode()).hexdigest()
    assert "synthetic-secret" not in packet.with_name("state.json").read_text()
    assert git(root, "status", "--porcelain").strip() == "M mini/pane.h"


def test_followups_preserve_scope_and_independent_agents_stay_separate(session_repo, planner_calls):
    planner_calls[0].extend([decision(["mini-sports"], ["mini/pane.h"]),
        decision(["mini-music"], ["music/song.py"]), decision(["music"], ["music/song.py"]),
        decision(["music"], ["music/song.py"])])
    first = prepare(session_repo, "Fix Mini hockey", "agent-a")
    assert prepare(session_repo, "continue", "agent-a")["slices"] == first["slices"]
    assert prepare(session_repo, "What about shootout timing?", "agent-a")["slices"] == first["slices"]
    broadened = prepare(session_repo, "Also fix music", "agent-a", replan=True)
    assert broadened["slices"] == ["mini-music", "mini-sports"]
    second = prepare(session_repo, "Fix music", "agent-b")
    assert second["slices"] == ["music"]
    assert second["packet"] != first["packet"]
    reset = prepare(session_repo, "Fix music", "agent-a", new_task=True)
    assert reset["slices"] == ["music"]


@pytest.mark.parametrize("client,event", [("codex", "UserPromptSubmit"), ("claude", "UserPromptSubmit"),
                                         ("gemini", "BeforeAgent")])
def test_prompt_hooks_prepare_packets_before_planning(session_repo, client, event, planner_calls):
    planner_calls[0].append(decision(["mini-sports"], ["mini/pane.h"]))
    payload = {"hook_event_name": event, "cwd": str(session_repo), "session_id": "sample", "prompt": "Fix Mini hockey"}
    result = hook(payload, client)["hookSpecificOutput"]
    assert result["hookEventName"] == event
    assert "mini-sports" in result["additionalContext"]
    assert "task.md" in result["additionalContext"]
    assert git(session_repo, "status", "--porcelain") == ""
    resumed = hook({**payload, "hook_event_name": "SessionStart"}, client)
    assert "Resume the task packet" in resumed["hookSpecificOutput"]["additionalContext"]


def test_configured_session_commands_execute_from_a_nested_directory(tmp_path):
    for client, config_path, event in (("codex", ".codex/hooks.json", "UserPromptSubmit"),
                                        ("claude", ".claude/settings.json", "UserPromptSubmit"),
                                        ("gemini", ".gemini/settings.json", "BeforeAgent")):
        config = json.loads((ROOT / config_path).read_text())
        command = config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        args = shlex.split(command)
        args[0] = sys.executable
        payload = {"hook_event_name": "SessionStart", "cwd": str(ROOT / "tools"),
                   "session_id": "startup-test-" + client, "prompt": "Fix Mini hockey shootout rendering"}
        result = subprocess.run(args, cwd=ROOT / "tools", input=json.dumps(payload), text=True,
                                capture_output=True)
        assert result.returncode == 0, result.stderr
        assert "task packet" in json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


def test_instruction_bridges_and_root_budget_have_one_owner():
    root = (ROOT / "AGENTS.md").read_text()
    assert len(root.split()) < 750
    assert "tools/workspaces/start.py" in root
    for name in ("CLAUDE.md", "GEMINI.md"):
        bridge = (ROOT / name).read_text()
        assert "@AGENTS.md" in bridge and len(bridge.split()) < 25
    assert len((ROOT / ".github/copilot-instructions.md").read_text().split()) < 50
    for name in (".claude/settings.local.json", ".codex/config.toml", ".gemini/oauth_creds.json"):
        with pytest.raises(WorkspaceError):
            safe_path(name)
    for name in (".claude/settings.json", ".codex/hooks.json", ".gemini/settings.json"):
        assert safe_path(name) == name


def test_cli_rejects_missing_task_without_mutating_source(session_repo, capsys):
    assert main(["--repo", str(session_repo)]) == 1
    assert "new task needs a description" in capsys.readouterr().err
    assert git(session_repo, "status", "--porcelain") == ""


def test_scope_ids_support_expansion_reset_and_path_safety(session_repo, planner_calls):
    planner_calls[0].extend([decision(["mini-sports"], ["mini/pane.h"]), decision(["music"], ["music/song.py"])])
    first = prepare(session_repo, "Fix Mini hockey", "agent-a")
    result = prepare(session_repo, "", "other-name", paths=["mini/new.h"], scope=first["scope"],
                     reason="Add a helper for the next shooter")
    state = json.loads(Path(result["packet"]).with_name("state.json").read_text())
    assert "mini/new.h" in state["context_files"]
    assert "Add a helper for the next shooter" in state["history"][-1]["reasons"]
    continued = prepare(session_repo, "continue", "agent-a")
    state = json.loads(Path(continued["packet"]).with_name("state.json").read_text())
    assert "mini/new.h" in state["context_files"]
    reset = prepare(session_repo, "Fix music", "unused", scope=first["scope"], new_task=True)
    assert reset["slices"] == ["music"]
    with pytest.raises(WorkspaceError, match="scope ID"):
        prepare(session_repo, "Fix Mini hockey", "test", scope="../../outside")


def test_packet_lists_no_unrelated_initial_mini_context(planner_calls):
    planner_calls[0].append(decision(["mini-sports"], ["esp32_hub75/src/mini/rendering/sports_pane.h"]))
    result = prepare(ROOT, "Fix Mini hockey shootout rendering", "startup-minimal-check", new_task=True)
    state = json.loads(Path(result["packet"]).with_name("state.json").read_text())
    assert not any(path.startswith(("TickerControlApp/", "ticker_core/features/", "sports_ticker/dashboard_v2/"))
                   for path in state["context_files"])
    assert not any(any(word in path for word in ("music", "weather", "stocks", "flights"))
                   for path in state["context_files"])
    assert all((ROOT / path).is_file() for path in state["build_files"])
