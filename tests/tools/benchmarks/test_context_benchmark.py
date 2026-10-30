"""Verify held-out context scoring and model usage accounting without network access."""
from copy import deepcopy
import json

import pytest

from tools.benchmarks import context_discovery as benchmark

pytestmark = pytest.mark.critical


@pytest.fixture
def inputs(tmp_path):
    manifest = {
        "components": {"owner": {"owned": ["owner.py"], "context": ["owner.py"],
                                  "build": ["held_out_test.py"], "checks": ["focused"], "dependencies": []},
                       "consumer": {"owned": ["consumer.py"], "context": ["consumer.py"],
                                    "build": [], "checks": [], "dependencies": []}},
        "slices": {"known": ["owner"]},
        "checks": {"focused": {"files": ["held_out_test.py"]}},
        "shared_owners": ["owner"], "shared_consumers": ["consumer"],
    }
    tracked = {path: "100644" for path in ("owner.py", "consumer.py", "held_out_test.py")}
    for path in tracked:
        (tmp_path / path).write_text("def render():\n    return 1\n", encoding="utf-8")
    expected = {"paths": ["owner.py", "held_out_test.py"], "components": ["owner", "consumer"],
                "checks": ["focused"], "shared_change": True}
    classes = ("narrow-known", "unfamiliar-component", "shared-contract")
    cases = [{"id": str(index), "task_class": task_class, "task": "Investigate a display fact",
              "expected": deepcopy(expected)} for index, task_class in enumerate(classes)]
    return tmp_path, manifest, tracked, cases


def ready():
    return {"phase": "ready", "slices": ["known"],
            "context": [{"path": "owner.py", "symbols": ["render"], "reason": "Owns the fact"},
                        {"path": "held_out_test.py", "symbols": [], "reason": "Checks the fact"}],
            "edit_targets": ["owner.py"], "inspect": [], "checks": ["focused"],
            "shared_change": True, "reason": "Select the owner and consumers"}


def injected_planner(root, task, manifest, tracked, *, runner):
    result, _ = runner({"task": task, "files": sorted(tracked)}, {"type": "object"}, 10)
    return result


def successful_runner(prompt, specification, timeout):
    return ready(), {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 20,
                     "output_tokens_details": {"reasoning_tokens": 10}}


def test_usage_subsets_do_not_inflate_total():
    counts = benchmark.usage_counts(successful_runner({}, {}, 1)[1])
    assert counts["total_tokens"] == 120
    assert counts["uncached_input_plus_output_tokens"] == 40
    assert counts["reasoning_output_tokens"] == 10
    assert counts["complete"]
    assert benchmark.usage_counts({"input_tokens": 0, "output_tokens": 0})["total_tokens"] == 0
    assert benchmark.usage_counts({"input_tokens": 10})["total_tokens"] is None
    assert benchmark.usage_counts({"input_tokens": True, "output_tokens": -1})["complete"] is False


def test_injected_evaluation_keeps_expected_answers_out_of_prompts(inputs):
    root, manifest, tracked, cases = inputs
    received = []

    def runner(prompt, specification, timeout):
        received.append(deepcopy(prompt))
        assert "expected" not in prompt and "task_class" not in prompt
        assert "held_out_test.py" not in prompt["task"]
        return successful_runner(prompt, specification, timeout)

    report = benchmark.evaluate(root, manifest, tracked, cases,
                                planners={"old": injected_planner, "new": injected_planner},
                                runners={"old": runner, "new": runner}, clock=lambda: 0)
    assert len(received) == 6
    assert report["paired"]["comparable_pairs"] == 3
    assert report["paired"]["arms"]["new"]["total_tokens"] == 360
    assert report["paired"]["arms"]["old"]["complete_context_cases"] == 3
    assert report["measurement"] == "planning-only"
    assert all(row["coverage"]["complete"] for row in report["runs"])


def test_planners_cannot_inspect_evaluation_rubric_sources(inputs):
    root, manifest, tracked, cases = inputs
    tracked.update({path: "100644" for path in benchmark.EVALUATION_PATHS})

    def runner(prompt, specification, timeout):
        assert not set(prompt["files"]) & benchmark.EVALUATION_PATHS
        return successful_runner(prompt, specification, timeout)

    report = benchmark.evaluate(root, manifest, tracked, cases[:1],
                                planners={"old": injected_planner, "new": injected_planner},
                                runners={"old": runner, "new": runner}, clock=lambda: 0)
    assert report["paired"]["comparable_pairs"] == 1
    assert report["excluded_evaluation_paths"] == sorted(benchmark.EVALUATION_PATHS)


def test_broad_build_scope_does_not_count_as_selected_entry_points(inputs):
    _, manifest, tracked, cases = inputs
    result = ready()
    result["context"] = result["context"][:1]
    scores = benchmark.score_result(result, cases[0]["expected"], manifest, tracked)
    assert scores["entry_points"]["missing"] == ["held_out_test.py"]
    assert scores["entry_points"]["fraction"] == 0.5
    assert scores["scope_build_file_count"] == 3
    assert scores["components"]["fraction"] == 1
    assert scores["complete"] is False


def test_failed_attempt_usage_remains_in_totals_when_planner_retries(inputs):
    root, manifest, tracked, cases = inputs
    calls = 0

    def retrying_runner(prompt, specification, timeout):
        nonlocal calls
        calls += 1
        if calls % 2:
            raise benchmark.AttemptFailure("Rejected attempt", {"input_tokens": 30, "output_tokens": 4})
        return successful_runner(prompt, specification, timeout)

    def retrying_planner(root, task, manifest, tracked, *, runner):
        try:
            runner({"task": task}, {}, 10)
        except benchmark.AttemptFailure:
            pass
        return runner({"task": task}, {}, 10)[0]

    report = benchmark.evaluate(root, manifest, tracked, cases[:1],
                                planners={"old": retrying_planner, "new": injected_planner},
                                runners={"old": retrying_runner, "new": successful_runner}, clock=lambda: 0)
    old = next(row for row in report["runs"] if row["arm"] == "old")
    assert old["usage"]["total_tokens"] == 154
    assert old["usage"]["complete"]
    assert [row["status"] for row in old["attempts"]] == ["failed", "succeeded"]
    assert report["paired"]["comparable_pairs"] == 1


def test_failed_unknown_usage_is_distinct_and_excluded_from_pairs(inputs):
    root, manifest, tracked, cases = inputs

    def runner(*args):
        raise benchmark.AttemptFailure("No usage from failed setup")

    report = benchmark.evaluate(root, manifest, tracked, cases[:1],
                                planners={"old": injected_planner, "new": injected_planner},
                                runners={"old": runner, "new": successful_runner}, clock=lambda: 0)
    old = next(row for row in report["runs"] if row["arm"] == "old")
    assert old["status"] == "failed"
    assert old["usage"]["total_tokens"] is None
    assert old["usage"]["unknown_usage_attempts"] == 1
    assert old["usage"]["is_lower_bound"]
    assert report["paired"]["comparable_pairs"] == 0
    assert report["paired"]["excluded_pairs"] == 1
    assert report["paired"]["arms"]["new"]["mean_entry_point_coverage"] is None
    assert report["all_runs"]["old"]["failed_runs"] == 1
    assert report["all_runs"]["old"]["usage"]["unknown_usage_attempts"] == 1


def test_success_after_unknown_usage_retains_lower_bound(inputs):
    attempts = [{"usage": benchmark.usage_counts(None)},
                {"usage": benchmark.usage_counts({"input_tokens": 8, "output_tokens": 2})}]
    counts = benchmark.total_usage(attempts)
    assert counts["total_tokens"] == 10
    assert counts["complete"] is False
    assert counts["unknown_usage_attempts"] == 1


def test_observation_counts_exact_utf8_request_and_repeated_source_text():
    attempts = []
    prompt = {"task": "Inspect café", "inspection_results": [
        {"path": "owner.py", "source": "1: café", "start_line": 1}]}
    clock = iter((2.0, 2.25)).__next__
    runner = benchmark.observed_runner(successful_runner, "Instructions", attempts, clock)
    runner(prompt, {"type": "object"}, 10)
    assert attempts[0]["request_bytes"] == len(("Instructions\n" + json.dumps(prompt)).encode())
    assert attempts[0]["source_excerpt_bytes"] == len("1: café".encode())
    assert attempts[0]["source_excerpt_paths"] == ["owner.py"]
    assert attempts[0]["seconds"] == 0.25


def test_cli_defaults_to_offline_and_never_loads_model_runners(inputs, monkeypatch, capsys):
    root, manifest, tracked, cases = inputs
    (root / ".github").mkdir()
    (root / ".github/agent-workspaces.json").write_text(json.dumps(manifest), encoding="utf-8")
    case_path = root / "cases.json"
    case_path.write_text(json.dumps({"version": 1, "cases": cases}), encoding="utf-8")
    monkeypatch.setattr(benchmark, "ROOT", root)
    monkeypatch.setattr(benchmark, "manifest_read", lambda path: manifest)
    monkeypatch.setattr(benchmark, "git", lambda *args: "fixture-revision")
    monkeypatch.setattr(benchmark, "inventory", lambda *args: tracked)

    def unexpected(*args):
        pytest.fail("Offline evaluation invoked a model runner")

    monkeypatch.setattr(benchmark, "load_planner", unexpected)
    assert benchmark.main(["--cases", str(case_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "offline-validation" and output["model_calls"] == 0
    assert len(output["cases"]) == 3
    with pytest.raises(SystemExit):
        benchmark.main(["--baseline-planner", "untrusted.py"])
    with pytest.raises(SystemExit):
        benchmark.main(["--live"])
    with pytest.raises(SystemExit):
        benchmark.main(["--live", "--baseline-planner", "frozen.py"])


def test_case_validation_requires_three_classes_and_existing_paths(inputs):
    root, manifest, tracked, cases = inputs
    path = root / "cases.json"
    path.write_text(json.dumps({"version": 1, "cases": cases}), encoding="utf-8")
    assert benchmark.load_cases(path, manifest, tracked) == cases
    cases[0]["expected"]["paths"] = ["missing.py"]
    path.write_text(json.dumps({"version": 1, "cases": cases}), encoding="utf-8")
    with pytest.raises(benchmark.WorkspaceError, match="absent"):
        benchmark.load_cases(path, manifest, tracked)
    path.write_text(json.dumps({"version": 1, "cases": cases[1:]}), encoding="utf-8")
    with pytest.raises(benchmark.WorkspaceError, match="three task classes"):
        benchmark.load_cases(path, manifest, tracked)


def test_planner_failure_evidence_preserves_available_usage():
    attempts = []

    class Failure(benchmark.WorkspaceError):
        evidence = {"usage": {"input_tokens": 13, "output_tokens": 2}, "usage_complete": True}

    def failed(*args):
        raise Failure("Failed model attempt")

    observed = benchmark.observed_runner(failed, "Instructions", attempts, clock=lambda: 0)
    with pytest.raises(Failure):
        observed({}, {}, 10)
    assert attempts[0]["usage"]["total_tokens"] == 15
    assert attempts[0]["status"] == "failed"


def test_observation_uses_each_transport_request_encoding():
    attempts = []
    prompt = {"task": "café"}
    encode = lambda value: "Instructions\n" + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    observed = benchmark.observed_runner(successful_runner, "Instructions", attempts,
                                         clock=lambda: 0, request_text=encode)
    observed(prompt, {}, 10)
    assert attempts[0]["request_bytes"] == len(encode(prompt).encode())
    assert attempts[0]["request_bytes"] != len(("Instructions\n" + json.dumps(prompt)).encode())


def test_partial_failure_counts_do_not_become_complete_usage():
    attempts = []

    class Failure(benchmark.WorkspaceError):
        evidence = {"usage": {"input_tokens": 13, "output_tokens": 2}, "usage_complete": False}

    def failed(*args):
        raise Failure("Partial usage from interrupted attempt")

    observed = benchmark.observed_runner(failed, "Instructions", attempts, clock=lambda: 0)
    with pytest.raises(Failure):
        observed({}, {}, 10)
    counts = benchmark.total_usage(attempts)
    assert counts["total_tokens"] == 15
    assert counts["is_lower_bound"]
    assert counts["unknown_usage_attempts"] == 1


def test_arm_order_alternates_for_paired_runs(inputs):
    root, manifest, tracked, cases = inputs
    report = benchmark.evaluate(root, manifest, tracked, cases,
                                planners={"old": injected_planner, "new": injected_planner},
                                runners={"old": successful_runner, "new": successful_runner},
                                repeats=2, clock=lambda: 0)
    assert [row["arm"] for row in report["runs"]] == [
        "old", "new", "new", "old", "old", "new", "new", "old", "old", "new", "new", "old"]
    assert report["paired"]["comparable_pairs"] == 6


def test_attempt_checkpoints_keep_completed_usage_before_plan_failure(inputs):
    root, manifest, tracked, cases = inputs
    checkpoints = []
    def failing_planner(root, task, manifest, tracked, *, runner):
        runner({"task": task}, {}, 10)
        raise benchmark.WorkspaceError("Plan rejected after completed model attempt")
    benchmark.evaluate(root, manifest, tracked, cases[:1],
        planners={"old": failing_planner, "new": injected_planner},
        runners={"old": successful_runner, "new": successful_runner},
        clock=lambda: 0, checkpoint=checkpoints.append)
    first = checkpoints[0]
    assert first["status"] == "running"
    assert first["runs"][0]["attempts"][0]["status"] == "running"
    assert first["runs"][0]["attempts"][0]["usage"]["total_tokens"] is None
    assert checkpoints[1]["runs"][0]["attempts"][0]["usage"]["total_tokens"] == 120
    assert checkpoints[-1]["runs"][0]["status"] == "failed"


def test_report_write_keeps_valid_json(tmp_path):
    target = tmp_path / "nested/report.json"
    benchmark.write_report(target, {"status": "running"})
    benchmark.write_report(target, {"status": "complete"})
    assert json.loads(target.read_text()) == {"status": "complete"}
    assert not target.with_suffix(".json.tmp").exists()
