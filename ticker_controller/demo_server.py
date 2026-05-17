"""Browser demo server — runs actual TickerStreamer and streams MJPEG frames."""

import io
import threading
import time

import requests
import requests.packages.urllib3

requests.packages.urllib3.disable_warnings()

# ── patch device-id before importing TickerStreamer ──────────────────────────
_DEMO_ID = "browser-demo"

# Monkeypatch the local binding that controller.py captured at import time.
# Must happen before TickerStreamer is imported so __init__ sees the override.
import ticker_controller.controller as _ctrl_mod
_ctrl_mod.get_device_id = lambda: _DEMO_ID

from ticker_controller.controller import TickerStreamer  # noqa: E402
from flask import Flask, Response, jsonify, request       # noqa: E402

# ── shared frame state ────────────────────────────────────────────────────────
_frame_lock  = threading.Lock()
_frame_bytes: bytes = b""
_frame_event = threading.Event()   # set each time a new frame is ready


# ── YouTube Music metadata ────────────────────────────────────────────────────
import re, json as _json

def _extract_video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else ""

def _normalise_ytm_url(url: str) -> str:
    """Convert music.youtube.com → www.youtube.com so yt-dlp handles it cleanly."""
    return url.replace("music.youtube.com", "www.youtube.com")

def get_ytmusic_info(url: str) -> dict:
    """Return {title, artist, thumbnail, duration, video_id} for a YouTube Music URL."""
    url = _normalise_ytm_url(url.strip())
    vid = _extract_video_id(url)
    if not vid:
        raise ValueError("Could not find a YouTube video ID in that URL")

    # yt-dlp knows about YouTube Music and strips artist from title automatically
    try:
        import yt_dlp
        opts = {
            "quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # For music, prefer "artist" tag over channel name
        artist = (info.get("artist") or info.get("creator") or
                  info.get("channel") or info.get("uploader") or "Unknown Artist")
        title  = info.get("track") or info.get("title") or "Unknown Track"
        # Prefer jpg thumbnails — webp can fail on some Pillow builds.
        # YouTube Music often has square album-art thumbnails in the list.
        thumbs = info.get("thumbnails") or []
        jpg_thumbs = [t for t in thumbs if t.get("url") and ".jpg" in t["url"].lower()]
        best = (jpg_thumbs or thumbs)
        # sort by resolution (prefer larger), pick best jpg
        best.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
        thumbnail = best[-1]["url"] if best else f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
        # Fallback to guaranteed-available jpg if we only got webp
        if "webp" in thumbnail and not jpg_thumbs:
            thumbnail = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"

        return {
            "title":     title,
            "artist":    artist,
            "thumbnail": thumbnail,
            "duration":  float(info.get("duration") or 0),
            "video_id":  vid,
        }
    except Exception:
        pass

    # Fallback: oembed for title/author, hqdefault thumbnail
    title, artist, thumbnail = "Unknown Track", "Unknown Artist", ""
    try:
        oe = requests.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json",
            timeout=6, headers={"User-Agent": "Mozilla/5.0"}
        ).json()
        title    = oe.get("title", title)
        artist   = oe.get("author_name", artist)
        thumbnail = oe.get("thumbnail_url", "")
    except Exception:
        pass

    # Duration from JSON-LD in the page
    duration = 0.0
    try:
        html = requests.get(
            f"https://www.youtube.com/watch?v={vid}",
            timeout=8, headers={"User-Agent": "Mozilla/5.0"}
        ).text
        ld_m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        if ld_m:
            ld = _json.loads(ld_m.group(1))
            iso = ld.get("duration", "")
            m2 = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
            if m2:
                h, mn, sc = (int(x or 0) for x in m2.groups())
                duration = float(h * 3600 + mn * 60 + sc)
    except Exception:
        pass

    if not thumbnail:
        thumbnail = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"

    return {"title": title, "artist": artist, "thumbnail": thumbnail,
            "duration": duration, "video_id": vid}


# ── BrowserTicker ─────────────────────────────────────────────────────────────
class BrowserTicker(TickerStreamer):
    """TickerStreamer that captures frames as PNG and supports YouTube Music override.

    Uses properties to intercept every read of `static_items` and `mode` so the
    YouTube game is always present and mode always returns 'music' while a track
    is loaded — regardless of what poll_backend writes between its 0.5-s cycles.
    """

    def __init__(self):
        # Must be set before super().__init__() calls our setters
        self._yt_game: dict | None = None
        self._static_items: list = []
        self._mode: str = "sports"
        super().__init__()

    # ── static_items property ─────────────────────────────────────────────────
    # Every read transparently injects the YouTube game when one is loaded.
    # poll_backend can overwrite _static_items as often as it likes; we still win.
    @property
    def static_items(self):
        items = self._static_items
        g = self._yt_game
        if g is not None and not any(i.get("id") == "spotify_now" for i in items):
            return [g] + items
        return items

    @static_items.setter
    def static_items(self, value):
        self._static_items = list(value) if value is not None else []

    # ── mode property ─────────────────────────────────────────────────────────
    # While a YouTube track is loaded, always report 'music' so the render
    # loop keeps music_is_playing=True no matter what poll_backend stores.
    @property
    def mode(self):
        if self._yt_game is not None:
            return "music"
        return self._mode

    @mode.setter
    def mode(self, value):
        self._mode = value

    # ── frame capture ─────────────────────────────────────────────────────────
    def update_display(self, pil_image):
        global _frame_bytes
        buf = io.BytesIO()
        pil_image.convert("RGB").save(buf, format="PNG", optimize=False, compress_level=1)
        with _frame_lock:
            _frame_bytes = buf.getvalue()
        _frame_event.set()
        _frame_event.clear()

    # ── YouTube Music control ─────────────────────────────────────────────────
    def load_youtube(self, title: str, artist: str, thumbnail: str, duration: float):
        import io as _io
        from PIL import Image

        # Pre-download album art into the logo cache with the exact keys that
        # draw_music_card looks up: get_logo(url, (COVER_SIZE, COVER_SIZE))
        cs = self.COVER_SIZE  # 42
        try:
            r = requests.get(thumbnail, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            raw = Image.open(_io.BytesIO(r.content)).convert("RGBA")
            raw = raw.resize((cs, cs), Image.Resampling.LANCZOS)
            self.logo_cache[f"{thumbnail}_{(cs, cs)}"] = raw
            self.logo_cache[f"{thumbnail}_{cs}x{cs}"] = raw
        except Exception as e:
            print(f"[YT] Thumbnail pre-fetch failed: {e}")

        # Reset music-card animation state so it picks up new art immediately
        self.last_cover_url    = ""
        self.vinyl_cache       = None
        self.prev_vinyl_cache  = None
        self.text_scroll_pos   = 0.0
        self.vinyl_rotation    = 0.0
        self.fade_alpha        = 1.0
        self.transitioning_out = False
        self.dominant_color    = (29, 185, 84)

        game = {
            "id":        "spotify_now",
            "type":      "music",
            "sport":     "music",
            "home_abbr": artist,
            "away_abbr": title,
            "home_logo": thumbnail,
            "is_shown":  True,
            "situation": {
                "is_playing": True,
                "progress":   0.0,
                "duration":   max(duration, 1.0),
                "fetch_ts":   time.time(),
            },
        }
        self._yt_game = game   # property now guarantees it's always visible
        self.showing_static = False   # let render_loop start fresh
        self.set_mode("music")

    def clear_youtube(self):
        self._yt_game = None
        # _static_items may still contain old spotify_now from a real Spotify feed;
        # leave it alone — poll_backend will refresh on the next cycle.
        self.showing_static = False


# ── start ticker ──────────────────────────────────────────────────────────────
_ticker = BrowserTicker()
_render_thread = threading.Thread(target=_ticker.render_loop, daemon=True)
_render_thread.start()

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sports Ticker</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d0d;color:#eee;font-family:system-ui,sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:20px 12px}

h1{font-size:.72rem;font-weight:500;letter-spacing:.16em;color:#333;margin-bottom:16px;text-transform:uppercase}

/* ── ticker display ── */
#ticker-wrap{position:relative;display:inline-block;border-radius:6px;overflow:hidden;box-shadow:0 0 0 1px #1e1e1e,0 12px 48px #000e}
#ticker{display:block;image-rendering:pixelated;image-rendering:crisp-edges}
#led-overlay{position:absolute;inset:0;background:radial-gradient(circle at 50% 50%,transparent 38%,rgba(0,0,0,.82) 60%);pointer-events:none}

/* ── controls row ── */
#controls{margin-top:16px;width:100%;max-width:920px;display:flex;align-items:center;gap:10px}

/* scale */
#scale-wrap{display:flex;align-items:center;gap:6px;font-size:.7rem;color:#444;margin-left:auto;flex-shrink:0}
#scale{accent-color:#0a84ff;width:72px;cursor:pointer}

/* ── mode grid ── */
#mode-grid{margin-top:16px;width:100%;max-width:920px;display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
.mode-tile{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;padding:12px 6px;border:1px solid #1e1e1e;border-radius:12px;background:#141414;cursor:pointer;transition:all .18s;color:#555;font-size:.68rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;user-select:none}
.mode-tile svg{opacity:.5;transition:opacity .18s}
.mode-tile:hover{background:#1a1a1a;color:#aaa;border-color:#2a2a2a}
.mode-tile:hover svg{opacity:.7}
.mode-tile.active{background:#0a84ff18;border-color:#0a84ff55;color:#4da6ff;box-shadow:0 0 14px #0a84ff22}
.mode-tile.active svg{opacity:1}

/* ── sub-panel ── */
#sub-panel{margin-top:12px;width:100%;max-width:920px}
.sub-row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.sub-label{font-size:.62rem;color:#333;letter-spacing:.1em;text-transform:uppercase;margin-right:2px;flex-shrink:0}
.pill{padding:4px 14px;border:1px solid #2a2a2a;border-radius:20px;background:#141414;color:#555;cursor:pointer;font-size:.7rem;font-weight:600;letter-spacing:.04em;transition:all .15s}
.pill:hover{border-color:#3a3a3a;color:#aaa}
.pill.active{background:#0a84ff;border-color:#0a84ff;color:#fff;box-shadow:0 0 8px #0a84ff44}

/* config cards */
.cfg-section{display:flex;flex-direction:column;gap:8px;margin-top:10px}
.cfg-card{background:#111;border:1px solid #1e1e1e;border-radius:10px;padding:12px 14px;display:flex;align-items:center;gap:12px}
.cfg-card.col{flex-direction:column;align-items:stretch;gap:10px}
.cfg-icon{font-size:1.3rem;flex-shrink:0;width:28px;text-align:center}
.cfg-body{flex:1;min-width:0}
.cfg-title{font-size:.82rem;font-weight:700;color:#d0d0d0}
.cfg-sub{font-size:.65rem;color:#444;margin-top:2px}
.cfg-row{display:flex;align-items:center;justify-content:space-between;gap:10px}
.cfg-lbl{font-size:.72rem;color:#555;flex-shrink:0}
.cfg-input{background:transparent;border:none;border-bottom:1px solid #2a2a2a;color:#d0d0d0;font-size:.82rem;font-family:monospace;text-align:right;outline:none;flex:1;padding:3px 0;min-width:0;transition:border-color .15s}
.cfg-input:focus{border-color:#0a84ff}
.cfg-input::placeholder{color:#333}
.cfg-resolved{font-size:.65rem;color:#3b82f6;font-family:monospace;margin-top:2px;min-height:14px}
.cfg-tracking{font-size:.72rem;color:#4ade80;display:flex;align-items:center;gap:6px}
.cfg-clear{background:none;border:none;color:#ef4444;font-size:.7rem;cursor:pointer;padding:2px 6px;border-radius:4px;transition:background .15s}
.cfg-clear:hover{background:#ef444422}
.sector-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px}
.sector-btn{padding:9px 10px;border:1px solid #2a2a2a;border-radius:8px;background:#141414;color:#555;cursor:pointer;font-size:.72rem;font-weight:600;text-align:center;transition:all .15s}
.sector-btn:hover{border-color:#3a3a3a;color:#aaa}
.sector-btn.active{background:#0a84ff18;border-color:#0a84ff55;color:#4da6ff}

/* ── game feed / pin panel ── */
#feed-section{margin-top:14px;width:100%;max-width:920px}
#feed-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
#feed-label{font-size:.62rem;color:#333;letter-spacing:.1em;text-transform:uppercase}
#feed-refresh{background:none;border:none;color:#333;cursor:pointer;font-size:.62rem;padding:2px 6px;border-radius:4px;transition:color .15s}
#feed-refresh:hover{color:#888}

#game-list{display:flex;flex-direction:column;gap:5px;max-height:340px;overflow-y:auto;padding-right:2px}
#game-list::-webkit-scrollbar{width:3px}
#game-list::-webkit-scrollbar-track{background:transparent}
#game-list::-webkit-scrollbar-thumb{background:#222;border-radius:2px}

/* game row */
.game-row{display:flex;align-items:center;padding:9px 12px;border-radius:10px;border:1px solid #1a1a1a;background:#111;cursor:pointer;transition:all .18s;gap:0;position:relative;overflow:hidden}
.game-row::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:transparent;transition:background .18s}
.game-row:hover{background:#161616;border-color:#252525}
.game-row:hover::before{background:#333}
.game-row.pinned{background:#0a84ff0e;border-color:#0a84ff44}
.game-row.pinned::before{background:#0a84ff}

/* team side */
.team-side{display:flex;align-items:center;gap:8px;flex:1;min-width:0}
.team-side.home{flex-direction:row-reverse}
.t-logo{width:30px;height:30px;object-fit:contain;border-radius:4px;flex-shrink:0;background:#181818}
.t-logo.err{opacity:.15;filter:grayscale(1)}
.t-info{display:flex;flex-direction:column;gap:1px;min-width:0}
.team-side.home .t-info{align-items:flex-end}
.t-abbr{font-size:.85rem;font-weight:800;letter-spacing:.04em;color:#d0d0d0}
.t-name{font-size:.6rem;color:#444;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:88px}

/* center */
.g-center{display:flex;flex-direction:column;align-items:center;gap:3px;padding:0 14px;flex-shrink:0;min-width:88px}
.score-row{display:flex;align-items:baseline;gap:7px}
.score-val{font-size:1.15rem;font-weight:800;color:#fff;font-variant-numeric:tabular-nums;min-width:18px;text-align:center;line-height:1}
.score-dash{color:#2a2a2a;font-size:.8rem}
.g-status{font-size:.58rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:2px 7px;border-radius:3px;white-space:nowrap}
.s-live{background:#0d2e0d;color:#4ade80}
.s-final{background:#1a1a1a;color:#444}
.s-pre{background:#0d1e2e;color:#3b82f6}
.g-sport{font-size:.56rem;color:#2a2a2a;letter-spacing:.08em;text-transform:uppercase}

#feed-empty{padding:24px 0;text-align:center;color:#2a2a2a;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase}
</style>
</head>
<body>
<h1>Sports Ticker &mdash; Live Preview</h1>

<div id="ticker-wrap">
  <img id="ticker" src="/stream" alt="ticker">
  <div id="led-overlay"></div>
</div>

<div id="controls">
  <div id="scale-wrap">
    <span>Scale</span>
    <input type="range" id="scale" min="1" max="8" step="0.5" value="4">
    <span id="scale-val">4×</span>
  </div>
</div>

<!-- 6-tile mode grid matching iOS -->
<div id="mode-grid">
  <div class="mode-tile active" data-cat="sports">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07"/></svg>
    Sports
  </div>
  <div class="mode-tile" data-cat="stocks">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
    Stocks
  </div>
  <div class="mode-tile" data-cat="music">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
    Music
  </div>
  <div class="mode-tile" data-cat="flights">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.8 19.2L16 11l3.5-3.5C21 6 21 4 19 2c-2-2-4-2-5.5-.5L10 5 1.8 6.2l-.3.4 4.9 2.9L3.2 12l2 2 3.9-2.2 2.9 4.9.4-.1z"/></svg>
    Flights
  </div>
  <div class="mode-tile" data-cat="weather">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>
    Weather
  </div>
  <div class="mode-tile" data-cat="clock">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
    Clock
  </div>
</div>

<!-- context-sensitive sub-pills -->
<div id="sub-panel"></div>

<!-- game feed (sports mode only) -->
<div id="feed-section" style="display:none">
  <div id="feed-header">
    <span id="feed-label" style="cursor:pointer;user-select:none" onclick="toggleFeed()">Active Feed &mdash; tap to pin <span id="feed-chevron">▾</span></span>
    <button id="feed-refresh">↻ Refresh</button>
  </div>
  <div id="game-list"><div id="feed-empty">Loading…</div></div>
</div>

<script>
const W=384, H=32;
let scale=4, activeCategory='sports', sportsFilter='sports', flightSub='airport';
let pinnedId='', allGames=[], leagueOptions=[], feedTimer=null;
// persisted config state
let cfg={ weather_location:'', airport_code_iata:'', airport_code_icao:'',
          airport_name:'', track_flight_id:'', track_guest_name:'', active_sports:{} };

// ── scale ──────────────────────────────────────────────────────────────────
function autoScale(){
  const pad=24; // horizontal padding (px per side)
  const maxW=window.innerWidth-pad*2;
  const s=Math.max(1,Math.min(8,Math.floor(maxW/W*2)/2)); // snap to 0.5 steps
  const slider=document.getElementById('scale');
  slider.value=s;
  applyScale(s);
}
function applyScale(s){
  scale=s;
  document.getElementById('ticker').style.cssText=`width:${W*s}px;height:${H*s}px`;
  document.getElementById('led-overlay').style.backgroundSize=`${s}px ${s}px`;
  document.getElementById('scale-val').textContent=s+'×';
}
autoScale();
window.addEventListener('resize',autoScale);
document.getElementById('scale').addEventListener('input',e=>applyScale(parseFloat(e.target.value)));

// ── helpers ────────────────────────────────────────────────────────────────
function el(tag,cls=''){const e=document.createElement(tag);if(cls)e.className=cls;return e;}
function div(cls=''){return el('div',cls);}
function span(cls,txt){const s=el('span',cls);s.textContent=txt;return s;}
function logoSrc(url){return url?'/proxy/logo?url='+encodeURIComponent(url):'';}
function postConfig(extra){
  return fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({...cfg,...extra})});
}
function applyMode(mode){
  return fetch('/api/set_mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
}

// ── league options ─────────────────────────────────────────────────────────
async function loadLeagues(){
  try{ const r=await fetch('/api/leagues'); leagueOptions=await r.json(); }catch(e){}
}

// ── mode tiles ─────────────────────────────────────────────────────────────
async function setCategory(cat){
  activeCategory=cat;
  document.querySelectorAll('.mode-tile').forEach(t=>t.classList.toggle('active',t.dataset.cat===cat));
  document.getElementById('feed-section').style.display=(cat==='sports')?'block':'none';
  if(cat==='sports'){ applyMode(sportsFilter); loadGames(); startFeedRefresh(); }
  else{
    stopFeedRefresh();
    if(cat==='flights') applyMode(flightSub==='track'?'flight_tracker':'flights');
    else applyMode(cat);
  }
  renderSubPanel();
}
document.querySelectorAll('.mode-tile').forEach(t=>t.addEventListener('click',()=>setCategory(t.dataset.cat)));

// ── sub-panel ──────────────────────────────────────────────────────────────
function renderSubPanel(){
  const p=document.getElementById('sub-panel'); p.innerHTML='';

  if(activeCategory==='sports'){
    const row=div('sub-row');
    row.appendChild(span('sub-label','Filter'));
    [['Show All','sports'],['Live Only','live'],['My Teams','my_teams']].forEach(([lbl,val])=>{
      const b=el('button','pill'+(sportsFilter===val?' active':''));
      b.textContent=lbl;
      b.addEventListener('click',()=>{ sportsFilter=val; if(pinnedId) togglePin(''); applyMode(val); renderSubPanel(); });
      row.appendChild(b);
    });
    p.appendChild(row);

  } else if(activeCategory==='stocks'){
    const sec=div('cfg-section');
    const stocks=leagueOptions.filter(o=>o.type==='stock');
    if(stocks.length){
      const hdr=span('sub-label','Market Sector'); hdr.style.display='block'; hdr.style.marginBottom='6px';
      sec.appendChild(hdr);
      const grid=div('sector-grid');
      stocks.forEach(opt=>{
        const isOn=cfg.active_sports[opt.id]===true;
        const b=div('sector-btn'+(isOn?' active':''));
        b.textContent=opt.label; b.style.cursor='pointer';
        b.addEventListener('click',()=>{
          // single-select: clear all others
          stocks.forEach(o=>{ cfg.active_sports[o.id]=false; });
          cfg.active_sports[opt.id]=true;
          postConfig({mode:'stocks',active_sports:cfg.active_sports});
          renderSubPanel();
        });
        grid.appendChild(b);
      });
      sec.appendChild(grid);
    } else {
      const info=div('cfg-card');
      info.innerHTML='<span class="cfg-icon">📈</span><div class="cfg-body"><div class="cfg-title">Stocks</div><div class="cfg-sub">Showing US market data</div></div>';
      sec.appendChild(info);
    }
    p.appendChild(sec);

  } else if(activeCategory==='weather'){
    const sec=div('cfg-section');
    // info card
    const info=div('cfg-card');
    info.innerHTML='<span class="cfg-icon">🌤</span><div class="cfg-body"><div class="cfg-title">Weather Display</div><div class="cfg-sub">Current conditions + 5-day forecast</div></div>';
    sec.appendChild(info);
    // location input
    const locCard=div('cfg-card col');
    const locRow=div('cfg-row');
    const locLbl=span('cfg-lbl','Location');
    const locInput=el('input','cfg-input'); locInput.type='text';
    locInput.placeholder='City, zip, or address'; locInput.value=cfg.weather_location;
    function submitWeather(){
      cfg.weather_location=locInput.value.trim();
      if(cfg.weather_location) postConfig({mode:'weather',weather_location:cfg.weather_location});
    }
    locInput.addEventListener('keydown',e=>{ if(e.key==='Enter'){ locInput.blur(); submitWeather(); }});
    locInput.addEventListener('blur',submitWeather);
    locRow.appendChild(locLbl); locRow.appendChild(locInput);
    locCard.appendChild(locRow);
    sec.appendChild(locCard);
    p.appendChild(sec);

  } else if(activeCategory==='flights'){
    const sec=div('cfg-section');
    // sub-mode pills
    const row=div('sub-row'); row.style.marginBottom='8px';
    row.appendChild(span('sub-label','Mode'));
    [['Airport','airport'],['Track Flight','track']].forEach(([lbl,val])=>{
      const b=el('button','pill'+(flightSub===val?' active':''));
      b.textContent=lbl;
      b.addEventListener('click',()=>{ flightSub=val; applyMode(val==='track'?'flight_tracker':'flights'); renderSubPanel(); });
      row.appendChild(b);
    });
    sec.appendChild(row);

    if(flightSub==='airport'){
      // info card
      const info=div('cfg-card');
      info.innerHTML='<span class="cfg-icon">🏢</span><div class="cfg-body"><div class="cfg-title">Airport Activity</div>'
        +(cfg.airport_name?`<div class="cfg-sub">${cfg.airport_name}</div>`:'<div class="cfg-sub">Arrivals &amp; departures board</div>')+'</div>';
      sec.appendChild(info);
      // airport code input
      const codeCard=div('cfg-card col');
      const codeRow=div('cfg-row');
      const codeLbl=span('cfg-lbl','Airport Code');
      const codeInput=el('input','cfg-input'); codeInput.type='text';
      codeInput.placeholder='IATA or ICAO (e.g. EWR, KJFK)';
      codeInput.value=cfg.airport_code_iata; codeInput.style.textTransform='uppercase';
      const resolved=div('cfg-resolved');
      if(cfg.airport_code_iata) resolved.textContent=`${cfg.airport_code_iata}  ·  ${cfg.airport_code_icao||''}`;
      function submitAirport(){
        const code=codeInput.value.trim().toUpperCase();
        if(code.length>=3){ cfg.airport_code_iata=code;
          postConfig({mode:'flights',airport_code_iata:code}).then(r=>r.json()).then(d=>{
            if(d.airport_code_iata){ cfg.airport_code_iata=d.airport_code_iata; codeInput.value=d.airport_code_iata; }
            if(d.airport_code_icao) cfg.airport_code_icao=d.airport_code_icao;
            if(d.airport_name){ cfg.airport_name=d.airport_name;
              resolved.textContent=`${cfg.airport_code_iata}  ·  ${cfg.airport_code_icao||''}  —  ${cfg.airport_name}`; }
          });
        }
      }
      codeInput.addEventListener('keydown',e=>{ if(e.key==='Enter'){ codeInput.blur(); submitAirport(); }});
      codeInput.addEventListener('blur',submitAirport);
      codeRow.appendChild(codeLbl); codeRow.appendChild(codeInput);
      codeCard.appendChild(codeRow); codeCard.appendChild(resolved);
      sec.appendChild(codeCard);

    } else {
      // track flight
      const info=div('cfg-card');
      info.innerHTML='<span class="cfg-icon">✈️</span><div class="cfg-body"><div class="cfg-title">Track a Flight</div><div class="cfg-sub">Enter a flight number to track in real time</div></div>';
      sec.appendChild(info);

      // flight number
      const fnCard=div('cfg-card col');
      const fnRow=div('cfg-row');
      const fnLbl=span('cfg-lbl','Flight #');
      const fnInput=el('input','cfg-input'); fnInput.type='text';
      fnInput.placeholder='e.g. UA123, DAL456'; fnInput.value=cfg.track_flight_id;
      fnInput.style.textTransform='uppercase';
      // guest name
      const gnRow=div('cfg-row');
      const gnLbl=span('cfg-lbl','Guest Name');
      const gnInput=el('input','cfg-input'); gnInput.type='text';
      gnInput.placeholder='Optional (e.g. Mom)'; gnInput.value=cfg.track_guest_name;
      function submitFlight(){
        cfg.track_flight_id=fnInput.value.trim().toUpperCase();
        cfg.track_guest_name=gnInput.value.trim();
        postConfig({mode:'flight_tracker',track_flight_id:cfg.track_flight_id,track_guest_name:cfg.track_guest_name});
        renderSubPanel();
      }
      fnInput.addEventListener('keydown',e=>{ if(e.key==='Enter'){ fnInput.blur(); submitFlight(); }});
      fnInput.addEventListener('blur',submitFlight);
      gnInput.addEventListener('keydown',e=>{ if(e.key==='Enter'){ gnInput.blur(); submitFlight(); }});
      gnInput.addEventListener('blur',submitFlight);
      fnRow.appendChild(fnLbl); fnRow.appendChild(fnInput);
      gnRow.appendChild(gnLbl); gnRow.appendChild(gnInput);
      fnCard.appendChild(fnRow); fnCard.appendChild(gnRow);
      sec.appendChild(fnCard);

      // tracking status / clear
      if(cfg.track_flight_id){
        const trackCard=div('cfg-card');
        const trackInfo=div('cfg-tracking');
        trackInfo.innerHTML=`<span>✅</span><span>Tracking: <strong>${cfg.track_flight_id}</strong>${cfg.track_guest_name?' — '+cfg.track_guest_name:''}</span>`;
        const clearBtn=el('button','cfg-clear'); clearBtn.textContent='Clear';
        clearBtn.addEventListener('click',()=>{
          cfg.track_flight_id=''; cfg.track_guest_name='';
          postConfig({mode:'flight_tracker',track_flight_id:'',track_guest_name:''});
          renderSubPanel();
        });
        trackCard.appendChild(trackInfo); trackCard.appendChild(clearBtn);
        sec.appendChild(trackCard);
      } else {
        const empty=div('cfg-card');
        empty.innerHTML='<span class="cfg-icon" style="opacity:.3">🛫</span><div class="cfg-body"><div class="cfg-sub" style="color:#333">Enter a flight number above to start tracking</div></div>';
        sec.appendChild(empty);
      }
    }
    p.appendChild(sec);

  } else if(activeCategory==='music'){
    const sec=div('cfg-section');
    // Spotify info
    const spotCard=div('cfg-card');
    spotCard.innerHTML='<span class="cfg-icon">🎵</span><div class="cfg-body"><div class="cfg-title">Spotify Integration</div><div class="cfg-sub">Ticker will display currently playing track when linked</div></div>';
    sec.appendChild(spotCard);
    // divider
    const hr=document.createElement('hr'); hr.style.cssText='border:none;border-top:1px solid #1e1e1e;margin:4px 0';
    sec.appendChild(hr);
    // YouTube section header
    const ytHdr=span('sub-label','YouTube Music'); ytHdr.style.cssText='display:block;margin-bottom:6px';
    sec.appendChild(ytHdr);
    // URL input card
    const ytCard=div('cfg-card col');
    const urlRow=div('cfg-row');
    const urlLbl=span('cfg-lbl','URL');
    const urlInput=el('input','cfg-input'); urlInput.type='text';
    urlInput.placeholder='https://music.youtube.com/watch?v=...';
    urlInput.style.fontFamily='monospace';
    const loadBtn=el('button','pill active'); loadBtn.textContent='Load';
    loadBtn.style.cssText='flex-shrink:0;border-radius:6px;padding:4px 12px;margin-left:8px;font-size:.7rem';
    urlRow.appendChild(urlLbl); urlRow.appendChild(urlInput); urlRow.appendChild(loadBtn);
    ytCard.appendChild(urlRow);
    // status line inside the card
    const ytStatus=div('cfg-resolved'); ytStatus.style.marginTop='4px';
    ytCard.appendChild(ytStatus);
    sec.appendChild(ytCard);
    // now-playing preview card (filled after load)
    const ytPreview=div(''); ytPreview.id='yt-preview';
    sec.appendChild(ytPreview);

    // load current state from server
    fetch('/api/youtube/status').then(r=>r.json()).then(d=>{
      if(d.active) renderYtPreview(d, ytPreview, urlInput, ytStatus);
    });

    function renderYtPreview(d, previewEl, inputEl, statusEl){
      previewEl.innerHTML='';
      if(!d||!d.active) return;
      const card=div('cfg-card'); card.style.cssText='gap:10px;margin-top:4px';
      // thumbnail
      const thumb=el('img','t-logo');
      thumb.src=d.thumbnail; thumb.style.cssText='width:48px;height:36px;border-radius:4px;object-fit:cover;flex-shrink:0';
      // info
      const info=div('cfg-body');
      const ttl=div('cfg-title'); ttl.textContent=d.title||'';
      const art=div('cfg-sub'); art.textContent=d.artist||'';
      const dur=div('cfg-sub'); dur.style.color='#555';
      const fmtT=s=>{const m=Math.floor(s/60),sec=Math.floor(s%60);return`${m}:${sec.toString().padStart(2,'0')}`;};
      dur.textContent=d.duration?fmtT(d.duration):'';
      info.appendChild(ttl); info.appendChild(art); info.appendChild(dur);
      // clear btn
      const clr=el('button','cfg-clear'); clr.textContent='Clear'; clr.style.marginLeft='auto';
      clr.addEventListener('click',()=>{
        fetch('/api/youtube',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clear:true})});
        previewEl.innerHTML=''; inputEl.value=''; statusEl.textContent='';
      });
      card.appendChild(thumb); card.appendChild(info); card.appendChild(clr);
      previewEl.appendChild(card);
    }

    function doLoad(){
      const url=urlInput.value.trim();
      if(!url) return;
      ytStatus.textContent='Loading…'; ytStatus.style.color='#555';
      loadBtn.disabled=true; loadBtn.textContent='…';
      fetch('/api/youtube',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})})
        .then(r=>r.json()).then(d=>{
          loadBtn.disabled=false; loadBtn.textContent='Load';
          if(d.error){ ytStatus.textContent=d.error; ytStatus.style.color='#ef4444'; return; }
          ytStatus.textContent=''; renderYtPreview({...d,active:true},ytPreview,urlInput,ytStatus);
          // switch UI to music mode
          document.querySelectorAll('.mode-tile').forEach(t=>t.classList.toggle('active',t.dataset.cat==='music'));
        }).catch(()=>{ loadBtn.disabled=false; loadBtn.textContent='Load'; ytStatus.textContent='Request failed'; ytStatus.style.color='#ef4444'; });
    }
    loadBtn.addEventListener('click',doLoad);
    urlInput.addEventListener('keydown',e=>{ if(e.key==='Enter'){ urlInput.blur(); doLoad(); }});
    p.appendChild(sec);

  } else if(activeCategory==='clock'){
    const sec=div('cfg-section');
    const card=div('cfg-card');
    card.innerHTML='<span class="cfg-icon">🕐</span><div class="cfg-body"><div class="cfg-title">Clock Mode</div><div class="cfg-sub">Displaying large time and date</div></div>';
    sec.appendChild(card); p.appendChild(sec);
  }
}

// ── status helpers ─────────────────────────────────────────────────────────
function statusInfo(g){
  const s=(g.status||'').toLowerCase();
  if(!s||s.match(/schedul|tbd|^pm|^\d+:\d+/)) return {cls:'s-pre',text:g.status||'Scheduled'};
  if(s.match(/final|full.?time|ft$|end/))      return {cls:'s-final',text:'Final'};
  return {cls:'s-live',text:g.status||'Live'};
}

function buildTeamSide(abbr,name,logo,isHome){
  const side=div('team-side'+(isHome?' home':''));
  const img=el('img','t-logo'); img.alt=abbr;
  if(logo){img.src=logo; img.onerror=()=>img.classList.add('err');} else img.classList.add('err');
  const info=div('t-info');
  const a=div('t-abbr'); a.textContent=abbr||'—';
  const n=div('t-name'); n.textContent=name||'';
  info.appendChild(a); info.appendChild(n);
  side.appendChild(img); side.appendChild(info);
  return side;
}

// ── pin logic ──────────────────────────────────────────────────────────────
function togglePin(id){
  const newId=(id===pinnedId)?'':id;
  pinnedId=newId;
  document.querySelectorAll('.game-row').forEach(r=>r.classList.toggle('pinned',r.dataset.id===newId));
  fetch('/api/pin_games',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({game_ids:newId?[newId]:[]})});
  applyMode(newId?'sports_full':sportsFilter);
}

// ── game feed ──────────────────────────────────────────────────────────────
let feedVisible=true;
function toggleFeed(){
  feedVisible=!feedVisible;
  document.getElementById('game-list').style.display=feedVisible?'':'none';
  document.getElementById('feed-chevron').textContent=feedVisible?'▾':'▸';
}
function startFeedRefresh(){stopFeedRefresh(); feedTimer=setInterval(loadGames,15000);}
function stopFeedRefresh(){if(feedTimer){clearInterval(feedTimer);feedTimer=null;}}
document.getElementById('feed-refresh').addEventListener('click',loadGames);

async function loadGames(){
  try{ const r=await fetch('/api/games'); const d=await r.json(); allGames=d.games||[]; renderFeed(); }catch(e){}
}

function renderFeed(){
  const list=document.getElementById('game-list'); list.innerHTML='';
  if(!allGames.length){
    const e=div(''); e.id='feed-empty'; e.textContent='No games in current feed';
    list.appendChild(e); return;
  }
  allGames.forEach(g=>{
    const id=g.id||g.game_id||'';
    const si=statusInfo(g); const sport=(g.sport||g.type||'').toUpperCase();
    const row=div('game-row'+(pinnedId===id?' pinned':'')); row.dataset.id=id;
    const center=div('g-center');
    const awayScore=g.away_score!=null?String(g.away_score):'';
    const homeScore=g.home_score!=null?String(g.home_score):'';
    if(awayScore!==''||homeScore!==''){
      const sr=div('score-row');
      const aS=div('score-val'); aS.textContent=awayScore||'0';
      const dash=div('score-dash'); dash.textContent='–';
      const hS=div('score-val'); hS.textContent=homeScore||'0';
      sr.appendChild(aS); sr.appendChild(dash); sr.appendChild(hS); center.appendChild(sr);
    }
    const st=div('g-status '+si.cls); st.textContent=si.text; center.appendChild(st);
    const sp=div('g-sport'); sp.textContent=sport; center.appendChild(sp);
    row.appendChild(buildTeamSide(g.away_abbr||'?',g.away_name||'',logoSrc(g.away_logo),false));
    row.appendChild(center);
    row.appendChild(buildTeamSide(g.home_abbr||'?',g.home_name||'',logoSrc(g.home_logo),true));
    row.addEventListener('click',()=>togglePin(id));
    list.appendChild(row);
  });
}

// ── init ──────────────────────────────────────────────────────────────────
loadLeagues().then(()=>{ setCategory('sports'); });
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return Response(_HTML, mimetype="text/html")


@app.route("/stream")
def stream():
    def generate():
        local_last: bytes = b""
        while True:
            with _frame_lock:
                frame = _frame_bytes
            if frame and frame is not local_last:
                local_last = frame
                yield (
                    b"--f\r\nContent-Type: image/png\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
            else:
                time.sleep(0.015)
    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=f",
        headers={"Cache-Control": "no-cache"},
    )


@app.route("/api/set_mode", methods=["POST"])
def set_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "sports")
    _ticker.set_mode(mode)
    return jsonify({"status": "ok", "mode": mode})


@app.route("/api/config", methods=["POST"])
def api_config():
    from ticker_controller.config import BACKEND_URL
    data = request.get_json(silent=True) or {}
    data.setdefault("ticker_id", _DEMO_ID)
    mode = data.get("mode")
    if mode:
        _ticker.set_mode(mode)
    # flight config goes through the ticker's own push so it can set active_sports correctly
    if "track_flight_id" in data or "airport_code_iata" in data:
        _ticker.push_flight_config(data)
    try:
        r = requests.post(
            f"{BACKEND_URL}/api/config",
            json=data,
            headers={"X-Client-ID": _DEMO_ID},
            timeout=5,
            verify=False,
        )
        return Response(r.content, status=r.status_code, mimetype="application/json")
    except Exception as e:
        return jsonify({"status": "ok"})


@app.route("/api/youtube", methods=["POST"])
def api_youtube():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if data.get("clear"):
        _ticker.clear_youtube()
        return jsonify({"status": "cleared"})
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    try:
        info = get_ytmusic_info(url)
        _ticker.load_youtube(
            title=info["title"],
            artist=info["artist"],
            thumbnail=info["thumbnail"],
            duration=info["duration"],
        )
        return jsonify({**info, "status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 422


@app.route("/api/youtube/status")
def api_youtube_status():
    game = _ticker._yt_game
    if not game:
        return jsonify({"active": False})
    sit = game.get("situation", {})
    elapsed = time.time() - float(sit.get("fetch_ts", time.time()))
    progress = min(float(sit.get("progress", 0)) + elapsed, float(sit.get("duration", 1)))
    return jsonify({
        "active":    True,
        "title":     game.get("away_abbr", ""),
        "artist":    game.get("home_abbr", ""),
        "thumbnail": game.get("home_logo", ""),
        "duration":  sit.get("duration", 0),
        "progress":  progress,
    })


@app.route("/api/leagues")
def api_leagues():
    from ticker_controller.config import BACKEND_URL
    try:
        r = requests.get(f"{BACKEND_URL}/leagues", timeout=5, verify=False)
        return Response(r.content, status=r.status_code, mimetype="application/json")
    except Exception:
        return jsonify([])


@app.route("/api/pin_games", methods=["POST"])
def pin_games():
    data = request.get_json(silent=True) or {}
    game_ids = data.get("game_ids", [])
    payload = {"ticker_id": _DEMO_ID, "game_ids": game_ids}
    try:
        from ticker_controller.config import BACKEND_URL
        requests.post(
            f"{BACKEND_URL}/api/pin_games",
            json=payload,
            headers={"X-Client-ID": _DEMO_ID},
            timeout=5,
            verify=False,
        )
    except Exception:
        pass
    return jsonify({"status": "ok", "game_ids": game_ids})


@app.route("/proxy/logo")
def proxy_logo():
    url = request.args.get("url", "")
    if not url:
        return "", 404
    try:
        r = requests.get(url, timeout=5, verify=False, headers={"User-Agent": "SportsTicker/1.0"})
        ct = r.headers.get("Content-Type", "image/png")
        return Response(r.content, status=r.status_code, mimetype=ct,
                        headers={"Cache-Control": "public, max-age=3600",
                                 "Access-Control-Allow-Origin": "*"})
    except Exception:
        return "", 404


@app.route("/api/games")
def api_games():
    games = list(_ticker.games) + list(_ticker.static_items)
    # filter to only pinnable game types (skip clock, weather, music, flight hud)
    skip_types = {"weather", "clock", "music", "flight_airport_hud"}
    pinnable = [
        g for g in games
        if g.get("type") not in skip_types and g.get("sport") not in skip_types
    ]
    return jsonify({"games": pinnable})


if __name__ == "__main__":
    print(f"Ticker Demo  →  http://localhost:5001   (device={_DEMO_ID})")
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)
