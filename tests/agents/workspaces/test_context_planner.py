"""Verify subagent selection, controlled inspection, and planner isolation."""
import json
from pathlib import Path
import subprocess

import pytest

from agents.manage import MANIFEST, ROOT, WorkspaceError, manifest_read, resolve
from agents.planner import (
    SUBAGENT_MODELS, PlannerFailure, Subagent, allowed_files, claude_command, codex_command, excerpt, plan_task,
    run_claude, run_codex, subagent, validate,
)
from agents.start import edit_owners, inventory

pytestmark = pytest.mark.critical


def ready(path="mini/pane.h"):
    return {"phase": "ready", "slices": ["mini-sports"],
            "context": [{"path": path, "symbols": ["render"], "reason": "The pane owns rendering"}],
            "edit_targets": [path], "discover": [], "inspect": [], "checks": [], "shared_change": False,
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
        assert ".env" not in json.dumps(prompt)
        assert "components" not in prompt
        if len(calls) == 1:
            assert "files" not in prompt
        assert timeout > 0 and specification["additionalProperties"] is False
        result = ready()
        if not prompt["inspection_results"]:
            result.update(phase="inspect", inspect=[{"path": "mini/pane.h", "symbol": "render"}])
        return result, {"input_tokens": 100, "output_tokens": 20}
    result = plan_task(root, "Fix a Mini pane", manifest, tracked, runner=runner, clock=lambda: 0)
    assert result["phase"] == "ready"
    assert result["evidence"]["kind"] == "subagent"
    assert result["evidence"]["runner"] == "injected" and result["evidence"]["model"] is None
    assert result["evidence"]["rounds"] == 2
    assert result["evidence"]["inspected_files"] == ["mini/pane.h"]
    assert result["evidence"]["usage"]["input_tokens"] == 200
    assert "int score" in calls[1]["inspection_results"][0]["source"]


@pytest.mark.parametrize("path", [".env", "../outside.py", "mini/src/mini/platform/config.h"])
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


def test_discovery_reveals_paths_before_context_selection(source):
    root, manifest, tracked = source
    (root / "mini/hidden.py").write_text("def repair():\n    return 1\n")
    tracked["mini/hidden.py"] = "100644"
    calls = []
    def runner(prompt, specification, timeout):
        calls.append(json.loads(json.dumps(prompt)))
        result = ready()
        if len(calls) == 1:
            result.update(phase="discover", context=[], edit_targets=[],
                          discover=[{"kind": "search", "query": "hidden.py"}])
        else:
            result = ready("mini/hidden.py")
        return result, {"input_tokens": 50, "output_tokens": 5}
    result = plan_task(root, "Inspect the repair helper", manifest, tracked, runner=runner, clock=lambda: 0)
    assert "mini/hidden.py" not in json.dumps(calls[0])
    assert "mini/hidden.py" in json.dumps(calls[1]["discovery_results"])
    assert result["context"][0]["path"] == "mini/hidden.py"
    assert result["evidence"]["usage"] == {"input_tokens": 100, "output_tokens": 10}
    assert result["evidence"]["request_bytes"] >= result["evidence"]["initial_prompt_bytes"]


def test_undisclosed_path_is_rejected_even_if_tracked(source):
    root, manifest, tracked = source
    tracked["mini/unseen.py"] = "100644"
    with pytest.raises(PlannerFailure, match="disclosed source index") as raised:
        plan_task(root, "Inspect helpers", manifest, tracked,
                  runner=lambda *_: (ready("mini/unseen.py"), {"input_tokens": 30, "output_tokens": 4}),
                  clock=lambda: 0)
    assert raised.value.evidence["usage"] == {"input_tokens": 30, "output_tokens": 4}
    assert raised.value.evidence["usage_complete"]


def test_failed_validation_preserves_usage_and_bounded_evidence(source):
    root, manifest, tracked = source
    result = ready()
    result["inspect"] = [{"path": "mini/pane.h", "symbol": "render"}] * 9
    with pytest.raises(PlannerFailure) as raised:
        plan_task(root, "Synthetic private request text", manifest, tracked,
                  runner=lambda *_: (result, {"input_tokens": 20, "cached_input_tokens": 8, "output_tokens": 7}),
                  clock=lambda: 0)
    evidence = raised.value.evidence
    assert evidence["usage"] == {"input_tokens": 20, "cached_input_tokens": 8, "output_tokens": 7}
    assert "Synthetic private" not in json.dumps(evidence) and "source" not in evidence
    assert evidence["rounds"] == 1


def test_request_bytes_stop_large_tasks_before_any_model_call(source, monkeypatch):
    root, manifest, tracked = source
    monkeypatch.setattr("agents.planner.MAX_REQUEST_BYTES", 50)
    calls = []
    with pytest.raises(PlannerFailure, match="byte budget") as raised:
        plan_task(root, "Inspect a pane", manifest, tracked, runner=lambda *_: calls.append(1), clock=lambda: 0)
    assert calls == [] and raised.value.evidence["rounds"] == 0


def test_latest_results_replace_earlier_source_excerpts(source):
    root, manifest, tracked = source
    calls = []
    def runner(prompt, specification, timeout):
        calls.append(json.loads(json.dumps(prompt)))
        result = ready()
        if len(calls) <= 2:
            result.update(phase="inspect", inspect=[{"path": "mini/pane.h", "symbol": "render"}])
        return result, {"input_tokens": 50, "output_tokens": 5}
    plan_task(root, "Inspect a pane", manifest, tracked, runner=runner, clock=lambda: 0)
    assert len(calls[2]["inspection_results"]) == 1


def test_transport_failures_retain_completed_usage(monkeypatch):
    monkeypatch.setattr("agents.planner.shutil.which", lambda name: "codex")
    def execute(args, **kwargs):
        events = [{"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 4}}]
        return subprocess.CompletedProcess(args, 1, "\n".join(json.dumps(row) for row in events), "Private runner text")
    monkeypatch.setattr("agents.planner.subprocess.run", execute)
    with pytest.raises(PlannerFailure) as raised:
        run_codex({}, {}, 10)
    assert raised.value.evidence["usage"] == {"input_tokens": 12, "output_tokens": 4}
    assert "Private runner" not in str(raised.value)


def test_transport_sums_completed_turns_and_keeps_subsets_separate(monkeypatch):
    monkeypatch.setattr("agents.planner.shutil.which", lambda name: "codex")
    def execute(args, **kwargs):
        (Path(kwargs["cwd"]) / "result.json").write_text(json.dumps(ready()))
        events = [{"type": "turn.completed", "usage": {"input_tokens": 20, "cached_input_tokens": 8,
                    "output_tokens": 4, "reasoning_output_tokens": 2}}] * 2
        return subprocess.CompletedProcess(args, 0, "\n".join(json.dumps(row) for row in events), "")
    monkeypatch.setattr("agents.planner.subprocess.run", execute)
    _, usage = run_codex({}, {}, 10)
    assert usage["input_tokens"] == 40 and usage["output_tokens"] == 8
    assert usage["cached_input_tokens"] == 16 and usage["reasoning_output_tokens"] == 4


@pytest.mark.parametrize("field", ["symbol", "reason", "context", "inspect"])
def test_local_validation_enforces_bounds_independently_of_model_schema(source, field):
    _, manifest, _ = source
    result = ready()
    if field == "symbol":
        result["context"][0]["symbols"] = ["X" * 500000]
    elif field == "reason":
        result["reason"] = "X" * 500000
    elif field == "context":
        result["context"] *= 33
    else:
        result.update(phase="inspect", inspect=[{"path": "mini/pane.h", "symbol": "X" * 500000}])
    with pytest.raises(WorkspaceError):
        validate(result, manifest, {"mini/pane.h"})


@pytest.mark.parametrize("event", [[], {"type": "turn.completed", "usage": None},
                                   {"type": "item.completed", "item": None}])
def test_transport_handles_malformed_json_events_without_losing_failure_type(monkeypatch, event):
    monkeypatch.setattr("agents.planner.shutil.which", lambda name: "codex")
    def execute(args, **kwargs):
        (Path(kwargs["cwd"]) / "result.json").write_text(json.dumps(ready()))
        return subprocess.CompletedProcess(args, 0, json.dumps(event), "")
    monkeypatch.setattr("agents.planner.subprocess.run", execute)
    with pytest.raises(PlannerFailure):
        run_codex({}, {}, 10)


def test_later_failure_cannot_make_prior_unknown_usage_complete(source):
    root, manifest, tracked = source
    calls = []
    def runner(*_):
        calls.append(1)
        if len(calls) == 1:
            result = ready()
            result.update(phase="inspect", inspect=[{"path": "mini/pane.h", "symbol": "render"}])
            return result, {"input_tokens": 5}
        raise PlannerFailure("Later failure", {"usage": {"input_tokens": 8, "output_tokens": 2}, "usage_complete": True})
    with pytest.raises(PlannerFailure) as raised:
        plan_task(root, "Inspect a pane", manifest, tracked, runner=runner, clock=lambda: 0)
    assert raised.value.evidence["usage"] == {"input_tokens": 13, "output_tokens": 2}
    assert raised.value.evidence["usage_complete"] is False


def test_final_schema_requires_ready_and_no_more_requests(source):
    from agents.planner import schema
    specification = schema(source[1], 2, final=True)
    assert specification["properties"]["phase"]["enum"] == ["ready"]
    assert specification["properties"]["discover"]["maxItems"] == 0
    assert specification["properties"]["inspect"]["maxItems"] == 0


def test_timeout_preserves_measured_tokens_as_an_incomplete_lower_bound(monkeypatch):
    monkeypatch.setattr("agents.planner.shutil.which", lambda name: "codex")
    def execute(args, **kwargs):
        output = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}})
        raise subprocess.TimeoutExpired(args, 10, output=output)
    monkeypatch.setattr("agents.planner.subprocess.run", execute)
    with pytest.raises(PlannerFailure) as raised:
        run_codex({}, {}, 10)
    assert raised.value.evidence["usage"] == {"input_tokens": 10, "output_tokens": 2}
    assert raised.value.evidence["usage_complete"] is False


def test_source_reads_are_bounded_and_known_files_only(source):
    root, _, tracked = source
    assert allowed_files(root, tracked) == ["mini/pane.h"]
    result = excerpt(root, {"path": "mini/pane.h", "symbol": "render"}, {"mini/pane.h"})
    assert result["symbol_found"] and "render" in result["symbols"]
    with pytest.raises(WorkspaceError):
        excerpt(root, {"path": ".env", "symbol": ""}, {"mini/pane.h"})


def test_transport_disables_recursive_hooks_tools_and_memory(tmp_path):
    args = codex_command("codex", tmp_path)
    assert args[args.index("--model") + 1] == SUBAGENT_MODELS["codex"]
    assert args[args.index("--sandbox") + 1] == "read-only"
    for feature in ("hooks", "shell_tool", "multi_agent", "apps", "browser_use"):
        assert ["--disable", feature] == args[args.index(feature) - 1:args.index(feature) + 1]
    assert "project_doc_max_bytes=0" in args and "memories.use_memories=false" in args
    assert "--ephemeral" in args and "--ignore-user-config" in args
    assert not any("bypass" in part for part in args)


def test_transport_collects_usage_and_rejects_tool_events(monkeypatch):
    monkeypatch.setattr("agents.planner.shutil.which", lambda name: "codex")
    tool_event = []
    def execute(args, **kwargs):
        folder = Path(kwargs["cwd"])
        assert "SportsTickerBackend" not in str(folder)
        assert kwargs["timeout"] == 10
        (folder / "result.json").write_text(json.dumps(ready()))
        events = tool_event or [{"type": "turn.completed", "usage": {"input_tokens": 12}}]
        return subprocess.CompletedProcess(args, 0, "\n".join(json.dumps(row) for row in events), "")
    monkeypatch.setattr("agents.planner.subprocess.run", execute)
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
    monkeypatch.setattr("agents.planner.shutil.which", lambda name: None)
    with pytest.raises(WorkspaceError, match="Install Codex CLI"):
        run_codex({}, {}, 10)


def test_weather_art_and_catalog_tests_have_precise_consumer_ownership():
    manifest = manifest_read(MANIFEST)
    owners = edit_owners(manifest, ["ticker/six/ui/weather_art.py", "ticker/six/ui/cards/weather.py",
                                    "tests/six/ui/test_catalog.py"], False)
    assert {"weather", "weather-art", "six-rendering"} <= owners
    plan = resolve(manifest, sorted(owners), inventory(ROOT, manifest, "HEAD"))
    assert "mini-firmware" in plan["components"]
    assert not set(manifest["shared_consumers"]) & set(plan["components"])


def test_subagent_records_its_cli_and_model_in_the_plan(source, monkeypatch):
    root, manifest, tracked = source
    seen = []
    def fake(prompt, specification, timeout, model):
        seen.append(model)
        return ready(), {"input_tokens": 9, "output_tokens": 3}
    monkeypatch.setitem(__import__("agents.planner", fromlist=["RUNNERS"]).RUNNERS, "claude", fake)
    result = plan_task(root, "Fix a Mini pane", manifest, tracked, runner=Subagent("claude", "haiku"), clock=lambda: 0)
    assert seen == ["haiku"]
    assert {key: result["evidence"][key] for key in ("kind", "runner", "model")} == \
        {"kind": "subagent", "runner": "claude", "model": "haiku"}


def test_subagent_selection_prefers_the_choice_then_the_first_installed_cli(monkeypatch):
    installed = {"codex"}
    monkeypatch.setattr("agents.planner.shutil.which", lambda name: name if name in installed else None)
    monkeypatch.delenv("TICKER_CONTEXT_SUBAGENT", raising=False)
    monkeypatch.delenv("TICKER_CONTEXT_MODEL", raising=False)
    assert subagent() == Subagent("codex", SUBAGENT_MODELS["codex"])
    installed.add("claude")
    assert subagent() == Subagent("claude", "haiku")
    monkeypatch.setenv("TICKER_CONTEXT_SUBAGENT", "codex")
    monkeypatch.setenv("TICKER_CONTEXT_MODEL", "small-model")
    assert subagent() == Subagent("codex", "small-model")
    assert subagent("claude", "other-model") == Subagent("claude", "other-model")
    with pytest.raises(WorkspaceError, match="Unknown context subagent"):
        subagent("gemini")
    installed.clear()
    monkeypatch.delenv("TICKER_CONTEXT_SUBAGENT")
    with pytest.raises(WorkspaceError, match="Install Claude Code or Codex CLI"):
        subagent()


def test_claude_transport_disables_tools_mcp_settings_and_sessions():
    args = claude_command("claude", {"type": "object"})
    assert args[args.index("--model") + 1] == "haiku"
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--setting-sources") + 1] == ""
    assert json.loads(args[args.index("--json-schema") + 1]) == {"type": "object"}
    for flag in ("--print", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in args
    assert not any("dangerously" in part or "bypass" in part for part in args)


def _claude_reply(**fields):
    reply = {"type": "result", "subtype": "success", "is_error": False, "permission_denials": [],
             "structured_output": ready(), "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1800,
                                                     "cache_read_input_tokens": 100, "output_tokens": 70}}
    reply.update(fields)
    return json.dumps(reply)


def test_claude_transport_runs_outside_the_repository_and_sums_input(monkeypatch):
    monkeypatch.setattr("agents.planner.shutil.which", lambda name: "claude")
    calls = []
    def execute(args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(args, 0, _claude_reply(), "")
    monkeypatch.setattr("agents.planner.subprocess.run", execute)
    result, usage = run_claude({"task": "Fix a pane"}, {"type": "object"}, 10)
    assert result == ready()
    assert usage == {"input_tokens": 1902, "output_tokens": 70, "runner_notices": 0}
    assert not Path(calls[0]["cwd"]).resolve().is_relative_to(ROOT)
    assert calls[0]["input"].endswith('{"task":"Fix a pane"}')


@pytest.mark.parametrize("reply,message", [
    (_claude_reply(permission_denials=[{"tool_name": "Bash"}]), "tool operation"),
    (_claude_reply(is_error=True, subtype="error_during_execution"), "sign-in"),
    (_claude_reply(structured_output=None), "unreadable"),
    ("not json", "sign-in"),
])
def test_claude_transport_rejects_failed_or_unsafe_turns(monkeypatch, reply, message):
    monkeypatch.setattr("agents.planner.shutil.which", lambda name: "claude")
    monkeypatch.setattr("agents.planner.subprocess.run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, reply, ""))
    with pytest.raises(PlannerFailure, match=message):
        run_claude({}, {}, 10)
