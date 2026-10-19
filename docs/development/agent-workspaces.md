# Selective agent workspaces

## Ownership

`tools/workspaces/manage.py` owns task workspace creation, expansion, and evidence.
`.github/agent-workspaces.json` owns component dependencies, context files, build files, and checks.
Git owns commits, branches, staging, and history.

Workspace selection does not control deployment selection.
`.github/deployment-paths.json` continues to own deployment selection.

## Selective task context

| Part | Responsibility |
|---|---|
| `AGENTS.md` | Shared repository rules. The file does not create an agent. |
| Scoped `AGENTS.md` files | Rules for the directories involved in the task. |
| `CLAUDE.md` and `GEMINI.md` | Small bridges to the shared guide. |
| Startup hooks | Reuse an existing packet or provide search guidance without a model call. |
| GPT-6 Luna | Plan context only after an explicit `--plan` or `--replan` request. |
| Workspace manager | Enforce dependency, ownership, and credential rules. |
| Coding agent | Implement the task, validate the change, and report results. |

`AGENTS.md` owns shared agent instructions.
`CLAUDE.md` and `GEMINI.md` import that one guide.
Copilot's bridge points to the same guide. Cursor uses `AGENTS.md` directly.

| Agent | Automatic entry |
|---|---|
| Codex | `.codex/hooks.json` uses `SessionStart`, `SubagentStart`, and `UserPromptSubmit`. |
| Claude Code | `.claude/settings.json` uses the same events. |
| Gemini CLI | `.gemini/settings.json` uses `SessionStart` and `BeforeAgent`. |
| Cursor, Copilot, and other compatible agents | Repository instructions describe normal search and optional context planning. |

After the client trusts repository hooks, each prompt receives lightweight guidance or a reference to an existing packet.
Hooks never start Luna, inspect prompt text, or create a task packet.
They perform no source edits, test execution, checkout changes, or hardware operations.

Use ordinary targeted searches for small tasks with a clear code location.
Read the relevant scoped instructions and source sections.
These tasks do not require a startup command or model call.

For a known component, select a manifest slice directly:

```powershell
python tools/workspaces/start.py --slice mini-sports --task "Fix Mini hockey shootout rendering"
```

This command resolves component dependencies and checks without Luna.
The manifest and sparse workspace tools remain available independently of model planning.

For broad, unfamiliar, or cross-component tasks, request Luna explicitly:

```powershell
python tools/workspaces/start.py --plan --task "Trace shared hockey shootout data through both renderers"
```

The coding agent decides when planning is useful. Hooks do not classify tasks or invoke another agent.
The result identifies a task packet, scope ID, context count, and build count.
Read the packet, then only the source sections needed for the task.
Task evidence stays under `.git/agent-context/<scope-id>/`.
The manager hashes task text instead of storing raw prompts.

Unknown edit ownership includes shared consumers.
Luna suggestions cannot narrow a shared contract change below its affected consumers.

For a dependency expansion, use the current packet's scope ID:

```powershell
python tools/workspaces/start.py --scope <scope-id> --slice weather --task "Inspect forecast integration" --reason "The alert depends on forecast state"
python tools/workspaces/start.py --scope <scope-id> --path tools/workspaces/new_helper.py --reason "Add the context helper"
```

For an independent task in the same client session, reset that scope:

```powershell
python tools/workspaces/start.py --scope <scope-id> --new-task --slice mini-weather --task "Fix Mini weather"
```

Continuation prompts reuse the recorded plan without another model call.
For a broad task that needs another model plan, request it explicitly:

```powershell
python tools/workspaces/start.py --scope <scope-id> --replan --task "Also inspect Mini artwork scheduling"
```

New plans preserve the original task scope and add discovered dependencies.
Resuming or compacting a session restores the packet reference.
The startup tool uses the current checkout, including existing local edits.
Its recorded SHA identifies that checkout. It does not certify that the commit exists on GitHub.
For isolated work pinned to GitHub, use the sparse workspace command below.

## Luna planning

Install Codex CLI and sign in with the account that can use `gpt-6-luna`.
The planner uses that login. It does not require a separate API key.
Every supported agent client can request this same local planner.
A normal prompt or session start does not invoke it.

1. Luna receives a compact component catalog, entry paths, and bounded filename hints.
2. Luna can request a component inventory, literal file search, symbol list, or source excerpt.
3. The manager limits discovery and inspection to eight requests. Each source excerpt contains at most 100 lines.
4. Luna returns slices, source entry points, useful symbols, expected edits, checks, and reasons.
5. The manager validates paths, adds dependencies, and includes consumers for shared edits.
6. The coding agent receives the resulting packet and performs implementation.

The planner has no shell, browsing, delegation, or hardware tools.
It runs outside the repository in a temporary directory.
Its child process disables startup hooks, inherited project instructions, and memory injection.
This prevents recursive planner startup.
The planner does not receive the full conversation or every source file.
The manager sends only requested excerpts and excludes credential paths.

Planning has a 60-second limit and at most three model rounds.
Each evidence round permits at most two discovery or inspection requests. The final round must return a plan.
Each request has a 48,000-byte limit. All requests together have a 144,000-byte limit.
These limits measure input text. They exclude the transport schema and client overhead.
The initial catalog has a 16,000-byte limit.
Filename hints contain at most 16 paths and 6,000 bytes.
Hints rank literal filename and path words. They read no source and do not choose components or slices.
Only the latest bounded discovery responses enter the next request. Previously disclosed paths remain available.
The model cannot select an undisclosed path.
Shared changes retain the declared owner and consumer entry points even when the model omits them.
The task record includes model identity, time, tokens, request bytes, inspection paths, and bounded discovery counts.
Raw prompts, excerpts, and client event streams do not enter the task record.
If planning fails, `failures.json` retains its available usage without overwriting the previous valid packet.
Missing usage remains unknown. Cached input and reasoning remain subsets of the reported input and output totals.
A normal continuation reuses a valid packet without another model call.
A changed manifest or planner version invalidates the cached selection.
If the selection is invalid, choose explicit slices or request Luna again.
Invalidation never starts a model automatically.
If explicit planning fails, the command reports failure. It does not select scope through hidden keyword rules.
The existing explicit `--slice` and `--path` commands remain available for agent-directed scope changes.

The runner uses [Codex structured output](https://learn.chatgpt.com/docs/non-interactive-mode) with the [GPT-6 Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna).

The model selects useful context. Code owns required dependencies and credential exclusions.
If an expected edit reaches a shared owner, the manager includes every declared consumer.
Model suggestions do not override repository instructions or authorize publishing.

The [NFL comparison](../research/2026-10-19-nfl-alert-agent-comparison.md) records the measured reason for selective planning.

## Bounded discovery without a model

The coding agent can inspect paths and symbols without invoking Luna:

```powershell
python tools/workspaces/find.py --search "station_retry"
python tools/workspaces/find.py --search "sports_ticker/providers ScoreAlertTracker"
python tools/workspaces/find.py --component mini-runtime
python tools/workspaces/find.py --symbols sports_ticker/providers/score_alerts.py
python tools/workspaces/find.py --excerpt sports_ticker/providers/score_alerts.py --symbol ScoreAlertTracker
```

Search uses literal words. It does not execute expressions or shell text.
Filename matches return without scanning source. A path prefix can restrict symbol discovery.
Results report truncation, missing sparse files, and source scan limits.
Selected-file lookups scan at most one MiB or 20,000 lines and return a bounded window.
The finder preserves the same credential exclusions and link checks as the workspace manager.
If a result is truncated, narrow the query or inspect another declared component.
Use `start.py --path` with the current scope and a reason when discovery expands a recorded task.

## Context evaluation

The benchmark checks three predefined task classes without model calls by default:

```powershell
python tools/benchmarks/context_discovery.py --output previews/context-evaluation/offline.json
```

A live comparison requires an explicit flag, a frozen baseline planner, and an output file:

```powershell
python tools/benchmarks/context_discovery.py --live --baseline-planner previews/context-evaluation/baseline_planner.py --repeat 2 --output previews/context-evaluation/report.json
```

Expected paths and consumers remain outside both model inputs.
The report measures request bytes, time, model tokens, selected context coverage, and shared consumer coverage.
Every failed attempt remains in the all-run totals. Paired comparisons require two completed runs with complete usage.
The report separates model-selected paths from the effective context after mandatory ownership expansion.
Atomic checkpoints record each attempt before it starts and after it finishes.
Interrupted attempts retain unknown usage. A timeout never claims complete accounting.
This benchmark measures planning and discovery. It does not establish implementation correctness or total coding cost.

## Client limits

Start a new agent session after changing hook configuration.
Clients control repository trust and hook review. This repository does not bypass those controls.
Instruction-only clients depend on the agent following `AGENTS.md`.
An agent that ignores repository instructions and hooks cannot receive enforced automatic setup from this repository.
Existing conversation history remains in context. A focused packet does not erase earlier messages.

## Create an isolated task workspace

Use Python 3.10 or newer and Git with protocol version 2 and sparse checkout support.
Use a GitHub remote with blob filtering support.
Use the full commit SHA from GitHub.
The commit must contain every selected manifest path.

```powershell
$taskSha = gh api repos/MattLD13/SportsTickerBackend/commits/main --jq .sha
python tools/workspaces/manage.py plan --slice mini-sports --sha $taskSha
python tools/workspaces/manage.py create --slice mini-sports --sha $taskSha --dest C:/agent-workspaces/hockey --task "Fix Mini hockey shootout rendering"
```

The manager fetches one pinned commit with `blob:none` filtering and checks out selected files with non-cone sparse patterns.
The workspace starts with detached `HEAD` and a clean Git diff.
The source checkout remains unchanged.
The manager never copies source checkout state, device data, or environment files.
If the remote lacks blob filtering, creation fails before fetching repository objects.

The manager validates a local control manifest against the pinned repository tree.
It records the manifest bytes and SHA-256 digest separately from the task base SHA.
This permits one checked-in manifest to prepare compatible earlier commits.
If a selected path does not exist at the pin, creation fails.

## Read the task packet

Open `<workspace>/.git/agent-workspace/task.md`.
The packet contains the task, ownership, context files, and check commands.
Read the context files first.
The build set includes additional files needed by imports and compilation.
`state.json` lists both sets and preserves their initial versions.

For `mini-sports`, the initial context excludes music, weather, stocks, flights, dashboards, iOS, and Six sports renderers.
Python package initialization imports several providers during focused tests.
The build set includes those provider modules without adding them to initial context.
The native Mini protocol header includes other pane headers.
Those headers also remain build files.

The manifest starts with Mini sports, Six sports, shared sports, music, weather, stocks, flights, airports, golf, racing, and news slices.
Feature slices share dependencies where the current code shares imports.
The first validated task boundary is Mini sports. Runtime and Mini feature slices have separate initial context.

## Expand a workspace

If a task changes shared behavior, select every consumer:

```powershell
python tools/workspaces/manage.py create --slice mini-sports --shared-change --sha $taskSha --dest C:/agent-workspaces/shared-hockey --task "Change shared hockey behavior"
```

If a dependency appears during work, record its reason:

```powershell
python tools/workspaces/manage.py expand --workspace C:/agent-workspaces/hockey --component sports-server --reason "The shootout field changes both device contracts"
python tools/workspaces/manage.py expand --workspace C:/agent-workspaces/hockey --path esp32_hub75/src/mini/rendering/new_helper.h --reason "Add a shared pane helper"
```

An explicit shared component expansion includes Mini, Six, and iOS consumers.
Unknown file ownership also includes shared components and consumers.
The manager adds ancestor `AGENTS.md` files automatically.
Expansion preserves existing edits and records the added files, context, and reason.
Record new files with `--path` before editing them.

## Run focused checks

Install the dependencies from `requirements.txt` and install pytest in your development environment.
Run commands from the source checkout:

```powershell
python tools/workspaces/manage.py run --workspace C:/agent-workspaces/hockey --check sports-contracts
python tools/workspaces/manage.py run --workspace C:/agent-workspaces/hockey --check mini-fields
python tools/workspaces/manage.py run --workspace C:/agent-workspaces/hockey --check mini-ui
python tools/workspaces/manage.py run --workspace C:/agent-workspaces/hockey --check mini-native
python tools/workspaces/manage.py audit --workspace C:/agent-workspaces/hockey
```

Each run records its command, exit code, duration, source revision, diff digest, and log path.
It also records the installed workspace manager digest.
An input digest includes selected file content, new files, missing files, and staged changes.
The record identifies inputs that changed during a check.
Evidence stays inside Git metadata and cannot enter `git add -A`.
`mini-native` requires a C++17 compiler named `g++`.
It fetches the ArduinoJson 7.4.3 commit recorded by `tools/workspaces/native_hockey.py`.
`{tools}` in a check command selects the installed manager tools directory outside the task workspace.
It compiles the production protocol and renderer headers against the real hockey vectors.
The dependency and executable stay inside Git metadata.

The selected Mini build validates native protocol and rendering code.
It does not build or flash the complete device firmware.
The existing firmware configuration header contains device credentials, so task workspaces exclude it.
Complete firmware builds remain in the existing release workflow.

## Return changes

Keep edits and commits as ordinary Git changes.
The audit checks committed changes, staged changes, unstaged changes, and new files against the recorded scope.
It rejects unrecorded files and shared edits without consumer expansion.
It does not decide whether an edit implements the requested task.
Review the ordinary Git diff before returning changes.

Run focused checks during work.
Before publishing, run full repository CI in the existing workflow from a full checkout.
That workflow validates cross-component behavior and selects deployments independently.
The workspace manager never publishes, merges, pushes, or deploys code.

Sparse checkout controls materialized files. It does not restrict access to Git history or remote objects.
The manager blocks known credential paths, private keys, runtime data, and symbolic links.
It does not replace secret scanning or repository access controls.
Keep production credentials and customer data outside Git.

## Validation commands

```powershell
python -m pytest -q tests/python/operations/test_agent_workspaces.py
python -m pytest -m critical -q
python -m pytest -q
```
