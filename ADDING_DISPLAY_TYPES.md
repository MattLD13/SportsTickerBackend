# Adding a New Display Type to the LED Matrix

How to add either a **scrolling card** (appears in the horizontally-scrolling strip) or a **fullscreen/static card** (holds the whole 384×32 display for `PAGE_HOLD_TIME` seconds) to the SportsTicker LED matrix.

The physical display is **384×32 pixels** — six chained 64×32 HUB75 panels.  
`PANEL_W = 384`, `PANEL_H = 32`, `PAGE_HOLD_TIME = 8.0` s — all in `ticker_controller/config.py`.

---

## How the render loop works

Each data poll cycle, the controller classifies every game object into one of two buckets:

```
static_items    → shown fullscreen, one at a time, for PAGE_HOLD_TIME (8 s) each
scrolling_items → stitched into a horizontal strip that scrolls continuously
```

After the scroll strip completes one full pass, the loop pops the next `static_items` entry and holds it for 8 s, then resumes scrolling. If there are no scrolling items it falls back to displaying static items back-to-back.

**The classification logic is in `controller.py` around line 871:**

```python
# → static_items
if (g_type == 'weather'
        or sport.startswith('clock')
        or is_golf_fullscreen
        or is_indycar_fullscreen
        or is_music
        or g_type == 'flight_visitor'
        or g_type == 'flight_airport_hud'):
    static_items.append(g)

# → static_items  (sports_full / soccer_full mode overrides)
elif self.mode in ('sports_full', 'soccer_full') and <not a special type>:
    static_items.append(g)

# → scrolling_items (everything else)
else:
    scrolling_items.append(g)
```

---

## Option A — Scrolling card

A scrolling card is a fixed-width `PIL.Image` that is pasted into the horizontal strip.  
Common widths: **64 px** (compact), **96 px**, **128 px**, **192 px**.  
Cards wider than `PANEL_W` (384) will still scroll but look odd.

### Step 1 — Write the renderer

Add a method to the relevant mixin in `ticker_controller/modes/`:

```python
# ticker_controller/modes/my_sport.py

from PIL import Image, ImageDraw
from ..config import PANEL_H
from ..fonts import draw_tiny_text

class MySportMixin:
    def draw_my_sport_card(self, game: dict) -> Image.Image:
        W = 128  # card width in pixels
        img = Image.new('RGBA', (W, PANEL_H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        # draw whatever you want on `img` / `d`
        draw_tiny_text(d, 2, 4,  game.get('home_abbr', '???'), (255, 255, 255))
        draw_tiny_text(d, 2, 14, str(game.get('home_score', '')), (200, 220, 255))

        return img
```

`draw_tiny_text(draw, x, y, text, color_rgb)` — 5×5 bitmap font, each character advances **5 px**.  
Helper: `_tiny_width(text) = len(text) * 5`.

#### Text that needs to scroll horizontally

Use `_draw_tiny_clipped` (defined in `ticker_controller/modes/racing.py`, copy the pattern):

```python
import time as _time

# inside your renderer:
scroll_pos = _time.time() * 18.0   # 18 px/s — adjust to taste
_draw_tiny_clipped(img, x=4, y=4, text=long_name,
                   color=(210, 215, 220), max_w=80, scroll_pos=scroll_pos)
```

`_draw_tiny_clipped` draws text into an off-screen buffer and crops it to `max_w`.  
When `text_w > max_w` it loops the text with a 20 px gap — no external state needed.  
Pass `scroll_pos=0.0` to clip without scrolling.

### Step 2 — Register the width in `get_item_width`

`controller.py → get_item_width()`:

```python
if t == 'my_sport_card':
    return 128   # must match what your renderer returns
```

Without this the strip builder uses the fallback `calc_card_width` formula, which is wrong for custom types.

### Step 3 — Dispatch in `draw_single_game`

`controller.py → draw_single_game()`, before the final `stadium.render` fallback:

```python
if g_type == 'my_sport_card' or g_sport == 'my_sport':
    img = self.draw_my_sport_card(game)
    self.game_render_cache[game_hash] = img   # cache it — data doesn't change mid-frame
    return img
```

Cache the result unless your card animates every frame (see Option B notes below).

### Step 4 — Produce the game object in the backend

Your fetcher's `format_for_ticker()` (or wherever you build the game list) must return a dict with at minimum:

```python
{
    'id':    'my_sport_abc123',   # unique string — used for scroll-position continuity
    'type':  'my_sport_card',     # must match the string you check in draw_single_game
    'sport': 'my_sport',          # used for mode-level filtering
    'is_shown': True,             # backend sets this; controller skips False entries
    # ... your data fields ...
}
```

The controller polls `/data` every 0.5 s. Only items with `is_shown: True` reach the renderer.

---

## Option B — Fullscreen / static card

A fullscreen card occupies the entire 384×32 display for `PAGE_HOLD_TIME` (8 s), then the loop advances to the next static item.

### Step 1 — Write the renderer

Same as Option A but `W = PANEL_W` (384):

```python
from ..config import PANEL_H, PANEL_W, PAGE_HOLD_TIME
import time as _time

class MySportMixin:
    def draw_my_sport_fullscreen(self, game: dict) -> Image.Image:
        W, H = PANEL_W, PANEL_H   # 384 × 32
        img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        # Page through data — auto-advances every PAGE_HOLD_TIME seconds
        entries = game.get('entries', [])
        n    = max(len(entries), 1)
        ROWS = 4
        page   = int(_time.time() / PAGE_HOLD_TIME)
        offset = (page * ROWS) % n

        for row_idx in range(ROWS):
            entry = entries[(offset + row_idx) % n]
            y = 4 + row_idx * 7   # 4 rows at y=4,11,18,25
            draw_tiny_text(d, 4, y, entry.get('name', ''), (255, 255, 255))

        return img
```

### Step 2 — Register the width

```python
# controller.py → get_item_width()
if t == 'my_sport_fullscreen':
    return PANEL_W
```

### Step 3 — Route to `static_items` in the classification block

`controller.py` around line 871 — add your condition:

```python
is_my_sport_fullscreen = (g_type == 'my_sport_fullscreen' or sport == 'my_sport') and self.mode == 'my_sport'

if (g_type == 'weather'
        or ...
        or is_my_sport_fullscreen):   # ← add this
    static_items.append(g)
```

### Step 4 — Dispatch in `draw_single_game` (no cache)

Fullscreen cards that animate every frame must **not** be cached:

```python
if g_type == 'my_sport_fullscreen':
    return self.draw_my_sport_fullscreen(game)   # no cache — re-renders each frame
```

The render loop re-calls `draw_single_game` every ~33 ms while `showing_static` is True and the game type is in the "re-render each frame" list (line ~627):

```python
# controller.py line ~627
if sport.startswith('clock') or game_type in ('music', 'golf', 'masters', 'weather', 'indycar_dashboard') or sport in ('music', 'golf', 'masters', 'indycar'):
    self.static_current_image = self.draw_single_game(self.static_current_game)
```

Add your type/sport string to that tuple so your card is re-rendered each frame.  
If your card is truly static (no animation), you can cache it and skip this.

### Step 5 — Add the mode (optional)

If you want a dedicated mode (`mode == 'my_sport'`), add it to `leagues.py`:

```python
# sports_ticker/leagues.py
VALID_MODES = {
    ...,
    'my_sport',
}
```

And wire the backend's state route to only return your fullscreen card when that mode is active.

---

## Quick-reference checklist

### Scrolling card
- [ ] Renderer method returns `Image.Image` of fixed width W
- [ ] `get_item_width()` returns W for your type string
- [ ] `draw_single_game()` dispatches to your renderer and caches result
- [ ] Backend game object has `type`, `sport`, `id`, `is_shown: True`

### Fullscreen / static card
- [ ] Renderer method returns `Image.Image` of width `PANEL_W` (384)
- [ ] `get_item_width()` returns `PANEL_W` for your type string
- [ ] Classification block routes your type/sport to `static_items`
- [ ] `draw_single_game()` dispatches to your renderer — **no cache** if animated
- [ ] Re-render-each-frame condition (line ~627) includes your type/sport string
- [ ] `VALID_MODES` updated if you added a new mode

---

## Existing examples to copy from

| Card type | Width | File | Renderer |
|---|---|---|---|
| Scrolling sport score | 64 px | `modes/sports.py` | `stadium.render()` |
| Golf leaderboard | 384 px fullscreen | `modes/golf.py` | `draw_leaderboard_card()` |
| IndyCar compact | 96 / 128 px | `modes/racing.py` | `draw_indycar_car_compact()` |
| IndyCar fullscreen | 384 px | `modes/racing.py` | `draw_indycar_fullscreen()` |
| Race control (RC) | 192 px | `modes/racing.py` | `draw_indycar_racecontrol_card()` |
| Weather | 384 px fullscreen | `modes/weather.py` | `draw_weather_detailed()` |
| Music (Spotify) | 384 px fullscreen | `modes/music.py` | `draw_music_card()` |
| Stock ticker | 128 px | `modes/sports.py` | `draw_stock_card()` |
| Flight visitor | 384 px fullscreen | `modes/flight.py` | `draw_flight_visitor()` |
