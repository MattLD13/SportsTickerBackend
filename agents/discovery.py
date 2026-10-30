"""Provide bounded repository evidence for model context selection."""
from __future__ import annotations

import ast
from collections import deque
from fnmatch import fnmatchcase
import json
import math
import os
from pathlib import Path
import re
import stat
import tokenize

from agents.manage import WorkspaceError, safe_path

SOURCE_SUFFIXES = frozenset({".py", ".cpp", ".cc", ".c", ".hpp", ".h", ".inc", ".swift",
                             ".md", ".json", ".toml", ".yml", ".yaml", ".ini", ".sh"})
MAX_CATALOG_BYTES = 16000
MAX_RESULT_BYTES = 12000
MAX_FILES = 80
MAX_SYMBOLS = 60
MAX_SCAN_FILES = 128
MAX_SOURCE_BYTES = 65536
MAX_SOURCE_LINES = 2000
MAX_SCAN_BYTES = 524288
MAX_EXCERPT_LINES = 100
MAX_EXCERPT_BYTES = 6000
MAX_QUERY_BYTES = 160
MAX_QUERY_TERMS = 8
MAX_TARGET_BYTES = 1048576
MAX_TARGET_LINES = 20000
MAX_HINT_BYTES = 6000
MAX_HINT_FILES = 16
HINT_STOPWORDS = frozenset({"a", "an", "and", "are", "as", "at", "be", "by", "can", "change", "check",
                            "code", "do", "file", "files", "fix", "for", "from", "have", "i", "in", "is",
                            "it", "its", "make", "of", "on", "or", "please", "should", "that", "the", "their",
                            "them", "this", "to", "update", "use", "when", "which", "with", "you", "your",
                            "py", "cpp", "cc", "c", "hpp", "h", "swift", "md", "json", "test", "tests"})


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _clip(value: str, budget: int) -> str:
    return value.encode("utf-8")[:budget].decode("utf-8", errors="ignore")


def _append(result: dict, field: str, value: object, budget: int, count: int) -> bool:
    if len(result[field]) >= count:
        result["truncated"] = True
        return False
    result[field].append(value)
    if _size(result) > budget:
        result[field].pop()
        result["truncated"] = True
        return False
    return True


def _target(root: Path, path: str) -> Path:
    """Reject links at every path segment, including Windows junctions."""
    try:
        safe_path(path)
    except WorkspaceError as error:
        raise WorkspaceError("Discovery rejected an unsafe source path") from error
    root = root.resolve()
    current = root
    for part in path.split("/"):
        current = current / part
        try:
            details = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise WorkspaceError("Discovery cannot inspect a source path") from error
        if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            raise WorkspaceError("Discovery rejected a linked source path")
    if not current.resolve().is_relative_to(root):
        raise WorkspaceError("Discovery rejected an external source path")
    return current


def allowed_files(root: Path, tracked: dict[str, str]) -> list[str]:
    """Return safe regular tracked sources, including absent sparse files."""
    result = []
    for path, mode in sorted(tracked.items()):
        if mode not in ("100644", "100755") or Path(path).suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            target = _target(root, path)
            if target.exists() and not target.is_file():
                continue
        except WorkspaceError:
            continue
        result.append(path)
    return result


def catalog(manifest: dict, allowed: set[str] | None = None) -> dict:
    """Return component descriptions and slices without the repository index."""
    result = {"components": [], "slices": [], "truncated": False}
    for name, component in sorted(manifest["components"].items()):
        row = {"name": name, "owner": _clip(str(component.get("owner", "")), 200)}
        if not _append(result, "components", row, MAX_CATALOG_BYTES, 64):
            break
    for name, components in sorted(manifest["slices"].items()):
        row = {"name": name, "components": components}
        if allowed is not None:
            candidates = []
            for component in components:
                for path in manifest["components"][component].get("context", []):
                    if path not in allowed or Path(path).suffix.lower() not in SOURCE_SUFFIXES:
                        continue
                    try:
                        safe_path(path)
                    except WorkspaceError:
                        continue
                    candidates.append(path)
            row["files"] = list(dict.fromkeys(candidates))[:3]
        if not _append(result, "slices", row, MAX_CATALOG_BYTES, 64):
            break
    return result


def _query(request: dict) -> str:
    query = request.get("query")
    if (not isinstance(query, str) or not query.strip() or len(query.encode("utf-8")) > MAX_QUERY_BYTES
            or any(ord(character) < 32 for character in query) or len(query.split()) > MAX_QUERY_TERMS):
        raise WorkspaceError("Discovery needs a short literal query")
    return query.strip()


def _closure(manifest: dict, name: str) -> list[str]:
    result, visiting = [], set()

    def visit(item: str) -> None:
        if item in visiting or item not in manifest["components"]:
            raise WorkspaceError("Discovery found an invalid component dependency")
        if item in result:
            return
        visiting.add(item)
        for dependency in manifest["components"][item].get("dependencies", []):
            visit(dependency)
        visiting.remove(item)
        result.append(item)

    visit(name)
    return result


def _owners(manifest: dict, path: str) -> list[str]:
    return [name for name, component in sorted(manifest["components"].items())
            if any(fnmatchcase(path, pattern) for pattern in component.get("owned", []))][:8]


def _name_tokens(value: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return {token.casefold() for token in re.findall(r"[^\W_]+", expanded)
            if len(token) > 1 and token.casefold() not in HINT_STOPWORDS}


def initial_hints(root: Path, task: str, manifest: dict, tracked: dict[str, str], allowed: set[str]) -> dict:
    """Rank literal filename evidence without reading source or selecting slices."""
    if not isinstance(task, str):
        raise WorkspaceError("Filename hints need task text")
    clipped = _clip(task, 8192)
    result = {"files": [], "details": [], "checks": [], "truncated": clipped != task}
    permitted = sorted(set(allowed_files(root, tracked)) & set(allowed))
    task_tokens = sorted(_name_tokens(clipped))[:64]
    result["truncated"] |= len(_name_tokens(clipped)) > 64
    exact = {value for value in re.findall(r"[\w./-]+", clipped) if value in permitted}
    names = {path: _name_tokens(Path(path).name) for path in permitted}
    tokens = {path: _name_tokens(path) for path in permitted}
    frequency = {token: sum(token in value for value in tokens.values()) for token in task_tokens}
    ranked = []
    for path in permitted:
        overlap = set(task_tokens) & tokens[path]
        if path not in exact and not overlap:
            continue
        score = sum((2 if token in names[path] else 1) * (math.log((len(permitted) + 1) / (frequency[token] + 1)) + 1)
                    for token in overlap)
        ranked.append((path not in exact, -score, path, sorted(overlap)))
    for is_inexact, _, path, overlap in sorted(ranked):
        owners = _owners(manifest, path)
        checks = sorted({check for owner in owners for check in manifest["components"][owner].get("checks", [])
                         if check in manifest.get("checks", {})})[:8]
        detail = {"path": path, "owners": owners, "checks": checks,
                  "match": "filename_tokens" if is_inexact else "exact_path", "terms": overlap[:8]}
        candidate = dict(result, files=result["files"] + [path], details=result["details"] + [detail],
                         checks=sorted(set(result["checks"]) | set(checks)))
        if len(result["files"]) >= MAX_HINT_FILES or _size(candidate) > MAX_HINT_BYTES:
            result["truncated"] = True
            break
        result = candidate
    return result


def _component(root: Path, name: str, manifest: dict, allowed: set[str]) -> dict:
    names = _closure(manifest, name)
    selected = manifest["components"][name]
    groups = [selected.get("context", []), selected.get("owned", []), selected.get("build", [])]
    for item in reversed(names[:-1]):
        component = manifest["components"][item]
        groups.extend(component.get(field, []) for field in ("context", "owned", "build"))
    rank = {}
    for priority, patterns in enumerate(groups):
        for path in sorted(allowed):
            if any(fnmatchcase(path, pattern) for pattern in patterns):
                rank.setdefault(path, priority * 2)
    files = list(rank)
    instructions = {(parent / "AGENTS.md").as_posix() for path in files for parent in Path(path).parents}
    for path in instructions & allowed:
        rank[path] = min(rank.get(path, 1), 1)
    files = sorted(rank, key=lambda path: (rank[path], path))
    checks = sorted({check for item in names for check in manifest["components"][item].get("checks", [])})
    result = {"kind": "component", "query": name, "components": [], "files": [], "details": [],
              "dependencies": [], "checks": [],
              "missing": [], "truncated": False, "total_files": len(files)}
    for field, items in (("components", names), ("dependencies", [item for item in names if item != name]),
                         ("checks", checks)):
        for item in items:
            if not _append(result, field, item, MAX_RESULT_BYTES // 3, 64):
                break
    for path in files:
        target = _target(root, path)
        row = {"path": path, "owners": _owners(manifest, path), "materialized": target.is_file()}
        candidate = dict(result, files=result["files"] + [path], details=result["details"] + [row],
                         missing=result["missing"] + ([] if target.is_file() else [path]))
        if len(result["files"]) >= MAX_FILES or _size(candidate) > MAX_RESULT_BYTES:
            result["truncated"] = True
            break
        result = candidate
    return result


def _read(root: Path, path: str, budget: int = MAX_SOURCE_BYTES) -> tuple[str, bool, int] | None:
    target = _target(root, path)
    try:
        # The descriptor check also rejects non-regular files changed after inventory.
        with target.open("rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise WorkspaceError("Discovery rejected a non-regular source")
            data = source.read(min(MAX_SOURCE_BYTES, budget))
    except FileNotFoundError:
        return None
    except OSError as error:
        raise WorkspaceError("Discovery cannot read a source file") from error
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    truncated = metadata.st_size > len(data) or len(lines) > MAX_SOURCE_LINES
    return "\n".join(lines[:MAX_SOURCE_LINES]), truncated, len(data)


def _symbols(source: str, suffix: str) -> tuple[list[dict], list[dict], bool]:
    """Read Python definitions and imports or C++ and Swift declarations."""
    symbols, imports = [], []
    if suffix == ".py":
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError):
            return [], [], False

        pending = [(tree, [])]
        while pending:
            node, parents = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append({"name": ".".join(parents + [node.name]), "line": node.lineno,
                                "end_line": node.end_lineno or node.lineno,
                                "kind": "class" if isinstance(node, ast.ClassDef) else "function"})
                parents = parents + [node.name]
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append({"name": _clip(ast.get_source_segment(source, node) or "", 240),
                                "line": node.lineno})
            pending.extend((child, parents) for child in reversed(list(ast.iter_child_nodes(node))))
    elif suffix in (".cpp", ".cc", ".c", ".hpp", ".h", ".inc", ".swift"):
        declaration = re.compile(r"\b(class|struct|enum|namespace|protocol|extension|func)\s+([\w:]+)")
        function = re.compile(r"(?:^|\s|[*&])([~\w:]+)\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:\{|$)")
        blocked = {"if", "for", "while", "switch", "catch", "return", "sizeof"}
        in_comment = False
        for number, line in enumerate(source.splitlines(), 1):
            # Strip comments and strings before declaration matching.
            clean = []
            index = 0
            while index < len(line):
                if in_comment:
                    end = line.find("*/", index)
                    if end < 0:
                        break
                    in_comment, index = False, end + 2
                elif line.startswith("/*", index):
                    in_comment, index = True, index + 2
                elif line.startswith("//", index):
                    break
                elif line[index] in ("\"", "'"):
                    quote = line[index]
                    index += 1
                    while index < len(line) and line[index] != quote:
                        index += 2 if line[index] == "\\" else 1
                    index += 1
                    clean.append(" ")
                else:
                    clean.append(line[index])
                    index += 1
            code = "".join(clean)
            match = declaration.search(code)
            if match:
                symbols.append({"name": match[2], "line": number, "end_line": number, "kind": match[1]})
            elif "(" in code and not re.match(r"\s*(?:#|return\b|throw\b|else\b)", code):
                match = function.search(code)
                if match and match[1] not in blocked and code[:match.start(1)].strip():
                    symbols.append({"name": match[1], "line": number, "end_line": number, "kind": "function"})
            if re.match(r"\s*(?:#\s*include\b|import\s+)", line):
                imports.append({"name": _clip(line.strip(), 240), "line": number})
    return sorted(symbols, key=lambda item: item["line"]), imports, True


def _scan_targeted(root: Path, path: str, symbol: str | None, budget: int,
                   search_terms: list[str] | None = None) -> dict:
    """Stream a selected file and keep bounded declarations and one local window."""
    result = {"symbols": [], "matching_symbols": [], "imports": [], "lines": [], "symbol_found": False,
              "truncated": False, "read_bytes": 0, "parse_ok": True, "symbol_parser": "lexical"}
    recent = deque(maxlen=4)
    literal, exact, scopes = [], [], []
    line_count = 0
    suffix = Path(path).suffix.lower()
    target = _target(root, path)
    try:
        with target.open("rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise WorkspaceError("Discovery rejected a non-regular source")

            def read_line() -> str:
                nonlocal line_count, literal
                if (result["read_bytes"] >= budget or line_count >= MAX_TARGET_LINES
                        or search_terms is None and len(exact) >= MAX_EXCERPT_LINES
                        or symbol == "" and len(literal) >= MAX_EXCERPT_LINES):
                    return ""
                data = stream.readline(budget - result["read_bytes"])
                if not data:
                    return ""
                result["read_bytes"] += len(data)
                line_count += 1
                line = data.decode("utf-8", errors="replace")
                row = (line_count, line.rstrip("\r\n"))
                recent.append(row)
                if exact and len(exact) < MAX_EXCERPT_LINES:
                    exact.append(row)
                if literal and len(literal) < MAX_EXCERPT_LINES:
                    literal.append(row)
                elif not literal and symbol is not None and (not symbol or symbol.casefold() in line.casefold()):
                    literal = list(recent)
                if len(result["imports"]) < 20 and re.match(r"\s*(?:from\s+\S+\s+import\b|import\s+|#\s*include\b)", line):
                    result["imports"].append({"name": _clip(line.strip(), 240), "line": line_count})
                return line

            def add_definition(name: str, line: int, kind: str, indent: int = 0) -> None:
                nonlocal exact
                if suffix == ".py":
                    while scopes and scopes[-1][0] >= indent:
                        scopes.pop()
                    qualified = ".".join([item[1] for item in scopes] + [name])
                    scopes.append((indent, name))
                else:
                    qualified = name
                row = {"name": qualified, "line": line, "end_line": line, "kind": kind}
                if len(result["symbols"]) < MAX_SYMBOLS:
                    result["symbols"].append(row)
                else:
                    result["truncated"] = True
                if search_terms and all(term in qualified.casefold() for term in search_terms):
                    if len(result["matching_symbols"]) < 30:
                        result["matching_symbols"].append(row)
                    else:
                        result["truncated"] = True
                if symbol and (qualified == symbol or name == symbol) and not result["symbol_found"]:
                    result["symbol_found"] = True
                    result["matched_symbol"] = row
                    exact = list(recent)

            if suffix == ".py":
                expected = None
                try:
                    for token in tokenize.generate_tokens(read_line):
                        if token.type == tokenize.NAME:
                            if expected:
                                definition_line = next((text for number, text in recent if number == token.start[0]), "")
                                indent = len(definition_line) - len(definition_line.lstrip())
                                add_definition(token.string, token.start[0], expected, indent)
                                expected = None
                            elif token.string in ("def", "class"):
                                expected = token.string
                except (tokenize.TokenError, IndentationError, SyntaxError):
                    result["parse_ok"] = False
            else:
                block_comment = False
                while line := read_line():
                    code = line
                    if block_comment:
                        end = code.find("*/")
                        if end < 0:
                            continue
                        code, block_comment = code[end + 2:], False
                    if "/*" in code and "*/" not in code.split("/*", 1)[1]:
                        block_comment = True
                    definitions, _, _ = _symbols(code, suffix)
                    for definition in definitions:
                        add_definition(definition["name"], line_count, definition["kind"])
            result["truncated"] |= result["read_bytes"] < metadata.st_size
    except FileNotFoundError:
        return dict(result, state="not_materialized")
    except OSError as error:
        raise WorkspaceError("Discovery cannot read a source file") from error
    result["lines"] = exact or literal
    result["symbol_found"] |= bool(symbol and literal)
    return result


def _symbol_result(root: Path, path: str, allowed: set[str]) -> dict:
    if path not in allowed:
        raise WorkspaceError("Discovery requested a file outside the source index")
    loaded = _read(root, path)
    result = {"kind": "symbols", "query": path, "files": [path], "symbols": [], "imports": [],
              "missing": [], "truncated": False, "state": "ok", "parse_ok": True}
    if loaded is None:
        return dict(result, missing=[path], state="not_materialized")
    source, truncated, _ = loaded
    symbols, imports, parsed = _symbols(source, Path(path).suffix.lower())
    if truncated:
        scan = _scan_targeted(root, path, None, MAX_TARGET_BYTES - loaded[2])
        symbols, imports, parsed = scan["symbols"], scan["imports"], scan["parse_ok"]
        truncated = scan["truncated"]
        result["symbol_parser"] = "lexical"
        result["scanned_bytes"] = scan["read_bytes"] + loaded[2]
    result.update(truncated=truncated, parse_ok=parsed)
    for field, values in (("symbols", symbols), ("imports", imports)):
        for value in values:
            if not _append(result, field, value, MAX_RESULT_BYTES, MAX_SYMBOLS):
                break
    return result


def _search(root: Path, query: str, allowed: set[str]) -> dict:
    terms = [term.casefold() for term in query.split()]
    result = {"kind": "search", "query": query, "files": [], "matches": [], "missing": [],
              "truncated": False, "scanned_files": 0, "scanned_bytes": 0, "symbols_not_scanned": False}
    # Filename results come first. A literal query never becomes a regex or shell command.
    ordered = sorted(allowed)
    for path in ordered:
        if all(term in path.casefold() for term in terms):
            candidate = dict(result, files=result["files"] + [path],
                             matches=result["matches"] + [{"path": path, "kind": "filename"}])
            if len(result["files"]) >= 30 or _size(candidate) > MAX_RESULT_BYTES - 512:
                return dict(result, truncated=True)
            result = candidate
    if result["files"]:
        return dict(result, symbols_not_scanned=True)
    source_paths = [path for path in ordered if Path(path).suffix.lower() in
                    {".py", ".cpp", ".cc", ".c", ".hpp", ".h", ".inc", ".swift"}]
    path_terms = [term for term in terms if "/" in term]
    if path_terms:
        source_paths = [path for path in source_paths if all(term in path.casefold() for term in path_terms)]
        terms = [term for term in terms if term not in path_terms]
    if not terms:
        return dict(result, symbols_not_scanned=True)
    for path in source_paths:
        remaining = MAX_SCAN_BYTES - result["scanned_bytes"]
        if result["scanned_files"] >= MAX_SCAN_FILES or remaining <= 0:
            result["truncated"] = True
            break
        result["scanned_files"] += 1
        scan = _scan_targeted(root, path, None, remaining, search_terms=terms) if path_terms else None
        loaded = None if scan is not None else _read(root, path, remaining)
        if scan is not None and scan.get("state") != "not_materialized":
            result["scanned_bytes"] += scan["read_bytes"]
            result["truncated"] |= scan["truncated"]
            symbols, parsed = scan["matching_symbols"], scan["parse_ok"]
        elif loaded is not None:
            source, truncated, count = loaded
            result["scanned_bytes"] += count
            result["truncated"] |= truncated
            symbols, _, parsed = _symbols(source, Path(path).suffix.lower())
        else:
            symbols, parsed = [], True
        if loaded is None and (scan is None or scan.get("state") == "not_materialized"):
            if len(result["missing"]) < 20 and _size(result) + len(path.encode("utf-8")) < MAX_RESULT_BYTES - 512:
                result["missing"].append(path)
            else:
                result["truncated"] = True
            continue
        if not parsed:
            result["truncated"] = True
        for symbol in symbols:
            if all(term in symbol["name"].casefold() for term in terms):
                row = {"path": path, "kind": "symbol", "name": symbol["name"], "line": symbol["line"]}
                candidate = dict(result, files=list(dict.fromkeys(result["files"] + [path])),
                                 matches=result["matches"] + [row])
                if len(result["matches"]) >= 30 or _size(candidate) > MAX_RESULT_BYTES - 512:
                    return dict(result, truncated=True)
                result = candidate
    return result


def discover(root: Path, request: dict, manifest: dict, tracked: dict[str, str], allowed: set[str]) -> dict:
    """Answer one model request without selecting task scope."""
    query = _query(request)
    # Revalidate supplied indexes so callers cannot expose private or linked paths.
    permitted = set(allowed_files(root, tracked)) & set(allowed)
    kind = request.get("kind")
    if kind == "component":
        if query not in manifest["components"]:
            raise WorkspaceError("Discovery requested an unknown component")
        return _component(root, query, manifest, permitted)
    if kind == "search":
        return _search(root, query, permitted)
    if kind == "symbols":
        return _symbol_result(root, query, permitted)
    raise WorkspaceError("Discovery requested an unknown operation")


def excerpt(root: Path, request: dict, allowed: set[str]) -> dict:
    """Return a bounded source window near a named definition."""
    path, symbol = request.get("path"), request.get("symbol", "")
    if not isinstance(path, str) or path not in allowed:
        raise WorkspaceError("Discovery requested a file outside the source index")
    if not isinstance(symbol, str) or len(symbol.encode("utf-8")) > MAX_QUERY_BYTES or any(ord(c) < 32 for c in symbol):
        raise WorkspaceError("Discovery needs a short source symbol")
    loaded = _read(root, path)
    result = {"path": path, "symbol": symbol, "state": "ok", "symbol_found": False,
              "start_line": 1, "symbols": [], "imports": [], "source": "", "truncated": False,
              "parse_ok": True}
    if loaded is None:
        return dict(result, state="not_materialized")
    source, truncated, _ = loaded
    definitions, imports, parsed = _symbols(source, Path(path).suffix.lower())
    targeted = None
    if truncated:
        scan = _scan_targeted(root, path, symbol, MAX_TARGET_BYTES - loaded[2])
        definitions, imports, parsed = scan["symbols"], scan["imports"], scan["parse_ok"]
        truncated = scan["truncated"]
        targeted = scan["lines"]
        result.update(symbol_parser="lexical", scanned_bytes=scan["read_bytes"] + loaded[2],
                      symbol_found=scan["symbol_found"])
    result.update(truncated=truncated, parse_ok=parsed)
    for definition in definitions[:MAX_SYMBOLS]:
        if not _append(result, "symbols", definition["name"], MAX_EXCERPT_BYTES // 3, MAX_SYMBOLS):
            break
    for item in imports[:20]:
        if not _append(result, "imports", item, MAX_EXCERPT_BYTES // 3, 20):
            break
    result["truncated"] |= len(definitions) > MAX_SYMBOLS or len(imports) > 20
    exact = next((item for item in definitions if symbol and
                  (item["name"] == symbol or item["name"].split(".")[-1] == symbol)), None)
    lines = source.splitlines()
    hit = next((index for index, line in enumerate(lines) if symbol and symbol.casefold() in line.casefold()), None)
    start = max(0, (exact["line"] - 1 if exact else hit or 0) - 3)
    if targeted is None:
        result.update(symbol_found=exact is not None or hit is not None, start_line=start + 1)
        targeted = [(index + 1, lines[index]) for index in range(start, min(start + MAX_EXCERPT_LINES, len(lines)))]
    else:
        result["start_line"] = targeted[0][0] if targeted else 1
    window = []
    for number, line in targeted:
        row = f"{number}: {line}"
        candidate = dict(result, source="\n".join(window + [row]))
        if _size(candidate) > MAX_EXCERPT_BYTES:
            result["truncated"] = True
            break
        window.append(row)
    result["source"] = "\n".join(window)
    result["truncated"] |= start > 0 or start + len(window) < len(lines)
    return result
