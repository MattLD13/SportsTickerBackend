import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from render_ticker_gif import render_gif_jobs

out = Path('previews') / 'f1_pin_long.gif'
print('Rendering long pinned F1 GIF ->', out)
res = render_gif_jobs('f1', view='pin', pin_idx=0, pin_out=str(out), fps=20, pin_dur=30, scale=6, do_prefetch_logos=True)
print('Done. pin_path=', res.pin_path)
