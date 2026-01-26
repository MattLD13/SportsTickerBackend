import os
import requests
import threading
import json
from flask import Flask, render_template_string, request, jsonify
from pydub import AudioSegment

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# --- FFmpeg Configuration ---
ffmpeg_path = os.path.join(os.getcwd(), "ffmpeg.exe")
if os.path.exists(ffmpeg_path):
    AudioSegment.converter = ffmpeg_path
    AudioSegment.ffmpeg = ffmpeg_path
    AudioSegment.ffprobe = os.path.join(os.getcwd(), "ffprobe.exe")

app = Flask(__name__)
HORNS_DIR = "horns"

# --- BACKEND LOGIC ---

def upload_and_play(ip, filename):
    print(f"\n[JOB START] Processing: {filename}")
    filepath = os.path.join(HORNS_DIR, filename)
    temp_path = "temp_hq.mp3"

    try:
        # 1. CONVERT (High Quality for ESP32-S3)
        print(">> Converting audio...")
        audio = AudioSegment.from_mp3(filepath)
        
        # ESP32-S3 supports 44100Hz perfectly!
        # Mono is still best for I2S amps unless you have a stereo decoder board.
        audio = audio.set_channels(1).set_frame_rate(44100) 
        
        # 128k bitrate is much better quality than 32k/64k
        audio.export(temp_path, format="mp3", bitrate="128k") 

        # 2. UPLOAD
        print(f">> Uploading to {ip}...")
        with open(temp_path, 'rb') as f:
            files = {'file': ('current.mp3', f, 'audio/mpeg')}
            try:
                # 10s connect, 60s read timeout
                r = requests.post(f"http://{ip}/upload", files=files, timeout=(10, 60))
                if r.status_code != 200:
                    print(f"[ERROR] Upload failed: {r.status_code}")
                    return
            except Exception as e:
                print(f"[ERROR] Connection failed: {e}")
                return

        # 3. PLAY
        print(">> Sending Play Command...")
        try:
            requests.get(f"http://{ip}/play", timeout=3)
            print("[SUCCESS] Playing!")
        except:
            pass 

    except Exception as e:
        print(f"[CRITICAL ERROR] {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# --- FLASK ROUTES ---

@app.route('/')
def index():
    if not os.path.exists(HORNS_DIR): os.makedirs(HORNS_DIR)
    # Get list of files
    files = sorted([f for f in os.listdir(HORNS_DIR) if f.endswith('.mp3')])
    return render_template_string(HTML_UI, files=files)

@app.route('/api/play', methods=['POST'])
def api_play():
    data = request.json
    ip = data.get('ip')
    filename = data.get('filename')
    
    if not ip or not filename:
        return jsonify({"status": "error", "message": "Missing IP"}), 400

    # Start background thread
    threading.Thread(target=upload_and_play, args=(ip, filename)).start()
    return jsonify({"status": "success", "message": f"Loading {filename}..."})

@app.route('/api/control', methods=['POST'])
def api_control():
    data = request.json
    ip = data.get('ip')
    cmd = data.get('cmd') # 'stop' or 'volume'
    val = data.get('val') # Volume amount (0.0 to 1.5)

    try:
        if cmd == 'stop':
            requests.get(f"http://{ip}/stop", timeout=2)
            return jsonify({"status": "success", "message": "Stopped"})
        
        elif cmd == 'volume':
            # ESP expects 0.0 to 1.5 roughly
            vol_map = float(val) / 100.0 
            requests.get(f"http://{ip}/set_volume?val={vol_map}", timeout=2)
            return jsonify({"status": "success", "message": f"Vol: {val}%"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
    
    return jsonify({"status": "error"}), 400

# --- MODERN UI TEMPLATE ---
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🚨 Goal Horn Control</title>
    <style>
        :root { --primary: #e50914; --dark: #141414; --gray: #333; --light: #f5f5f5; }
        body { background-color: var(--dark); color: var(--light); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; text-align: center; }
        
        /* HEADER & SETTINGS */
        h1 { margin-bottom: 5px; text-transform: uppercase; letter-spacing: 2px; }
        .settings-bar { background: var(--gray); padding: 15px; border-radius: 10px; display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; align-items: center; max-width: 600px; margin: 20px auto; }
        input[type="text"] { padding: 10px; border-radius: 5px; border: none; width: 140px; text-align: center; font-weight: bold; }
        
        /* CONTROLS */
        .btn { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; transition: 0.2s; color: white; }
        .btn-stop { background: var(--primary); width: 100%; font-size: 1.2rem; padding: 15px; max-width: 600px; margin: 10px auto; display: block; }
        .btn-stop:active { transform: scale(0.98); }
        .volume-control { display: flex; align-items: center; gap: 10px; }
        input[type="range"] { accent-color: #00bc8c; cursor: pointer; }

        /* SEARCH */
        #searchBox { width: 100%; max-width: 600px; padding: 15px; font-size: 16px; margin: 20px auto; display: block; border-radius: 8px; border: none; box-sizing: border-box; }

        /* GRID */
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; max-width: 1000px; margin: 0 auto; }
        .card { background: var(--gray); padding: 15px; border-radius: 8px; cursor: pointer; transition: 0.2s; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 80px; }
        .card:hover { background: #444; transform: translateY(-2px); }
        .card:active { background: #555; transform: scale(0.95); }
        .team-name { font-weight: bold; font-size: 14px; word-break: break-word; }

        /* TOAST NOTIFICATION */
        #toast { visibility: hidden; min-width: 250px; background-color: #333; color: #fff; text-align: center; border-radius: 5px; padding: 16px; position: fixed; z-index: 1; left: 50%; bottom: 30px; transform: translateX(-50%); box-shadow: 0px 4px 15px rgba(0,0,0,0.5); }
        #toast.show { visibility: visible; animation: fadein 0.5s, fadeout 0.5s 2.5s; }
        
        @keyframes fadein { from {bottom: 0; opacity: 0;} to {bottom: 30px; opacity: 1;} }
        @keyframes fadeout { from {bottom: 30px; opacity: 1;} to {bottom: 0; opacity: 0;} }
    </style>
</head>
<body>

    <h1>🚨 NHL Goal Horns</h1>
    
    <div class="settings-bar">
        <div>
            <label style="font-size:12px; color:#aaa;">ESP8266 IP ADDRESS</label><br>
            <input type="text" id="espIP" placeholder="192.168.X.X" onchange="saveIP()">
        </div>
        <div class="volume-control">
            <span>🔊</span>
            <input type="range" min="0" max="150" value="100" id="volSlider" onchange="setVolume(this.value)">
        </div>
    </div>

    <button class="btn btn-stop" onclick="stopHorn()">⏹ EMERGENCY STOP</button>

    <input type="text" id="searchBox" placeholder="🔍 Search Teams..." onkeyup="filterGrid()">

    <div class="grid" id="teamGrid">
        {% for file in files %}
        <div class="card" onclick="playHorn('{{ file }}')">
            <div class="team-name">{{ file | replace('.mp3', '') | replace('_', ' ') }}</div>
        </div>
        {% endfor %}
    </div>

    <div id="toast">Notification</div>

    <script>
        // 1. Load IP from Memory on Startup
        window.onload = function() {
            const savedIP = localStorage.getItem('esp_ip');
            if (savedIP) document.getElementById('espIP').value = savedIP;
        }

        // 2. Save IP to Memory
        function saveIP() {
            const ip = document.getElementById('espIP').value;
            localStorage.setItem('esp_ip', ip);
        }

        function getIP() {
            const ip = document.getElementById('espIP').value;
            if(!ip) { showToast("⚠️ Enter ESP IP Address first!"); return null; }
            return ip;
        }

        // 3. Play Function
        function playHorn(filename) {
            const ip = getIP();
            if(!ip) return;

            showToast("⏳ Uploading " + filename + "...");
            
            fetch('/api/play', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ ip: ip, filename: filename })
            })
            .then(res => res.json())
            .then(data => {
                console.log(data);
            })
            .catch(err => showToast("❌ Error connecting to Server"));
        }

        // 4. Stop Function
        function stopHorn() {
            const ip = getIP();
            if(!ip) return;
            
            fetch('/api/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ ip: ip, cmd: 'stop' })
            }).then(showToast("🛑 Stopping..."));
        }

        // 5. Volume Function
        function setVolume(val) {
            const ip = getIP();
            if(!ip) return;

            fetch('/api/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ ip: ip, cmd: 'volume', val: val })
            });
        }

        // 6. Search Filter
        function filterGrid() {
            const input = document.getElementById('searchBox');
            const filter = input.value.toUpperCase();
            const grid = document.getElementById("teamGrid");
            const cards = grid.getElementsByClassName('card');

            for (let i = 0; i < cards.length; i++) {
                let txt = cards[i].innerText;
                if (txt.toUpperCase().indexOf(filter) > -1) {
                    cards[i].style.display = "flex";
                } else {
                    cards[i].style.display = "none";
                }
            }
        }

        // 7. Toast Helper
        function showToast(msg) {
            var x = document.getElementById("toast");
            x.innerText = msg;
            x.className = "show";
            setTimeout(function(){ x.className = x.className.replace("show", ""); }, 3000);
        }
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)