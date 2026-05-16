(function () {
'use strict';

const CFG = window._CFG || {};
const BUNDLE_URL = CFG.browserBundleUrl || '/api/browser/ticker_controller_bundle';
const PYODIDE_BASE_URL = 'https://cdn.jsdelivr.net/pyodide/v0.27.1/full/';

const IMAGE_KEYS = new Set([
  'home_logo', 'away_logo', 'logo', 'cover_url', 'album_art', 'image_url', 'image',
  'thumbnail', 'art', 'art_url', 'next_logos', 'photo_url', 'banner_url', 'icon_url',
]);

let pyodidePromise = null;
let controllerPromise = null;
const assetCache = new Map();

function looksLikeHttpUrl(value) {
  return typeof value === 'string' && /^https?:\/\//i.test(value);
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const slice = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, slice);
  }
  return btoa(binary);
}

async function blobToDataUrl(blob) {
  const buffer = await blob.arrayBuffer();
  const mime = blob.type || 'application/octet-stream';
  return 'data:' + mime + ';base64,' + arrayBufferToBase64(buffer);
}

async function inlineImageUrl(url) {
  if (!looksLikeHttpUrl(url)) return url;
  if (assetCache.has(url)) return assetCache.get(url);
  try {
    const proxyUrl = '/api/browser/image_proxy?url=' + encodeURIComponent(url);
    const resp = await fetch(proxyUrl, { cache: 'force-cache' });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const dataUrl = await blobToDataUrl(await resp.blob());
    assetCache.set(url, dataUrl);
    return dataUrl;
  } catch (err) {
    assetCache.set(url, url);
    return url;
  }
}

async function inlineGameAssets(value) {
  if (Array.isArray(value)) {
    const out = [];
    for (const item of value) out.push(await inlineGameAssets(item));
    return out;
  }
  if (!value || typeof value !== 'object') return value;

  const out = {};
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry === 'string' && (IMAGE_KEYS.has(key) || /logo|art|image|cover/i.test(key))) {
      out[key] = await inlineImageUrl(entry);
    } else if (Array.isArray(entry) && /logo/i.test(key)) {
      out[key] = await Promise.all(entry.map(item => inlineGameAssets(item)));
    } else if (entry && typeof entry === 'object') {
      out[key] = await inlineGameAssets(entry);
    } else {
      out[key] = entry;
    }
  }
  return out;
}

async function ensurePyodide() {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      if (!window.loadPyodide) {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = PYODIDE_BASE_URL + 'pyodide.js';
          script.async = true;
          script.onload = resolve;
          script.onerror = () => reject(new Error('Failed to load pyodide.js'));
          document.head.appendChild(script);
        });
      }
      const pyodide = await window.loadPyodide({ indexURL: PYODIDE_BASE_URL });
      await pyodide.loadPackage(['pillow']);
      return pyodide;
    })();
  }
  return pyodidePromise;
}

function requestsStubSource() {
  return `
from types import SimpleNamespace
from urllib.parse import unquote_to_bytes
import base64


class _Warns:
    @staticmethod
    def disable_warnings(*args, **kwargs):
        return None


packages = SimpleNamespace(urllib3=_Warns())


class _Response:
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        raise NotImplementedError('JSON is not implemented in the browser preview stub')


class adapters:
    class HTTPAdapter:
        def __init__(self, *args, **kwargs):
            pass
        def close(self):
            return None
        def init_poolmanager(self, *args, **kwargs):
            return None


class Session:
    def get(self, url, *args, **kwargs):
        return get(url, *args, **kwargs)

    def post(self, url, *args, **kwargs):
        return post(url, *args, **kwargs)

    def close(self):
        return None


def _decode_data_url(url):
    meta, data = url.split(',', 1)
    if ';base64' in meta:
        return base64.b64decode(data)
    return unquote_to_bytes(data)


def get(url, *args, **kwargs):
    if isinstance(url, str) and url.startswith('data:'):
        return _Response(_decode_data_url(url), 200, {'Content-Type': url.split(';', 1)[0][5:]})
    raise RuntimeError(f'Browser preview requests only supports data: URLs, got {url!r}')


def post(*args, **kwargs):
    return _Response(b'', 200, {})
`;
}

function browserEntrySource() {
  return `
import base64
import io
import sys
import types
import time

from PIL import Image, ImageDraw, ImageFont


def _install_stubs():
  if 'flask' not in sys.modules:
    flask_mod = types.ModuleType('flask')

    class _Request:
      args = {}
      headers = {}
      json = None

    class Flask:
      def __init__(self, *args, **kwargs):
        self.config = {}
        self.secret_key = ''

      def route(self, *args, **kwargs):
        def decorator(func):
          return func
        return decorator

      def register_blueprint(self, *args, **kwargs):
        return None

    def render_template_string(*args, **kwargs):
      return ''

    def jsonify(*args, **kwargs):
      if args:
        return args[0]
      return kwargs

    def make_response(value=None):
      return value

    flask_mod.Flask = Flask
    flask_mod.request = _Request()
    flask_mod.render_template_string = render_template_string
    flask_mod.jsonify = jsonify
    flask_mod.make_response = make_response
    sys.modules['flask'] = flask_mod

  if 'requests' not in sys.modules:
    requests_mod = types.ModuleType('requests')
    adapters_mod = types.ModuleType('requests.adapters')

    class _Warns:
      @staticmethod
      def disable_warnings(*args, **kwargs):
        return None

    class _Response:
      def __init__(self, content=b'', status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

      def json(self):
        raise NotImplementedError('JSON is not implemented in the browser preview stub')

    class HTTPAdapter:
      def __init__(self, *args, **kwargs):
        pass

      def close(self):
        return None

      def init_poolmanager(self, *args, **kwargs):
        return None

    class Session:
      def get(self, url, *args, **kwargs):
        return get(url, *args, **kwargs)

      def post(self, url, *args, **kwargs):
        return post(url, *args, **kwargs)

      def mount(self, *args, **kwargs):
        return None

      def close(self):
        return None

    def get(url, *args, **kwargs):
      if isinstance(url, str) and url.startswith('data:'):
        header, payload = url.split(',', 1)
        if ';base64' in header:
          return _Response(base64.b64decode(payload), 200, {'Content-Type': header.split(';', 1)[0][5:]})
        return _Response(payload.encode('utf-8'), 200, {'Content-Type': header.split(';', 1)[0][5:]})
      raise RuntimeError(f'Browser preview requests only supports data: URLs, got {url!r}')

    def post(*args, **kwargs):
      return _Response(b'', 200, {})

    requests_mod.Session = Session
    requests_mod.get = get
    requests_mod.post = post
    requests_mod.adapters = adapters_mod
    requests_mod.packages = types.SimpleNamespace(urllib3=_Warns())
    adapters_mod.HTTPAdapter = HTTPAdapter
    sys.modules['requests'] = requests_mod
    sys.modules['requests.adapters'] = adapters_mod


_install_stubs()


def _load_real_controller():
  import importlib.util

  spec = importlib.util.spec_from_file_location('real_ticker_controller', '/app/real_ticker_controller.py')
  module = importlib.util.module_from_spec(spec)
  module.__dict__['__name__'] = 'real_ticker_controller'
  module.__dict__['__file__'] = '/app/real_ticker_controller.py'
  sys.modules['real_ticker_controller'] = module
  spec.loader.exec_module(module)
  return module


_RTC = _load_real_controller()
TickerStreamer = _RTC.TickerStreamer
PANEL_W = _RTC.PANEL_W
PANEL_H = _RTC.PANEL_H
StadiumRenderer = _RTC.StadiumRenderer
load_display_font = _RTC.load_display_font
load_monospace_font = _RTC.load_monospace_font


class BrowserTickerStreamer(TickerStreamer):
    def __init__(self):
        self.device_id = 'browser-preview'
        self.mode = 'sports'
        self.mode_override = None
        self.running = False
        self.logo_cache = {}
        self.stadium = StadiumRenderer(logo_cache=self.logo_cache)
        self.font = load_monospace_font(10, bold=True)
        self.medium_font = load_monospace_font(12, bold=True)
        self.big_font = load_monospace_font(14, bold=True)
        self.huge_font = load_display_font(20, bold=True)
        self.clock_giant = load_display_font(28, bold=True)
        self.tiny = load_monospace_font(9)
        self.tiny_small = load_monospace_font(8)
        self.micro = load_monospace_font(7)
        self.nano = load_monospace_font(5)
        self.score_default_font = ImageFont.load_default()
        self.games = []
        self.brightness = 1.0
        self.scroll_sleep = 0.05
        self.inverted = False
        self.is_pairing = False
        self.pairing_code = ''
        self.game_render_cache = {}
        self.anim_tick = 0
        self.active_strip = None
        self.bg_strip = None
        self.bg_strip_ready = False
        self.new_games_list = []
        self.static_items = []
        self.static_index = 0
        self.showing_static = False
        self.static_until = 0.0
        self.static_current_image = None
        self.static_current_game = None
        self.last_applied_hash = ''
        self.current_data_hash = ''
        self.VINYL_SIZE = 51
        self.COVER_SIZE = 42
        self.vinyl_mask = Image.new('L', (self.COVER_SIZE, self.COVER_SIZE), 0)
        ImageDraw.Draw(self.vinyl_mask).ellipse((0, 0, self.COVER_SIZE, self.COVER_SIZE), fill=255)
        self.scratch_layer = Image.new('RGBA', (self.VINYL_SIZE, self.VINYL_SIZE), (0, 0, 0, 0))
        self._init_vinyl_scratch()
        self.vinyl_rotation = 0.0
        self.text_scroll_pos = 0.0
        self.last_frame_time = time.time()
        self.dominant_color = (29, 185, 84)
        self.spindle_color = 'black'
        self.last_cover_url = ''
        self.vinyl_cache = None
        self.prev_vinyl_cache = None
        self.prev_dominant_color = (29, 185, 84)
        self.fade_alpha = 1.0
        self.transitioning_out = False
        self.viz_heights = [2.0] * 16
        self.viz_phase = [0.0] * 16
        self.C_BG = (5, 5, 8)
        self.C_AMBER = (255, 170, 0)
        self.C_BLUE_TXT = (80, 180, 255)
        self.C_WHT = (220, 220, 230)
        self.C_GRN = (80, 255, 80)
        self.C_RED = (255, 60, 60)
        self.C_GRY = (120, 120, 130)

    def get_logo(self, url, size=(24, 24)):
        if not url:
            return None
        cached = self.logo_cache.get(f"{url}_{size}") or self.logo_cache.get(f"{url}_{size[0]}x{size[1]}")
        if cached:
            return cached
        if not str(url).startswith('data:'):
            return None
        try:
            import requests
            raw = Image.open(io.BytesIO(requests.get(url, timeout=1).content)).convert('RGBA')
            raw.thumbnail(size, Image.Resampling.LANCZOS)
            final = Image.new('RGBA', size, (0, 0, 0, 0))
            final.paste(raw, ((size[0] - raw.width) // 2, (size[1] - raw.height) // 2), raw)
            self.logo_cache[f"{url}_{size}"] = final
            self.logo_cache[f"{url}_{size[0]}x{size[1]}"] = final
            return final
        except Exception:
            return None


_RENDERER = BrowserTickerStreamer()
_STATIC_INDEX = 0


def _partition_games(games, mode):
    flight_weather = None
    flight_arrivals = []
    flight_departures = []
    other_games = []

    for game in games:
        if not isinstance(game, dict):
            continue
        game_type = str(game.get('type', ''))
        if game_type == 'flight_weather':
            flight_weather = game
        elif game_type == 'flight_arrival':
            flight_arrivals.append(game)
        elif game_type == 'flight_departure':
            flight_departures.append(game)
        else:
            other_games.append(game)

    if flight_weather or flight_arrivals or flight_departures:
        other_games.append({
            'type': 'flight_airport_hud',
            'sport': 'flight',
            'id': 'airport_hud',
            'is_shown': True,
            '_weather_item': flight_weather,
            '_arrivals': flight_arrivals,
            '_departures': flight_departures,
        })

    static_items = []
    scrolling_items = []

    for game in other_games:
        sport = str(game.get('sport', '')).lower()
        game_type = str(game.get('type', ''))
        is_music = (game_type == 'music' or sport == 'music')
        is_golf_fullscreen = (game_type in ('golf', 'masters') or sport in ('golf', 'masters')) and mode == 'golf'

        if game_type == 'weather' or sport.startswith('clock') or is_golf_fullscreen or is_music or game_type == 'flight_visitor' or game_type == 'flight_airport_hud':
            static_items.append(game)
        elif mode in ('sports_full', 'soccer_full') and game_type not in ['leaderboard', 'stock_ticker'] and 'flight' not in str(game_type):
            static_items.append(game)
        else:
            scrolling_items.append(game)

    return static_items, scrolling_items


def _next_static_game(static_items):
    global _STATIC_INDEX
    if not static_items:
        return None
    game = static_items[_STATIC_INDEX % len(static_items)]
    _STATIC_INDEX += 1
    return game


def _placeholder_item_for_mode(mode):
    mode = str(mode or '').lower()
    if mode == 'music':
        return {
            'type': 'music',
            'sport': 'music',
            'id': 'spotify_idle',
            'status': 'IDLE',
            'state': 'paused',
            'is_shown': True,
            'home_abbr': 'MUSIC',
            'away_abbr': 'NO SONG DATA',
            'home_logo': '',
            'next_logos': [],
            'situation': {
                'progress': 0,
                'duration': 1,
                'is_playing': False,
                'fetch_ts': time.time(),
            },
        }
    if mode == 'flight_tracker':
        return {
            'type': 'flight_visitor',
            'sport': 'flight',
            'id': 'flight_tracker_blank',
            'guest_name': 'NO FLIGHT SELECTED',
            'origin_city': 'TRACKER',
            'dest_city': 'SETUP',
            'alt': 0,
            'dist': 0,
            'eta_str': '--',
            'speed': 0,
            'progress': 0,
            'status': 'ADD FLIGHT',
            'delay_min': 0,
            'is_delayed': False,
            'is_live': False,
            'aircraft_type': '',
            'aircraft_code': '',
            'is_shown': True,
        }
    if mode == 'clock':
        return {'type': 'clock', 'sport': 'clock', 'id': 'clk', 'is_shown': True}
    return None


def render_strip(games, mode='sports'):
    _RENDERER.mode = mode or 'sports'
    _RENDERER.game_render_cache = {}
    playlist = [g for g in games if isinstance(g, dict) and g.get('is_shown', True)]
    if not playlist:
        placeholder = _placeholder_item_for_mode(_RENDERER.mode)
        if placeholder:
            playlist = [placeholder]
    static_items, scrolling_items = _partition_games(playlist, _RENDERER.mode)

    if static_items and not scrolling_items:
        strip = _RENDERER.draw_single_game(_next_static_game(static_items))
    elif _RENDERER.mode in ('sports_full', 'soccer_full') and static_items:
        strip = _RENDERER.draw_single_game(_next_static_game(static_items))
    elif scrolling_items:
        strip = _RENDERER.build_seamless_strip(scrolling_items)
    elif static_items:
        strip = _RENDERER.draw_single_game(_next_static_game(static_items))
    else:
        strip = _RENDERER.draw_clock_modern()

    if strip is None:
        strip = Image.new('RGBA', (PANEL_W, PANEL_H), (0, 0, 0, 255))
    buf = io.BytesIO()
    strip.save(buf, 'PNG')
    return {
        'width': strip.width,
        'height': strip.height,
        'data_b64': base64.b64encode(buf.getvalue()).decode('ascii'),
    }
`;
}

async function ensureControllerRuntime() {
  if (!controllerPromise) {
    controllerPromise = (async () => {
      const pyodide = await ensurePyodide();
      const bundleResp = await fetch(BUNDLE_URL, { cache: 'no-store' });
      if (!bundleResp.ok) throw new Error('bundle HTTP ' + bundleResp.status);
      const bundle = await bundleResp.json();
      const source = String(bundle && bundle.source ? bundle.source : '');

      pyodide.FS.mkdirTree('/app');
      pyodide.FS.writeFile('/app/real_ticker_controller.py', source);
      pyodide.FS.writeFile('/app/browser_entry.py', browserEntrySource());

      await pyodide.runPythonAsync(`
import sys
sys.path.insert(0, '/app')
from browser_entry import render_strip
`);

      return pyodide;
    })();
  }
  return controllerPromise;
}

async function fetchVisibleGames(tickerId, mode) {
  const params = [];
  if (tickerId) params.push('id=' + encodeURIComponent(tickerId));
  if (mode) params.push('mode=' + encodeURIComponent(mode));
  const url = '/data' + (params.length ? '?' + params.join('&') : '');
  const resp = await fetch(url, { cache: 'no-store' });
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  const payload = await resp.json();
  const localConfig = payload && payload.local_config ? payload.local_config : {};
  const effectiveMode = String(localConfig.mode || mode || 'sports');
  const games = payload && payload.content && Array.isArray(payload.content.sports)
    ? payload.content.sports.filter(game => game && game.is_shown !== false)
    : [];
  return {
    mode: effectiveMode,
    games: await Promise.all(games.map(game => inlineGameAssets(game))),
  };
}

async function renderStrip(mode, tickerId) {
  try {
    const pyodide = await ensureControllerRuntime();
    const payload = await fetchVisibleGames(tickerId, mode);
    pyodide.globals.set('browser_games_json', JSON.stringify(payload.games));
    pyodide.globals.set('browser_mode', payload.mode || mode || 'sports');
    const jsonText = await pyodide.runPythonAsync(`
import json
from browser_entry import render_strip

payload = json.loads(browser_games_json)
json.dumps(render_strip(payload, browser_mode))
`);
    const data = JSON.parse(String(jsonText));
    const b64 = data && data.data_b64 ? data.data_b64 : '';
    if (!b64) throw new Error('renderer returned no data');
    return {
      width: data.width || 0,
      height: data.height || 0,
      dataUrl: 'data:image/png;base64,' + b64,
    };
  } catch (err) {
    console.error('Browser ticker runtime failed:', err);
    controllerPromise = null;
    pyodidePromise = null;
    throw err;
  }
}

window.__tickerBrowserRuntime = {
  renderStrip,
};
})();
