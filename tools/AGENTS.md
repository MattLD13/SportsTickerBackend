# tools/ Agent Guide

Local utilities for debugging backend data and renderer output. Run everything from the **repo root**.

## Scripts

### `fetch_and_render.py`
General-purpose render tool. Fetches from the running backend and saves PNGs.
```
python tools/fetch_and_render.py --mode <mode> --view <scroll|pin|both> --save previews/<sport>/name.png
```
- `--mode`: sport/mode name, e.g. `nascar`, `nascar_full`, `indycar`, `f1`, `sports`
- `--view scroll`: renders the 128×32 scroll card strip
- `--view pin`: renders the 384×32 full pinned frame
- Requires the backend server to be running (`python -m sports_ticker` or similar)

### `render_racing_previews.py`
Renders racing (IndyCar / F1 / NASCAR) scroll+pin PNGs directly from the live API or backend.
```
python tools/render_racing_previews.py --mode <indycar|f1|nascar|both> --out-dir previews/<sport>
```
- Falls back to live API fetch if the backend has no data for that sport.
- Saves `<mode>_scroll.png` and `<mode>_pin.png` in `--out-dir`.

### `dump_backend_snapshot.py`
Prints normalized game payloads from the backend as JSON — useful for inspecting raw data.
```
python tools/dump_backend_snapshot.py
```

## Generating GIFs to test scroll animation

Use this pattern to render a multi-frame GIF showing the pinned view animating:

```python
import sys, time
sys.path.insert(0, '.')
from sports_ticker.fetchers.sports import SportsFetcher
from tools.fetch_and_render import make_renderer, prefetch_logos, render_pin
from PIL import Image

# Fetch live data
fetcher = SportsFetcher("New York", 40.7128, -74.0060)
game = fetcher._fetch_nascar(force=True)   # or _fetch_f1 / _fetch_indycar

renderer = make_renderer('nascar')         # mode name matches sport
renderer.mode = 'nascar'
prefetch_logos(renderer, [game])

SCALE, FPS, N_FRAMES = 4, 15, 60
frames = []
for _ in range(N_FRAMES):
    f = render_pin(renderer, game)
    frames.append(f.resize((f.width*SCALE, f.height*SCALE), Image.Resampling.NEAREST).convert('RGB'))
    time.sleep(1.0 / FPS)

frames[0].save('previews/nascar/scroll_test.gif', save_all=True,
               append_images=frames[1:], loop=0, duration=int(1000/FPS))
```

- `SCALE=4` makes each 384×32 frame → 1536×128 so it's readable.
- `time.sleep(1/FPS)` advances real `time.time()` so scroll state progresses.
- Extract key frames for quick review: `gif.seek(i); gif.copy().save('frame.png')`

## Preview folder layout

```
previews/
  nascar/     ← NASCAR scroll/pin PNGs and GIFs
  f1/         ← F1 scroll/pin PNGs
    live/     ← renders from live OpenF1 API
  indycar/    ← IndyCar scroll/pin PNGs
```

Save previews into the appropriate sport subfolder, not the root `previews/`.

## Notes
- `make_renderer(mode)` returns a `TickerStreamer` with fonts and logo cache pre-initialized.
- `prefetch_logos(renderer, games)` downloads and caches all logos/car images before rendering.
- `render_pin(renderer, game)` calls the sport-specific full-screen draw method based on `game['sport']`.
- `render_scroll(renderer, games)` renders the full scroll strip of all games.
- The scroll animation state (`_ic_info_scroll_x`) lives on the renderer instance — reuse the same renderer across frames so the position advances continuously.
