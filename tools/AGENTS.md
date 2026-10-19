# Tools guide

Run tools from the repository root.
Read the root `AGENTS.md` before changing a tool.

## Ownership

| Folder | Purpose |
|---|---|
| `rendering/` | Render production frames and build the public layout gallery. |
| `mini/` | Generate shared firmware data and inspect Mini hardware. |
| `diagnostics/` | Inspect Ticker Six, provider data, streams, and hardware. |
| `deployment/` | Select deployment scope and provision device credentials. |
| `benchmarks/` | Measure rendering and transport costs. |
| `experiments/` | Retain optional design and model experiments. |
| `assets/` | Store source assets used by local tools. |

## Commands

Render a production frame:

```powershell
python tools/rendering/render_frame.py --snapshot tests/fixtures/display/v2_render_snapshot.json --mode sports --item-id nfl-live --no-prefetch --output previews/nfl.png
```

Build and verify the public gallery:

```powershell
python tools/rendering/build_demo_layouts.py
python tools/rendering/verify_public_demo.py
```

Check shared Mini data:

```powershell
python tools/mini/generate_mini_fields.py --check
python tools/mini/generate_mini_ui.py --check
python tools/mini/generate_mini_weather.py --check
```

## Rules

Use production providers, contracts, and renderers.
Keep file access and network access outside rendering functions.
Store generated images, captures, and reports under `previews/`.
Keep device credentials outside Git and tool output.
If a tool changes hardware state, require an explicit command option and document its recovery path.
Remove tools that depend on deleted V1 modules.
