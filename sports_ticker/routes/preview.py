"""Server-side LED strip renderer — serves game frames as a PNG strip."""

import io
import os
import sys
import threading

from flask import request, Response
from ..routes_runtime import app
from ..core import state, normalize_mode
from ..workers import fetcher

# ticker_controller lives at the repo root — add it to sys.path once
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_renderer = None
_renderer_lock = threading.Lock()

PANEL_W = 384
PANEL_H = 32
SEP_W   = 2
SEP_COL = (25, 25, 25, 255)


def _get_renderer():
    global _renderer
    if _renderer is not None:
        return _renderer
    with _renderer_lock:
        if _renderer is not None:
            return _renderer
        try:
            from ticker_controller.stadium import StadiumRenderer
            _renderer = StadiumRenderer()
            print("[preview] StadiumRenderer ready")
        except Exception as e:
            print(f"[preview] StadiumRenderer init failed: {e}")
            _renderer = False   # sentinel so we don't retry on every request
    return _renderer


@app.route('/api/preview/strip.png')
def preview_strip():
    from PIL import Image, ImageDraw

    mode_str = request.args.get('mode', state.get('mode', 'sports'))
    try:
        current_mode = normalize_mode(mode_str)
        games = fetcher.get_mode_snapshot(current_mode, 0)[:30]
    except Exception:
        games = []

    renderer = _get_renderer()

    def _empty_response():
        img = Image.new('RGB', (PANEL_W, PANEL_H), (0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        buf.seek(0)
        r = Response(buf.getvalue(), mimetype='image/png')
        r.headers['Cache-Control'] = 'no-store'
        r.headers['X-Strip-Width'] = str(PANEL_W)
        return r

    if not renderer or not games:
        return _empty_response()

    cards = []
    for g in games:
        try:
            result = renderer.render(g)
            card = result[0] if isinstance(result, tuple) else result
            if card is None:
                continue
            if card.mode != 'RGBA':
                card = card.convert('RGBA')
            cards.append(card)
        except Exception as e:
            print(f"[preview] render error for {g.get('id','?')}: {e}")

    if not cards:
        return _empty_response()

    total_w = sum(c.width for c in cards) + (len(cards) - 1) * SEP_W
    strip = Image.new('RGBA', (total_w, PANEL_H), (0, 0, 0, 255))
    sd = ImageDraw.Draw(strip)
    x = 0
    for i, card in enumerate(cards):
        if i > 0:
            sd.line([(x, 0), (x, PANEL_H - 1)], fill=SEP_COL)
            x += SEP_W
        strip.paste(card, (x, 0), card)
        x += card.width

    img = strip.convert('RGB')
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    r = Response(buf.getvalue(), mimetype='image/png')
    r.headers['Cache-Control'] = 'no-store'
    r.headers['X-Strip-Width'] = str(img.width)
    return r
