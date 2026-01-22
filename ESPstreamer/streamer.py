import os
import requests
import threading
from flask import Flask, render_template_string, request
from pydub import AudioSegment

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# FFmpeg Check
ffmpeg_path = os.path.join(os.getcwd(), "ffmpeg.exe")
if os.path.exists(ffmpeg_path):
    AudioSegment.converter = ffmpeg_path
    AudioSegment.ffmpeg = ffmpeg_path
    AudioSegment.ffprobe = os.path.join(os.getcwd(), "ffprobe.exe")

app = Flask(__name__)
HORNS_DIR = "horns"

def upload_and_play(ip, filename):
    print(f"\n--- PROCESSING: {filename} ---")
    filepath = os.path.join(HORNS_DIR, filename)
    temp_path = "temp_small.mp3"

    try:
        # 1. OPTIMIZE AUDIO
        print("Step 1: Converting...")
        audio = AudioSegment.from_mp3(filepath)
        
        # Remove length limit (Play full song)
        # audio = audio[:60000] <--- LIMIT REMOVED
        
        # COMPRESSION FIX: Lower bitrate to 32k to save space
        audio = audio.set_channels(1).set_frame_rate(16000)
        audio.export(temp_path, format="mp3", bitrate="32k")
        
        size = os.path.getsize(temp_path)
        print(f"DEBUG: New Size: {size} bytes")

        # 2. UPLOAD
        print(f"Step 2: Uploading to {ip}...")
        with open(temp_path, 'rb') as f:
            files = {'file': ('current.mp3', f, 'audio/mpeg')}
            
            # TIMEOUT FIX: Increased to 120 seconds (2 minutes)
            try:
                r = requests.post(f"http://{ip}/upload", files=files, timeout=120)
                if r.status_code == 200:
                    print("DEBUG: Upload Success!")
                else:
                    print(f"ERROR: Upload failed (Code {r.status_code})")
                    return
            except requests.exceptions.Timeout:
                print("ERROR: Timed out! The ESP is writing too slowly.")
                return

        # 3. PLAY
        print("Step 3: Playing...")
        requests.get(f"http://{ip}/play", timeout=5)
        print("SUCCESS! Check Speaker.")

    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# --- WEB UI ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<body style="background:#222; color:white; text-align:center; padding:20px; font-family:sans-serif;">
    <h1>📢 Turbo Uploader</h1>
    <form action="/play_manual" method="post" style="max-width:400px; margin:auto; background:#333; padding:20px;">
        <label>ESP IP:</label><br>
        <input type="text" name="manual_ip" value="192.168.0.244" style="width:100%; padding:10px;"><br><br>
        <label>Horn:</label><br>
        <select name="filename" style="width:100%; padding:10px;">
            {% for file in files %}
                <option value="{{ file }}">{{ file }}</option>
            {% endfor %}
        </select><br><br>
        <button type="submit" style="width:100%; padding:15px; background:#28a745; color:white; border:none; font-weight:bold;">▶ UPLOAD & PLAY</button>
    </form>
</body>
</html>
"""

@app.route('/')
def index():
    if not os.path.exists(HORNS_DIR): os.makedirs(HORNS_DIR)
    files = [f for f in os.listdir(HORNS_DIR) if f.endswith('.mp3')]
    return render_template_string(HTML_TEMPLATE, files=files)

@app.route('/play_manual', methods=['POST'])
def play_manual():
    ip = request.form.get('manual_ip')
    filename = request.form.get('filename')
    if ip and filename:
        threading.Thread(target=upload_and_play, args=(ip, filename)).start()
    return "Processing... Check Terminal."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)