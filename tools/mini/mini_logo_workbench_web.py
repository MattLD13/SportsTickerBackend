"""Serve the browser logo workbench and bridge its preview to the mini ticker."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import base64
import json
import os
import sys
import threading
import time
from urllib.parse import urlparse

from flask import Flask, jsonify, request, Response
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image
from ticker_core.features.sports.logo_rendering import prepare_team_logo, team_logo_layout
from ticker_core.features.sports.logo_visibility import mean_edge_brightness, paste_team_logo


BACKEND_URL = os.environ.get("TICKER_BACKEND_URL", "https://ticker.mattdicks.org").rstrip("/")
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SportsTicker" / "LogoWorkbench"
STATE_PATH = STATE_DIR / "state.json"
COMPARISON_PICKS_PATH = STATE_DIR / "comparison-picks.json"
OHIO_STATE_LOGO_PATH = ROOT / "tools" / "assets" / "ohio-state-white-text.svg"
ALLOWED_LOGO_HOSTS = {"a.espncdn.com", "raw.githubusercontent.com", "upload.wikimedia.org"}
app = Flask(__name__)
http = requests.Session()
serial_lock = threading.Lock()
comparison_picks_lock = threading.Lock()
serial_device = None
serial_firmware = None
WORKBENCH_FIRMWARE = "mini-1.2.8"


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SportsTicker Logo Workbench</title>
<style>
:root{color-scheme:dark;--bg:#0a101c;--panel:#111b2b;--panel2:#17243a;--line:#273952;--text:#eef3fa;--muted:#9aaac0;--mint:#5dd6c0;--gold:#f1bd68;--blue:#24466a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Segoe UI",system-ui,sans-serif}button,input,select{font:inherit}button{border:0;border-radius:8px;background:#203650;color:var(--text);padding:10px 14px;cursor:pointer}button:hover{background:#2b4a6e}.app{max-width:1440px;margin:auto;padding:24px}.eyebrow{color:var(--mint);font-size:11px;font-weight:700;letter-spacing:.13em}.heading{font-size:27px;font-weight:700;margin:4px 0}.sub{color:var(--muted);margin:0}.toolbar{display:flex;gap:9px;align-items:center;background:var(--panel);border:1px solid #1e2b40;border-radius:12px;padding:12px;margin:18px 0 16px}.toolbar .spacer{flex:1}.toolbar label{color:var(--muted)}input,select{background:#080e18;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:9px}.status{color:var(--muted);min-width:230px;text-align:right}.grid{display:grid;grid-template-columns:320px 1fr;gap:16px;align-items:stretch}.card{background:var(--panel);border:1px solid #1e2b40;border-radius:12px;padding:16px}.library{height:calc(100vh - 245px);min-height:500px;display:flex;flex-direction:column}.library-head{display:flex;align-items:center;justify-content:space-between;font-weight:700;margin-bottom:12px}.search{width:100%;margin-bottom:9px}.filters{display:flex;gap:8px;margin-bottom:8px}.filters select{flex:1;min-width:0}.items{overflow:auto;flex:1}.item{display:flex;align-items:center;gap:10px;padding:8px;border-radius:8px;cursor:pointer;border:1px solid transparent}.item:hover{background:#15253a}.item.selected{background:#183653;border-color:#2d577b}.item img,.thumb{height:38px;width:38px;object-fit:contain;background:#05070b;border-radius:6px;image-rendering:pixelated}.item .name{min-width:0;flex:1;font-weight:600}.item small{display:block;color:var(--muted);font-weight:400}.pill{font-size:10px;font-weight:700;letter-spacing:.06em;color:var(--gold)}.pill.done{color:var(--mint)}.work{min-width:0}.preview-card{margin-bottom:14px}.section-title{font-size:11px;color:#afbdd0;font-weight:700;letter-spacing:.06em;margin:0 0 10px}.tick-big{width:min(100%,768px);height:64px;display:block;background:#000;border:1px solid var(--line);image-rendering:pixelated}.mini-title{margin-top:15px}.tick-mini{width:min(100%,512px);height:256px;display:block;background:#000;border:1px solid var(--line);image-rendering:pixelated}.tune{display:flex;gap:20px;align-items:center;flex-wrap:wrap}.switch{display:flex;gap:10px;align-items:center}.tune input[type=range]{width:min(400px,36vw);accent-color:var(--mint);padding:0}.hint{color:#788ca6;font-size:11px;margin-top:9px}.outline-btn.active{background:#26514f;color:#c7fff4}.device{display:flex;gap:9px;align-items:center}.device input{width:100px}.secondary{background:#152239}.logo-name{color:var(--text);font-weight:650;margin-bottom:9px}.error{color:#ff9898}.count{color:var(--muted);font-size:12px}.file-input{display:none}@media(max-width:900px){.app{padding:14px}.grid{grid-template-columns:1fr}.library{height:280px;min-height:0}.toolbar{flex-wrap:wrap}.toolbar .spacer{display:none}.status{text-align:left}.tick-mini{max-width:100%;height:auto;aspect-ratio:2}}
</style></head><body>
<main class="app">
<div class="eyebrow">LOGO WORKBENCH</div><div class="heading">Tune it on the mini. Ship it on the big.</div>
<p class="sub">Logos come from the ticker server. The mini preview compensates for P2.5 pixels against the big ticker’s P3 pixels.</p>
<div class="toolbar"><button id="reload">↻ Refresh server logos</button><button id="addFile" class="secondary">＋ Add image</button><button class="secondary" onclick="location.href='/compare'">Compare every logo ↗</button><input id="fileInput" class="file-input" type="file" accept="image/*" multiple><div class="spacer"></div><div class="device"><label for="port">Mini ticker port</label><input id="port" value="COM11"><button id="connect">Connect</button></div><div class="status" id="status">Loading ticker server catalog…</div></div>
<div class="grid"><section class="card library"><div class="library-head"><span>LOGO LIBRARY</span><span class="count" id="count">—</span></div><input class="search" id="search" placeholder="Search teams or leagues"><div class="filters"><select id="league"><option value="all">All leagues</option></select><select id="state"><option value="all">All status</option><option value="todo">To do</option><option value="done">Complete</option></select></div><div id="items" class="items"></div></section>
<section class="work"><div class="card preview-card"><div class="section-title">BIG TICKER · 384 × 32</div><canvas id="big" class="tick-big" width="384" height="32"></canvas><div class="section-title mini-title">MINI TICKER · 64 × 32 · HARDWARE VIEW</div><canvas id="mini" class="tick-mini" width="64" height="32"></canvas><div class="hint" id="pixelDetails">Preparing native ticker pixels…</div></div>
<div class="card"><div class="section-title">TUNE PIXELS</div><div class="tune"><label for="renderMode">Big ticker layout</label><select id="renderMode"><option value="scrolling">Scrolling</option><option value="full_screen">Full screen</option></select><button id="outline" class="outline-btn active">Outline: ticker default · O</button><label for="sensitivity">Outline darkness cutoff</label><input id="sensitivity" type="range" min="0" max="100" value="35"><span id="sensitivityValue">35</span></div><div class="hint">Adjust the cutoff to use a darkness rule. Lower values outline darker logos. Higher values include lighter colors.</div><div class="hint">← → select &nbsp; O cycle ticker default / off / complete inner / inner by darkness &nbsp; − / + cutoff &nbsp; ENTER complete &nbsp; CTRL + O add image</div></div></section></div>
</main>
<script>
const $=id=>document.getElementById(id);let teams=[],selected=null,done=new Set(),outlineMode='ticker',sensitivity=35,renderMode='scrolling',serialConnected=false,currentBlob=null,currentPrepared=null,prepareTimer=null,prepareGeneration=0,selectionGeneration=0,sending=false,pendingFrame=null;
const big=$('big'),mini=$('mini'),bctx=big.getContext('2d'),mctx=mini.getContext('2d');
function key(t){return t.file?'file:'+t.name:t.league+':'+t.abbr}
function status(s){$('status').textContent=s}
async function loadState(){try{done=new Set(await (await fetch('/api/state')).json())}catch{done=new Set()}}
async function loadCatalog(){status('Loading logos from ticker server…');$('items').innerHTML='';try{const res=await fetch('/api/catalog');if(!res.ok)throw new Error((await res.json()).error||res.statusText);teams=await res.json();const leagues=[...new Set(teams.map(t=>t.league))].sort();$('league').innerHTML='<option value="all">All leagues</option>'+leagues.map(x=>`<option>${esc(x)}</option>`).join('');renderList();if(teams.length){select(0);status(`${teams.length} logos loaded from ticker server`)}else status('No team logos were returned')}catch(e){status('Ticker server unavailable: '+e.message);$('items').innerHTML='<div class="error">Could not load the V2 team catalog.</div>'}}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function renderList(){const query=$('search').value.toLowerCase(),league=$('league').value,state=$('state').value;const filtered=teams.filter(t=>(league==='all'||t.league===league)&&(!query||(t.abbr+' '+t.league).toLowerCase().includes(query))&&(state==='all'||(state==='done')===done.has(key(t))));$('count').textContent=`${done.size} complete`;const rows=filtered.map(t=>`<div class="item ${selected&&key(t)===key(selected)?'selected':''}" data-key="${esc(key(t))}"><img loading="lazy" src="${t.file?esc(t.logo):'/api/logo?url='+encodeURIComponent(t.logo)}" alt=""><span class="name">${esc(t.abbr)}<small>${esc(t.league)}</small></span><span class="pill ${done.has(key(t))?'done':''}">${done.has(key(t))?'DONE':'TODO'}</span></div>`).join('');$('items').innerHTML=rows||'<div class="sub">No logos match this filter.</div>';for(const el of $('items').querySelectorAll('.item'))el.onclick=()=>select(teams.find(t=>key(t)===el.dataset.key))}
function loadImage(blob){currentBlob=blob;queuePrepare()}
async function rasterizeLogo(blob,targetSize){if(!blob.type.toLowerCase().includes('svg'))return blob;const url=URL.createObjectURL(blob);try{const image=await new Promise((resolve,reject)=>{const item=new Image();item.onload=()=>resolve(item);item.onerror=()=>reject(new Error('Could not decode the SVG logo.'));item.src=url});const canvas=document.createElement('canvas');canvas.width=targetSize;canvas.height=targetSize;const scale=Math.min(targetSize/image.naturalWidth,targetSize/image.naturalHeight);const width=image.naturalWidth*scale,height=image.naturalHeight*scale;canvas.getContext('2d').drawImage(image,(targetSize-width)/2,(targetSize-height)/2,width,height);return await new Promise((resolve,reject)=>canvas.toBlob(png=>png?resolve(png):reject(new Error('Could not rasterize the SVG logo.')),'image/png'))}finally{URL.revokeObjectURL(url)}}
function queuePrepare(){clearTimeout(prepareTimer);pendingFrame=null;const generation=++prepareGeneration;prepareTimer=setTimeout(async()=>{if(!currentBlob||!selected)return;try{const form=new FormData();const nativeSize=renderMode==='scrolling'?22:24;const image=await rasterizeLogo(currentBlob,nativeSize);const filename=(selected.name||`${selected.abbr||'logo'}.png`).replace(/\.svg$/i,'.png');form.append('image',image,filename);const league=selected.league_id||'custom';const response=await fetch(`/api/prepare?league=${encodeURIComponent(league)}&view=${renderMode}&sensitivity=${sensitivity}&outline=${outlineMode}`,{method:'POST',body:form});const prepared=await response.json();if(!response.ok)throw Error(prepared.error||'Logo preparation failed');const images=await Promise.all([prepared.big_png,prepared.mini_png].map(async data=>createImageBitmap(await(await fetch('data:image/png;base64,'+data)).blob())));if(generation!==prepareGeneration){images.forEach(image=>image.close());return}currentPrepared={...prepared,images,label:selected.abbr||selected.name,generation};renderFrame()}catch(error){if(generation===prepareGeneration)status(error.message)}},100)}
function renderFrame(){for(const [canvas,ctx] of [[big,bctx],[mini,mctx]]){ctx.fillStyle='#000';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.imageSmoothingEnabled=false}if(!currentPrepared)return;bctx.drawImage(currentPrepared.images[0],0,0);mctx.drawImage(currentPrepared.images[1],0,0);const d=currentPrepared.details;$('pixelDetails').textContent=`Big ${d.size}px → Mini ${d.mini_size}px · P3/P2.5 physical size match · centered · outline ${d.outline_added?'on':'off'}`;if(serialConnected)sendFrame(currentPrepared)}
async function sendFrame(prepared){pendingFrame=prepared;if(sending)return;sending=true;while(pendingFrame){const next=pendingFrame;pendingFrame=null;try{const r=await fetch('/api/frame',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rgb:next.rgb})});const j=await r.json();if(next.generation===prepareGeneration)status(r.ok?`Mini ticker confirms ${next.label} · ${next.details.view.replace('_',' ')} · ${j.port}`:j.error)}catch(e){if(next.generation===prepareGeneration)status('Ticker send failed: '+e.message)}}sending=false}
async function select(i){if(typeof i==='number')i=teams[i];if(!i)return;const selection=++selectionGeneration;++prepareGeneration;clearTimeout(prepareTimer);pendingFrame=null;selected=i;currentPrepared=null;currentBlob=null;renderFrame();renderList();if(i.file){loadImage(i.blob)}else{status(`${i.league} · ${i.abbr} · loading logo`);try{const r=await fetch('/api/logo?url='+encodeURIComponent(i.logo));if(!r.ok)throw Error('Logo download failed');const blob=await r.blob();if(selection===selectionGeneration)loadImage(blob)}catch(e){if(selection===selectionGeneration)status(e.message)}}}
async function toggleDone(){if(!selected)return;const k=key(selected);done.has(k)?done.delete(k):done.add(k);await fetch('/api/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify([...done])});renderList()}
$('reload').onclick=loadCatalog;$('search').oninput=renderList;$('league').onchange=renderList;$('state').onchange=renderList;
function outlineLabel(){const labels={ticker:'ticker default',off:'off',inner:'complete inner 1 px',auto:'inner by darkness'};$('outline').textContent=`Outline: ${labels[outlineMode]} · O`;$('outline').classList.toggle('active',outlineMode!=='off')}
$('outline').onclick=()=>{const modes=['ticker','off','inner','auto'];outlineMode=modes[(modes.indexOf(outlineMode)+1)%modes.length];outlineLabel();queuePrepare()};$('sensitivity').oninput=e=>{sensitivity=+e.target.value;outlineMode='auto';outlineLabel();$('sensitivityValue').textContent=sensitivity;queuePrepare()};
$('renderMode').onchange=e=>{renderMode=e.target.value;queuePrepare()};
$('addFile').onclick=()=>$('fileInput').click();$('fileInput').onchange=e=>{for(const f of e.target.files){const item={file:true,name:f.name,abbr:f.name,blob:f,league:'Computer',logo:URL.createObjectURL(f)};teams.unshift(item)}renderList();if(e.target.files[0])select(teams[0])};async function connectTicker(){try{const r=await fetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({port:$('port').value})}),j=await r.json();if(!r.ok)throw Error(j.error);serialConnected=true;status(`Connected to ${j.port} · ${j.firmware}`);if(currentPrepared)renderFrame()}catch(e){serialConnected=false;status('Cannot connect: '+e.message)}}$('connect').onclick=connectTicker;
document.onkeydown=e=>{if(e.ctrlKey&&e.key.toLowerCase()==='o'){e.preventDefault();$('fileInput').click();return}if(e.target.matches('input,select'))return;if(e.key==='ArrowLeft'||e.key==='ArrowRight'){const i=teams.findIndex(t=>selected&&key(t)===key(selected));select((i+(e.key==='ArrowRight'?1:-1)+teams.length)%teams.length)}else if(e.key.toLowerCase()==='o')$('outline').click();else if(e.key==='+'||e.key==='=')$('sensitivity').stepUp(5),$('sensitivity').dispatchEvent(new Event('input'));else if(e.key==='-')$('sensitivity').stepDown(5),$('sensitivity').dispatchEvent(new Event('input'));else if(e.key==='Enter'||e.key===' ')toggleDone()};
renderFrame();loadState().then(loadCatalog);fetch('/api/device').then(r=>r.json()).then(j=>{serialConnected=j.connected;if(j.port)$('port').value=j.port;if(serialConnected){if(currentPrepared)renderFrame()}else connectTicker()}).catch(()=>connectTicker());
</script></body></html>"""


def _load_state() -> list[str]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return [str(item) for item in data if isinstance(item, str)]
    except (OSError, ValueError, TypeError):
        return []


def _png_base64(image: Image.Image) -> str:
    """Encode one completed RGB frame for a browser preview."""
    output = BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _prepare_frames(raw: bytes, *, league: str, view: str, sensitivity: int, outline: str, method: str = "old") -> dict:
    """Render native logo pixels once and place them on both black frames."""
    if not 0 <= sensitivity <= 100:
        raise ValueError("Sensitivity must range from zero to one hundred.")
    layout = team_logo_layout(view, league)
    mark = prepare_team_logo(raw, layout, method=method)
    native = Image.new("RGBA", mark.size, (0, 0, 0, 255))
    added = paste_team_logo(native, mark, (0, 0), outline=outline, darkness_cutoff=sensitivity * 255 / 100)
    native = native.convert("RGB")
    big = Image.new("RGB", (384, 32), "black")
    big_position = ((384 - layout.size) // 2, (32 - layout.size) // 2)
    big.paste(native, big_position)
    mini_size = round(layout.size * 3 / 2.5)
    mini_mark = native.resize((mini_size, mini_size), Image.Resampling.NEAREST)
    mini = Image.new("RGB", (64, 32), "black")
    mini_position = ((64 - mini_size) // 2, (32 - mini_size) // 2)
    mini.paste(mini_mark, mini_position)
    return {
        "big_png": _png_base64(big),
        "mini_png": _png_base64(mini),
        "rgb": base64.b64encode(mini.tobytes()).decode("ascii"),
        "details": {
            "view": view,
            "size": layout.size,
            "mini_size": mini_size,
            "big_x": big_position[0],
            "mini_x": mini_position[0],
            "y": mini_position[1],
            "outline": outline,
            "outline_added": added,
            "edge_brightness": mean_edge_brightness(mark) * 100 / 255,
            "cutoff": sensitivity,
        },
    }


@app.get("/")
def index():
    from flask import Response

    return Response(PAGE, mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.get("/compare")
def compare():
    comparison_path = ROOT / "tools" / "mini" / "mini_logo_comparison.html"
    return Response(comparison_path.read_text(encoding="utf-8"), mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.get("/api/catalog")
def catalog():
    try:
        response = http.get(f"{BACKEND_URL}/api/v2/catalog/leagues", timeout=25)
        response.raise_for_status()
        source_leagues = response.json().get("leagues", [])
        leagues = [x for x in source_leagues if x.get("type") == "sport" and x.get("my_teams_enabled") and not x.get("conference_parent")]

        def fetch_teams(league: dict) -> list[dict]:
            result = http.get(f"{BACKEND_URL}/api/v2/catalog/leagues/{league['id']}/teams", timeout=25)
            result.raise_for_status()
            return [
                {
                    "league": league["label"],
                    "league_id": league["id"],
                    "abbr": team["abbr"],
                    "logo": "workbench:ohio-state-white-text-v1" if league["id"] == "ncf_fbs" and team["abbr"] == "OSU" else team["logo"],
                }
                for team in result.json().get("teams", [])
                if team.get("abbr") and team.get("logo")
            ]

        with ThreadPoolExecutor(max_workers=6) as pool:
            teams = [team for group in pool.map(fetch_teams, leagues) for team in group]
        return jsonify(teams)
    except (requests.RequestException, KeyError, ValueError) as error:
        return jsonify({"error": f"Ticker server catalog request failed: {error}"}), 502


@app.get("/api/logo")
def logo():
    source = request.args.get("url", "")
    if source == "workbench:ohio-state-white-text-v1":
        return Response(OHIO_STATE_LOGO_PATH.read_bytes(), mimetype="image/svg+xml", headers={"Cache-Control": "no-store"})
    parsed = urlparse(source)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_LOGO_HOSTS:
        return jsonify({"error": "Logo source is not allowed."}), 400
    try:
        response = http.get(source, headers={"User-Agent": "SportsTickerLogoWorkbench/1.0", "Accept": "image/*"}, timeout=15)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/png").split(";")[0]
        if not content_type.startswith("image/") or len(response.content) > 5_000_000:
            return jsonify({"error": "Logo response is not a supported image."}), 415
        return Response(response.content, mimetype=content_type, headers={"Cache-Control": "public, max-age=3600"})
    except requests.RequestException as error:
        return jsonify({"error": f"Logo download failed: {error}"}), 502


@app.post("/api/prepare")
def prepare_logo():
    uploaded = request.files.get("image")
    if uploaded is None:
        return jsonify({"error": "Choose a logo image."}), 400
    raw = uploaded.read()
    if not raw or len(raw) > 5_000_000:
        return jsonify({"error": "Logo image must be between one byte and five megabytes."}), 413
    try:
        rendered = _prepare_frames(
            raw,
            league=request.args.get("league", "custom").strip().lower(),
            view=request.args.get("view", "scrolling"),
            sensitivity=int(request.args.get("sensitivity", "35")),
            outline=request.args.get("outline", "ticker"),
            method=request.args.get("method", "old"),
        )
        return jsonify(rendered)
    except (OSError, ValueError) as error:
        return jsonify({"error": f"Could not prepare logo: {error}"}), 400


@app.route("/api/state", methods=["GET", "POST"])
def state():
    if request.method == "GET":
        return jsonify(_load_state())
    values = request.get_json(silent=True)
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        return jsonify({"error": "Completion state must be a list of keys."}), 400
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(sorted(set(values)), indent=2), encoding="utf-8")
    return jsonify({"saved": len(set(values))})


@app.route("/api/comparison-picks", methods=["GET", "POST"])
def comparison_picks():
    with comparison_picks_lock:
        try:
            picks = json.loads(COMPARISON_PICKS_PATH.read_text(encoding="utf-8"))
            if not isinstance(picks, dict):
                picks = {}
        except (OSError, ValueError):
            picks = {}
        if request.method == "GET":
            return jsonify(picks)

        body = request.get_json(silent=True) or {}
        key = str(body.get("key") or "").strip()
        choice = str(body.get("choice") or "").strip().lower()
        abbreviation = str(body.get("abbr") or "").strip()
        league = str(body.get("league") or "").strip()
        legacy_outline = str(body.get("outline") or "off").strip().lower()
        try:
            old_outline = str(body.get("old_outline", legacy_outline) or "off").strip().lower()
            old_cutoff = int(body.get("old_cutoff", body.get("cutoff", 35)))
            new_outline = str(body.get("new_outline", legacy_outline) or "off").strip().lower()
            new_cutoff = int(body.get("new_cutoff", body.get("cutoff", 35)))
        except (TypeError, ValueError):
            return jsonify({"error": "Outline cutoff must be an integer."}), 400
        if not key or not abbreviation or not league or choice not in {"old", "new"}:
            return jsonify({"error": "Choose OLD or NEW for one logo."}), 400
        valid_outlines = {"ticker", "off", "inner", "auto"}
        if (
            old_outline not in valid_outlines
            or new_outline not in valid_outlines
            or not 0 <= old_cutoff <= 100
            or not 0 <= new_cutoff <= 100
        ):
            return jsonify({"error": "Outline mode or cutoff is invalid."}), 400
        picks[key] = {
            "choice": choice,
            "abbr": abbreviation,
            "league": league,
            "old_outline": old_outline,
            "old_cutoff": old_cutoff,
            "new_outline": new_outline,
            "new_cutoff": new_cutoff,
            "saved_at": time.time(),
        }
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        COMPARISON_PICKS_PATH.write_text(json.dumps(picks, indent=2, sort_keys=True), encoding="utf-8")
        return jsonify({"saved": True, "key": key, "choice": choice, "count": len(picks)})


@app.post("/api/rendering-manifest")
def rendering_manifest():
    """Apply saved review choices to the versioned V2 logo policy manifest."""
    from tools.export_logo_rendering_decisions import build_manifest

    catalog_response = catalog()
    if catalog_response.status_code >= 400:
        return catalog_response
    teams = catalog_response.get_json(silent=True)
    with comparison_picks_lock:
        try:
            picks = json.loads(COMPARISON_PICKS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            picks = {}
    try:
        manifest = build_manifest(teams, picks)
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400
    target = ROOT / "sports_ticker" / "projections" / "logo_rendering_decisions.json"
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    decisions = manifest["decisions"]
    return jsonify({
        "saved": True,
        "count": len(decisions),
        "new": sum(item["choice"] == "new" for item in decisions),
        "old": sum(item["choice"] == "old" for item in decisions),
        "unreviewed": sum(not item["choice"] for item in decisions),
        "target_ticker_id": manifest["target_ticker_id"],
        "path": str(target),
    })


@app.post("/api/connect")
def connect():
    global serial_device, serial_firmware
    body = request.get_json(silent=True) or {}
    port = str(body.get("port", "")).strip()
    if not port:
        return jsonify({"error": "Enter the ticker serial port."}), 400
    try:
        import serial

        with serial_lock:
            if serial_device is not None:
                serial_device.close()
            serial_device = serial.Serial(port, 115200, timeout=0.2, write_timeout=3)
            serial_firmware = None
            deadline = time.monotonic() + 18
            ready = False
            while time.monotonic() < deadline:
                serial_device.write(b"PING\n")
                serial_device.flush()
                retry_at = time.monotonic() + 1
                while time.monotonic() < retry_at:
                    line = serial_device.readline().decode("utf-8", errors="ignore").strip()
                    if line.startswith("MINI_READY:"):
                        serial_firmware = line.partition(":")[2]
                        ready = True
                        break
                if ready:
                    break
            if not ready:
                serial_device.close()
                serial_device = None
                return jsonify({"error": f"No MINI_READY response from {port}. Check the USB port and firmware."}), 503
            if serial_firmware != WORKBENCH_FIRMWARE:
                serial_device.close()
                serial_device = None
                return jsonify({"error": f"Ticker runs {serial_firmware}. Flash {WORKBENCH_FIRMWARE} for this workbench."}), 409
        return jsonify({"connected": True, "port": port, "firmware": serial_firmware})
    except Exception as error:
        serial_device = None
        return jsonify({"error": str(error)}), 503


@app.get("/api/device")
def device():
    with serial_lock:
        connected = serial_device is not None and serial_device.is_open
        return jsonify({"connected": connected, "port": serial_device.port if connected else None, "firmware": serial_firmware})


@app.post("/api/disconnect")
def disconnect():
    global serial_device, serial_firmware
    with serial_lock:
        if serial_device is not None:
            serial_device.close()
        serial_device = None
        serial_firmware = None
    return jsonify({"connected": False})


def _frame_checksum(rgb: bytes) -> str:
    """Match the firmware checksum for each received RGB frame."""
    result = 2166136261
    for value in rgb:
        result = ((result ^ value) * 16777619) & 0xFFFFFFFF
    return f"{result:08x}"


@app.post("/api/frame")
def frame():
    body = request.get_json(silent=True) or {}
    try:
        rgb = base64.b64decode(body.get("rgb", ""), validate=True)
    except (ValueError, TypeError):
        return jsonify({"error": "Frame data must use valid base64."}), 400
    if len(rgb) != 64 * 32 * 3:
        return jsonify({"error": "Frame size must be 64 by 32 RGB."}), 400
    with serial_lock:
        if serial_device is None or not serial_device.is_open:
            return jsonify({"error": "Connect the mini ticker first."}), 409
        try:
            serial_device.write(b"FRAME64:" + base64.b64encode(rgb) + b"\n")
            serial_device.flush()
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                line = serial_device.readline().decode("utf-8", errors="ignore")
                if line.startswith("FRAME_OK:"):
                    checksum = line.strip().partition(":")[2]
                    if checksum != _frame_checksum(rgb):
                        return jsonify({"error": "Mini ticker frame checksum does not match."}), 502
                    return jsonify({"sent": True, "displayed": True, "port": serial_device.port, "checksum": checksum})
                if "FRAME_ERROR" in line:
                    return jsonify({"error": "Mini ticker rejected the logo frame."}), 422
            return jsonify({"error": "Mini ticker did not acknowledge the RGB frame."}), 504
        except Exception as error:
            return jsonify({"error": str(error)}), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("MINI_LOGO_WORKBENCH_PORT", "8765")), threaded=True, use_reloader=False)
