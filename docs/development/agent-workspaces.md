# Selective agent workspaces

## Ownership

`tools/workspaces/manage.py` owns task workspace creation, expansion, and evidence.
`.github/agent-workspaces.json` owns component dependencies, context files, build files, and checks.
Git owns commits, branches, staging, and history.

Workspace selection does not control deployment selection.
`.github/deployment-paths.json` continues to own deployment selection.

## Create a task workspace

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
The first validated task boundary is Mini sports.

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
