# Testing

Run the focused V2 suite from the repository root:

```powershell
python -m pytest -q
```

The tests live in `tests/rewrite/`. They use temporary SQLite files, injected provider ports, and memory frame sinks. They do not start the production scheduler or require panel hardware.

Use the renderer for display verification:

```powershell
python tools\render_rewrite.py --snapshot tests\rewrite\debug\v2_render_snapshot.json --mode sports --item-id mlb-live --pinned --no-prefetch --output previews\mlb.png
```

Run the controller contract harness:

```powershell
python tools\v2_control_harness.py --self-test
```

The harness checks sports filters, pin, unpin, strip replacement, and live delay without an iOS build.

For every code change, keep one focused boundary test. If pixels change, save and inspect a real 384x32 frame. Do not keep tests for deleted V1 routes or controller code.
