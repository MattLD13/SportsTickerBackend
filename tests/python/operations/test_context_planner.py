"""Verify Luna selection, controlled inspection, and planner isolation."""
import json
from pathlib import Path
import subprocess

import pytest

from tools.workspaces.manage import MANIFEST, ROOT, WorkspaceError, manifest_read, resolve
from tools.workspaces.planner import (
    MODEL, allowed_files, codex_command, excerpt, plan_task, run_codex, validate,
)
from tools.workspaces.start import edit_owners, inventory

pytestmark = pytest.mark.critical


def ready(path="mini/pane.h"):
    return {"phase": "ready", "slices": ["mini-sports"],
            "context": [{"path": path, "symbols": ["render"], "reason": "The pane owns rendering"}],
            "edit_targets": [path], "inspect": [], "checks": [], "shared_change": False,
            "reason": "Inspect the pane and its test"}


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "mini").mkdir(parents=True)
    (root / "mini/pane.h").write_text("inline void render() {\n  int score = 1;\n}\n")
    (root / ".env").write_text("SYNTHETIC_CREDENTIAL=do-not-send\n")
    manifest = {"slices": {"mini-sports": ["mini"]}, "checks": {},
                "components": {"mini": {"owner": "Mini", "context": ["mini/pane.h"]}}}
    tracked = {"mini/pane.h": "100644", ".env": "100644"}
    return root, manifest, tracked


def test_planner_requests_controlled_inspection_then_returns_a_plan(source):
    root, manifest, tracked = source
    calls = []
    def runner(prompt, specification, timeout):
        calls.append(json.loads(json.dumps(prompt)))
        assert ".env" not in prompt["files"]
        assert timeout > 0 and specification["additionalProperties"] is False
        result = ready()
        if not prompt["inspection_results"]:
            result.update(phase="inspect", inspect=[{"path": "mini/pane.h", "symbol": "render"}])
        return result, {"input_tokens": 100, "output_tokens": 20}
    result = plan_task(root, "Fix a Mini pane", manifest, tracked, runner=runner, clock=lambda: 0)
    assert result["phase"] == "ready"
    assert result["evidence"]["model"] == MODEL
    assert result["evidence"]["rounds"] == 2
    assert result["evidence"]["inspected_files"] == ["mini/pane.h"]
    assert result["evidence"]["usage"]["input_tokens"] == 200
    assert "int score" in calls[1]["inspection_results"][0]["source"]


@pytest.mark.parametrize("path", [".env", "../outside.py", "esp32_hub75/src/mini/platform/config.h"])
def test_model_cannot_select_credentials_or_external_files(source, path):
    _, manifest, _ = source
    with pytest.raises(WorkspaceError):
        validate(ready(path), manifest, {"mini/pane.h"})


def test_unknown_checks_and_slices_are_rejected(source):
    _, manifest, _ = source
    result = ready()
    result["checks"] = ["run-whatever-command"]
    with pytest.raises(WorkspaceError, match="check"):
        validate(result, manifest, {"mini/pane.h"})
    result = ready()
    result["slices"] = ["missing"]
    with pytest.raises(WorkspaceError, match="slice"):
        validate(result, manifest, {"mini/pane.h"})


def test_inspection_budget_counts_repeated_requests(source):
    root, manifest, tracked = source
    def runner(*args):
        result = ready()
        result.update(phase="inspect", inspect=[{"path": "mini/pane.h", "symbol": "render"}] * 9)
        return result, {}
    with pytest.raises(WorkspaceError, match="inspection budget"):
        plan_task(root, "Fix a pane", manifest, tracked, runner=runner, clock=lambda: 0)


def test_planner_failure_is_visible_without_keyword_fallback(source):
    root, manifest, tracked = source
    def runner(*args):
        raise WorkspaceError("No model access")
    with pytest.raises(WorkspaceError, match="No model access"):
        plan_task(root, "Fix Mini hockey", manifest, tracked, runner=runner, clock=lambda: 0)


def test_source_reads_are_bounded_and_known_files_only(source):
    root, _, tracked = source
    assert allowed_files(root, tracked) == ["mini/pane.h"]
    result = excerpt(root, {"path": "mini/pane.h", "symbol": "render"}, {"mini/pane.h"})
    assert result["symbol_found"] and "render" in result["symbols"]
    with pytest.raises(WorkspaceError):
        excerpt(root, {"path": ".env", "symbol": ""}, {"mini/pane.h"})


def test_transport_disables_recursive_hooks_tools_and_memory(tmp_path):
    args = codex_command("codex", tmp_path)
    assert args[args.index("--model") + 1] == "gpt-6-luna"
    assert args[args.index("--sandbox") + 1] == "read-only"
    for feature in ("hooks", "shell_tool", "multi_agent", "apps", "browser_use"):
        assert ["--disable", feature] == args[args.index(feature) - 1:args.index(feature) + 1]
    assert "project_doc_max_bytes=0" in args and "memories.use_memories=false" in args
    assert "--ephemeral" in args and "--ignore-user-config" in args
    assert not any("bypass" in part for part in args)


def test_transport_collects_usage_and_rejects_tool_events(monkeypatch):
    monkeypatch.setattr("tools.workspaces.planner.shutil.which", lambda name: "codex")
    tool_event = []
    def execute(args, **kwargs):
        folder = Path(kwargs["cwd"])
        assert "SportsTickerBackend" not in str(folder)
        assert kwargs["timeout"] == 10
        (folder / "result.json").write_text(json.dumps(ready()))
        events = tool_event or [{"type": "turn.completed", "usage": {"input_tokens": 12}}]
        return subprocess.CompletedProcess(args, 0, "\n".join(json.dumps(row) for row in events), "")
    monkeypatch.setattr("tools.workspaces.planner.subprocess.run", execute)
    result, usage = run_codex({"task": "Fix a pane"}, {"type": "object"}, 10)
    assert result["phase"] == "ready" and usage["input_tokens"] == 12
    tool_event.extend([{"type": "item.completed", "item": {"type": "error", "message": "Client startup notice"}},
                       {"type": "turn.completed", "usage": {"input_tokens": 12}}])
    _, usage = run_codex({}, {}, 10)
    assert usage["runner_notices"] == 1
    tool_event.append({"type": "item.completed", "item": {"type": "command_execution"}})
    with pytest.raises(WorkspaceError, match="tool operation"):
        run_codex({}, {}, 10)


def test_missing_cli_returns_an_actionable_error(monkeypatch):
    monkeypatch.setattr("tools.workspaces.planner.shutil.which", lambda name: None)
    with pytest.raises(WorkspaceError, match="Install Codex CLI"):
        run_codex({}, {}, 10)


def test_weather_art_and_catalog_tests_have_precise_consumer_ownership():
    manifest = manifest_read(MANIFEST)
    owners = edit_owners(manifest, ["ticker_core/features/weather/drawing.py",
                                    "tests/python/rendering/test_catalog.py"], False)
    assert {"weather", "weather-art", "six-rendering"} <= owners
    plan = resolve(manifest, sorted(owners), inventory(ROOT, manifest, "HEAD"))
    assert "mini-firmware" in plan["components"]
    assert not set(manifest["shared_consumers"]) & set(plan["components"])
