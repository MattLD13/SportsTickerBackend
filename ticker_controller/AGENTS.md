# ticker_controller Agent Guide

Renderer/controller package for 384x32 LED frames.

## Key Files
- `controller.py`: `TickerStreamer`, polling, logo cache, mode routing, render loop.
- `modes/`: mode-specific drawing code.
- `config.py`: panel dimensions, backend URL, asset cache directory.
- `stadium.py`: generic sports card renderer.

## Rendering Rules
- Always preserve `PANEL_W=384` and `PANEL_H=32` assumptions unless intentionally changing hardware target.
- Use `draw_tiny_text`/`draw_hybrid_text` for pixel text where possible.
- After display changes, render with `tools/fetch_and_render.py` or `tools/render_racing_previews.py`.
- Remote logos/cars should be prefetched in `controller.py` and cached by exact URL+size.

## Racing Modes
- `modes/indycar.py` owns the shared racing-style full screen and scroll layout.
- `modes/f1.py` maps F1 payloads into that layout and draws generated F1 car silhouettes using team colors.
- Full-screen racing cards are static items; scrolling cards are 128x32 items in the normal strip.
