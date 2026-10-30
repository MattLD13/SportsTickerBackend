"""Verify bounded discovery without model calls or task routing."""
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from agents import discovery
from agents.manage import WorkspaceError

pytestmark = pytest.mark.critical


def byte_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@pytest.fixture
def repository(tmp_path):
    files = {"AGENTS.md": "Rules\n", "app/AGENTS.md": "App rules\n",
             "app/worker.py": "import os\nfrom pathlib import Path\n\nclass Worker:\n    async def refresh(self):\n        return 7\n",
             "shared/types.py": "class Event:\n    pass\n", "app/missing.py": None,
             "other/unrelated.py": "def unrelated():\n    pass\n"}
    for path, source in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source is not None:
            target.write_text(source, encoding="utf-8")
    manifest = {"components": {
        "app": {"owner": "Worker state", "owned": ["app/*"], "build": ["app/*"],
                "context": ["app/worker.py"], "dependencies": ["shared"]},
        "shared": {"owner": "Shared events", "owned": ["shared/*"], "context": ["shared/types.py"]},
        "other": {"owner": "Other code", "owned": ["other/*"], "context": ["other/unrelated.py"]}},
        "slices": {"app": ["app"], "other": ["other"]}, "checks": {}}
    tracked = {path: "100644" for path in files}
    return tmp_path, manifest, tracked


def request(repository, kind, query):
    root, manifest, tracked = repository
    allowed = set(discovery.allowed_files(root, tracked))
    return discovery.discover(root, {"kind": kind, "query": query}, manifest, tracked, allowed)


def test_catalog_has_compact_descriptions_and_only_explicit_allowed_entrypoints(repository):
    root, manifest, tracked = repository
    manifest["components"]["app"]["context"] += ["app/*.py", ".env", "app/missing.py"]
    result = discovery.catalog(manifest, set(discovery.allowed_files(root, tracked)))
    assert result["components"][0] == {"name": "app", "owner": "Worker state"}
    assert result["slices"][0] == {"name": "app", "components": ["app"],
                                   "files": ["app/worker.py", "app/missing.py"]}
    assert "owned" not in json.dumps(result) and "app/*.py" not in json.dumps(result)
    assert all("files" not in row for row in discovery.catalog(manifest)["slices"])


def test_catalog_limits_count_and_utf8_bytes():
    manifest = {"components": {str(i): {"owner": "雪" * 1000} for i in range(200)},
                "slices": {str(i): [str(i)] for i in range(200)}}
    result = discovery.catalog(manifest)
    assert result["truncated"]
    assert len(result["components"]) <= 64 and len(result["slices"]) <= 64
    assert byte_size(result) <= discovery.MAX_CATALOG_BYTES


def test_allowed_files_preserve_missing_sources_and_reject_private_or_nonregular_paths(repository):
    root, _, tracked = repository
    blocked = {".env": "100644", "ticker_data/cache.py": "100644", "private_credentials.json": "100644",
               "mini/src/mini/platform/config.h": "100644", "linked.py": "120000",
               "submodule.py": "160000", "image.png": "100644", "../external.py": "100644"}
    tracked.update(blocked)
    (root / "directory.py").mkdir()
    tracked["directory.py"] = "100644"
    allowed = discovery.allowed_files(root, tracked)
    assert "app/missing.py" in allowed and "app/worker.py" in allowed
    assert not set(blocked) & set(allowed) and "directory.py" not in allowed


@pytest.mark.parametrize("linked_part,reparse", [("app", False), ("app/worker.py", False), ("app", True)])
def test_linked_files_and_ancestors_are_rejected_before_reads(repository, monkeypatch, linked_part, reparse):
    root, manifest, tracked = repository
    original = Path.lstat
    linked = root / linked_part

    def metadata(path, *args, **kwargs):
        if path == linked:
            return SimpleNamespace(st_mode=stat.S_IFDIR if reparse else stat.S_IFLNK,
                                   st_file_attributes=0x400 if reparse else 0)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", metadata)
    assert "app/worker.py" not in discovery.allowed_files(root, tracked)
    with pytest.raises(WorkspaceError, match="linked"):
        discovery.excerpt(root, {"path": "app/worker.py", "symbol": ""}, {"app/worker.py"})
    result = discovery.discover(root, {"kind": "component", "query": "app"}, manifest, tracked, set(tracked))
    assert "app/worker.py" not in result["files"]


def test_component_inventory_includes_dependencies_owners_instructions_and_missing_files(repository, monkeypatch):
    monkeypatch.setattr(discovery, "_read", lambda *args: pytest.fail("Inventory read source content"))
    result = request(repository, "component", "app")
    assert result["components"] == ["shared", "app"]
    assert result["files"] == ["app/worker.py", "AGENTS.md", "app/AGENTS.md", "app/missing.py", "shared/types.py"]
    assert result["missing"] == ["app/missing.py"]
    assert next(row for row in result["details"] if row["path"] == "app/worker.py")["owners"] == ["app"]
    assert not result["truncated"]


def test_component_inventory_has_count_and_byte_limits(repository):
    root, manifest, tracked = repository
    for number in range(150):
        tracked[f"app/{number:03d}_" + "雪" * 40 + ".py"] = "100644"
    result = request(repository, "component", "app")
    assert result["truncated"] and len(result["files"]) <= discovery.MAX_FILES
    assert byte_size(result) <= discovery.MAX_RESULT_BYTES
    assert result["total_files"] > len(result["files"])


def test_requested_component_precedes_large_dependency_inventory(repository):
    _, manifest, tracked = repository
    tracked.update({f"shared/{number:03d}.py": "100644" for number in range(200)})
    manifest["components"]["app"]["checks"] = ["app-check"]
    result = request(repository, "component", "app")
    assert result["files"][0] == "app/worker.py"
    assert "app/missing.py" in result["files"]
    assert result["dependencies"] == ["shared"] and result["checks"] == ["app-check"]
    assert result["truncated"]


def test_ancestor_guides_precede_large_dependency_inventory(repository):
    _, manifest, tracked = repository
    tracked.update({f"shared/{number:03d}.py": "100644" for number in range(200)})
    manifest["components"]["shared"]["owned"].append("AGENTS.md")
    result = request(repository, "component", "app")
    assert result["files"][1:3] == ["AGENTS.md", "app/AGENTS.md"]
    assert all("\\" not in path for path in result["files"])


def test_python_symbols_use_ast_names_imports_and_lines(repository):
    result = request(repository, "symbols", "app/worker.py")
    assert result["symbols"] == [
        {"name": "Worker", "line": 4, "end_line": 6, "kind": "class"},
        {"name": "Worker.refresh", "line": 5, "end_line": 6, "kind": "function"}]
    assert result["imports"] == [{"name": "import os", "line": 1}, {"name": "from pathlib import Path", "line": 2}]
    assert result["parse_ok"] and not result["truncated"]


def test_cpp_and_swift_symbols_ignore_comments_and_strings(repository):
    root, _, tracked = repository
    sources = {"app/pane.h": '#include "types.h"\n// void fake() {\n/* struct Hidden { */\nstruct Pane {\n void render() {\n if (true) {\n const char* text = "class Secret";\n}\n',
               "app/View.swift": 'import SwiftUI\n// func fake() {}\nstruct View {\n func render(_ score: Int) -> String {\n return "func secret()"\n }\n}\n'}
    for path, source in sources.items():
        (root / path).write_text(source, encoding="utf-8")
        tracked[path] = "100644"
    for path in sources:
        result = request(repository, "symbols", path)
        names = [row["name"] for row in result["symbols"]]
        assert "render" in names and not {"fake", "Hidden", "Secret", "secret", "if"} & set(names)
        assert result["imports"]


@pytest.mark.parametrize("query", [".*", "[a-z]+", "$(touch should-not-exist)", "../", "--help"])
def test_search_queries_are_literal_data(repository, query):
    result = request(repository, "search", query)
    assert result["files"] == [] and result["matches"] == []


@pytest.mark.parametrize("query", ["", " ", "x\nworker", "x\x00", "雪" * 100, "one " * 9, None])
def test_invalid_queries_fail_before_discovery(repository, query):
    with pytest.raises(WorkspaceError, match="short literal"):
        request(repository, "search", query)


def test_literal_search_finds_paths_and_qualified_symbols(repository):
    paths = request(repository, "search", "app worker")
    assert paths["matches"][0] == {"path": "app/worker.py", "kind": "filename"}
    symbols = request(repository, "search", "worker.refresh")
    assert symbols["matches"] == [{"path": "app/worker.py", "kind": "symbol", "name": "Worker.refresh", "line": 5}]
    assert symbols["files"] == ["app/worker.py"]


def test_search_bounds_total_source_reads(repository):
    root, _, tracked = repository
    for number in range(20):
        path = f"app/large{number:03d}.py"
        (root / path).write_text("# bounded\n" * 10000, encoding="utf-8")
        tracked[path] = "100644"
    result = request(repository, "search", "never_matches")
    assert result["truncated"]
    assert 0 < result["scanned_bytes"] <= discovery.MAX_SCAN_BYTES
    assert result["scanned_files"] <= discovery.MAX_SCAN_FILES
    assert byte_size(result) <= discovery.MAX_RESULT_BYTES


def test_search_bounds_scan_count_and_missing_path_output(repository):
    _, _, tracked = repository
    tracked.update({f"app/{number:03d}.py": "100644" for number in range(200)})
    result = request(repository, "search", "never_matches")
    assert result["truncated"] and result["scanned_files"] == discovery.MAX_SCAN_FILES
    assert len(result["missing"]) <= 20


def test_search_and_symbol_results_limit_match_counts(repository):
    root, _, tracked = repository
    tracked.update({f"app/worker{number}.py": "100644" for number in range(100)})
    paths = request(repository, "search", "worker")
    assert paths["truncated"] and len(paths["matches"]) <= 30
    (root / "app/worker.py").write_text("\n".join(f"def function{number}(): pass" for number in range(100)), encoding="utf-8")
    symbols = request(repository, "symbols", "app/worker.py")
    assert symbols["truncated"] and len(symbols["symbols"]) == discovery.MAX_SYMBOLS
    assert byte_size(symbols) <= discovery.MAX_RESULT_BYTES


def test_filename_search_returns_without_reading_sources(repository, monkeypatch):
    monkeypatch.setattr(discovery, "_read", lambda *args: pytest.fail("Filename search read source content"))
    result = request(repository, "search", "worker.py")
    assert result["files"] == ["app/worker.py"] and result["symbols_not_scanned"]
    assert result["scanned_bytes"] == result["scanned_files"] == 0


def test_symbol_search_accepts_literal_path_prefix(repository):
    result = request(repository, "search", "app/ Worker.refresh")
    assert result["files"] == ["app/worker.py"]
    assert result["scanned_files"] == 2


def test_sparse_sources_have_explicit_missing_state(repository):
    root, _, tracked = repository
    symbols = request(repository, "symbols", "app/missing.py")
    assert symbols["state"] == "not_materialized" and symbols["missing"] == ["app/missing.py"]
    result = discovery.excerpt(root, {"path": "app/missing.py", "symbol": "refresh"}, set(tracked))
    assert result["state"] == "not_materialized" and result["source"] == ""


def test_targeted_excerpt_uses_definition_instead_of_earlier_text_match(repository):
    root, _, tracked = repository
    source = '# refresh in a comment\n' + '\n' * 120 + 'def refresh():\n    return "雪"\n'
    (root / "app/worker.py").write_text(source, encoding="utf-8")
    result = discovery.excerpt(root, {"path": "app/worker.py", "symbol": "refresh"}, set(tracked))
    assert result["symbol_found"] and result["start_line"] > 100
    assert "def refresh" in result["source"] and "雪" in result["source"]
    assert "refresh in a comment" not in result["source"]


def test_large_source_uses_streamed_late_definition_and_local_window(repository):
    root, _, tracked = repository
    source = '"""\ndef fake():\n    pass\n"""\n' + "# padding for bounded scan\n" * 3000
    source += 'class Late:\n    async def refresh(self):\n        def nested():\n            return "雪"\n        return nested()\n'
    (root / "app/worker.py").write_text(source, encoding="utf-8")
    result = discovery.excerpt(root, {"path": "app/worker.py", "symbol": "Late.refresh"}, set(tracked))
    assert result["symbol_found"] and result["start_line"] > 3000
    assert 'return "雪"' in result["source"] and "def fake" not in result["source"]
    assert "Late.refresh.nested" in result["symbols"] and "fake" not in result["symbols"]
    assert result["scanned_bytes"] <= discovery.MAX_TARGET_BYTES
    assert len(result["source"].splitlines()) <= discovery.MAX_EXCERPT_LINES
    assert byte_size(result) <= discovery.MAX_EXCERPT_BYTES
    symbols = request(repository, "symbols", "app/worker.py")
    assert "Late.refresh" in [row["name"] for row in symbols["symbols"]]
    search = request(repository, "search", "app/ Late.refresh")
    assert any(row.get("name") == "Late.refresh" and row["line"] > 3000 for row in search["matches"])
    assert search["scanned_bytes"] <= discovery.MAX_SCAN_BYTES


def test_scoped_substring_search_finds_late_matches_after_symbol_list_limit(repository):
    root, _, _ = repository
    early = "\n".join(f"def early_{number}(): pass" for number in range(65))
    source = early + "\n" + "# padding\n" * 3000 + "def attempt_reconnect():\n    pass\n"
    source += "# more padding\n" * 120 + "def finish_reconnect():\n    pass\n"
    (root / "app/worker.py").write_text(source, encoding="utf-8")
    result = request(repository, "search", "app/ reconnect")
    assert [row["name"] for row in result["matches"]] == ["attempt_reconnect", "finish_reconnect"]
    assert result["scanned_bytes"] <= discovery.MAX_SCAN_BYTES
    assert byte_size(result) <= discovery.MAX_RESULT_BYTES


def test_scoped_search_bounds_matching_definitions_separately(repository):
    root, _, _ = repository
    early = "\n".join(f"def early_{number}(): pass" for number in range(65))
    (root / "app/worker.py").write_text(early + "\n" + "\n".join(f"def reconnect_{number}(): pass" for number in range(50)), encoding="utf-8")
    result = request(repository, "search", "app/ reconnect")
    assert len(result["matches"]) == 30 and result["truncated"]


def hints(repository, task):
    root, manifest, tracked = repository
    return discovery.initial_hints(root, task, manifest, tracked, set(tracked))


def test_filename_hints_rank_exact_paths_first_without_source_reads_or_scope_selection(repository, monkeypatch):
    monkeypatch.setattr(discovery, "_read", lambda *args: pytest.fail("Filename hints read source"))
    _, manifest, _ = repository
    manifest["components"]["app"]["checks"] = ["worker-check", "unknown-check"]
    manifest["checks"]["worker-check"] = {"files": ["app/worker.py"]}
    result = hints(repository, "Fix app/worker.py and unrelated behavior")
    assert result["files"][0] == "app/worker.py"
    assert result["details"][0]["match"] == "exact_path"
    assert result["details"][0]["owners"] == ["app"]
    assert result["checks"] == ["worker-check"]
    assert "slices" not in result and "components" not in result


def test_filename_hints_rank_rare_name_tokens_and_include_tests(repository):
    _, _, tracked = repository
    tracked.update({"app/station_retry.cpp": "100644", "app/test_station_retry.py": "100644",
                    **{f"app/station_{number}.py": "100644" for number in range(30)}})
    result = hints(repository, "Repair station retry")
    assert set(result["files"][:2]) == {"app/station_retry.cpp", "app/test_station_retry.py"}
    assert all("retry" in row["terms"] for row in result["details"][:2])


def test_filename_hints_bound_count_bytes_and_task_tokens(repository):
    _, _, tracked = repository
    tracked.update({f"app/worker_{number}_" + "雪" * 50 + ".py": "100644" for number in range(100)})
    result = hints(repository, "worker " + "word " * 3000)
    assert result["truncated"] and len(result["files"]) <= discovery.MAX_HINT_FILES
    assert byte_size(result) <= discovery.MAX_HINT_BYTES


def test_filename_hints_ignore_generic_words_and_honor_safe_tracked_index(repository):
    _, _, tracked = repository
    tracked.update({"ticker_data/worker.py": "100644", ".env.worker.py": "100644", "app/link_worker.py": "120000"})
    assert hints(repository, "please fix the code and check files")["files"] == []
    result = hints(repository, "worker")
    assert not {"ticker_data/worker.py", ".env.worker.py", "app/link_worker.py"} & set(result["files"])
    root, manifest, _ = repository
    result = discovery.initial_hints(root, "worker unrelated", manifest, tracked, {"app/worker.py"})
    assert result["files"] == ["app/worker.py"]


def test_filename_hints_support_unicode_and_camel_case_names(repository):
    _, _, tracked = repository
    tracked.update({"app/StationRetry.swift": "100644", "app/天気.py": "100644"})
    result = hints(repository, "station retry 天気")
    assert {"app/StationRetry.swift", "app/天気.py"} <= set(result["files"])


def test_excerpt_limits_lines_bytes_and_nonascii_output(repository):
    root, _, tracked = repository
    (root / "app/worker.py").write_text("# " + "雪" * 1000 + "\n" + "# more\n" * 500, encoding="utf-8")
    result = discovery.excerpt(root, {"path": "app/worker.py", "symbol": ""}, set(tracked))
    assert result["truncated"]
    assert len(result["source"].splitlines()) <= discovery.MAX_EXCERPT_LINES
    assert byte_size(result) <= discovery.MAX_EXCERPT_BYTES
    assert "雪" in result["source"] and "\ufffd" not in result["source"]


def test_source_reads_limit_bytes_and_lines(repository):
    root, _, _ = repository
    (root / "app/worker.py").write_bytes(b"# line\n" * 20000)
    source, truncated, count = discovery._read(root, "app/worker.py")
    assert truncated and count == discovery.MAX_SOURCE_BYTES
    assert len(source.splitlines()) <= discovery.MAX_SOURCE_LINES


def test_invalid_syntax_is_explicit_and_does_not_invent_symbols(repository):
    root, _, _ = repository
    (root / "app/worker.py").write_text("def broken(\n", encoding="utf-8")
    result = request(repository, "symbols", "app/worker.py")
    assert result["parse_ok"] is False and result["symbols"] == []


@pytest.mark.parametrize("kind,query", [("component", "missing"), ("symbols", ".env"),
                                       ("symbols", "../outside.py"), ("shell", "worker")])
def test_unknown_operations_components_and_paths_fail(repository, kind, query):
    with pytest.raises(WorkspaceError):
        request(repository, kind, query)
