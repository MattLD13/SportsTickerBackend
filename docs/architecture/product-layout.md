# Product folder design

```text
ticker-server/
  sports_ticker/       # server package and unchanged showcase pages
  backend_ops/         # worker, release, and recovery packages
  deploy/              # backend service units
ticker-six/
  ticker_core/         # Six runtime and rendering package
ticker-mini/           # PlatformIO firmware project
ticker-control/        # Xcode and Swift package project
ai/                    # AI workspace tools, tests, guides, and manifest
tests/                 # shared Python, native, and fixture checks
tools/                 # rendering, diagnostics, deployment, and device utilities
docs/                  # architecture, contracts, operations, and research
.github/               # GitHub workflows and required integration files
```

Python package names stay stable inside the product folders.
The editable workspace installation exposes those packages to development tools.
`run.py` loads explicit product paths from `release-layout.json` for device startup.
Root installation and update scripts remain stable public entry points.

Backend archive packaging maps product source paths to the existing runtime paths.
Deployed backend services keep their current package imports and working directories.
Workspace selection, deployment selection, build commands, and test commands use the new source paths.

AI tool discovery files remain in the locations required by each tool.
The implementations, manifest, tests, guides, fixtures, and benchmark live in `ai/`.
Historical review artifacts retain their original source-revision records.

Showcase templates, scripts, styles, images, and examples retain their contents.
Only generated source provenance records the new paths and build-tool hash.
No showcase page design or example frame changes belong in this task.

## Branch and rollout

This work remains on `refactor/product-repository-layout`.
The preparation commit is `64d14de3a4f9b926ba91061d284e112036bca0b5` before the physical product moves.
Existing Six devices need that preparation release before the new folder layout.
Read [the migration notes](../development/product-layout-migration.md) before merging or deploying this branch.
The publish job requires `refs/heads/main`. Pull-request validation cannot deploy products.

## Evidence

The pre-move updater checks passed 11 tests for both declared layouts and frame-health behavior.
The first renamed-layout run passed 1,579 tests and exposed four AI workspace setup failures.
Three failures require the committed renamed tree. One required the test fixture's moved manifest directory.
Archive checks keep deployed package paths separate from repository source paths.

Final validation passed all 1,583 Python tests and 1,173 critical tests.
The relocated Mini project built successfully with PlatformIO.
The native production renderer generated 135 layouts and 4,072 frames.
All 172 static images and animation atlases match the existing gallery at the decoded pixel level.
PNG encodings can differ between host libraries. The branch retains the existing example images.
Showcase page sources, firmware sources, and iOS sources remain byte-identical after relocation.
