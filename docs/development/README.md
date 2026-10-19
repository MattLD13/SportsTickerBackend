# Contributing

Read [AGENTS.md](../../AGENTS.md) before changing code.
Read nested agent guides for the directories you change.
Preserve existing local changes and runtime data.

## Local development

Create a Python virtual environment and install runtime dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The Pi uses `requirements.txt`. The backend uses `requirements-backend.txt`.
The `dev` dependency group in `pyproject.toml` describes optional development tools.
It does not replace deployment installation or define a distributable Python package.

Install development tools:

```powershell
python -m pip install "pytest>=8,<9" "ruff>=0.14,<0.15" "mypy>=1.18,<2"
```

Copy `.env.example` to `.env` for local backend settings.
Keep credentials in `.env` and exclude them from Git.

## Static checks

Run static checks from the repository root:

```powershell
python -m ruff check sports_ticker ticker_core
python -m mypy
```

Ruff starts with syntax and selected correctness rules. Mypy starts with `sports_ticker/markets.py`.
Expand coverage after resolving findings in the affected modules.

`.github/workflows/deploy.yml` owns Python checks, shared layout checks, Mini firmware validation, and publishing.
Its publishing steps have Ticker Server, Ticker Mini, and Ticker Six sections.
Only affected publishing steps run.
`.github/workflows/ios.yml` builds the iOS app when its sources change.


## Validation

`pyproject.toml` selects `tests/python` and retains the existing pytest patterns and markers.
Read [tests/AGENTS.md](../../tests/AGENTS.md) for focused validation and release checks.
If you change display output, render and inspect a real 384x32 PNG.
Read [tools/AGENTS.md](../../tools/AGENTS.md) before changing preview tools.

## Change notes

Before a commit, record the behavior owner, the removed path, and the real input and output.
Use the writing rules in `AGENTS.md` for documentation, comments, and commit messages.
If the user requests publication, commit the requested changes and push directly to `main`.
