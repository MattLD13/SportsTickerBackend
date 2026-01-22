#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <LittleFS.h> 

#include "AudioFileSourceLittleFS.h"
#include "AudioGeneratorMP3.h"
#include "AudioOutputI2S.h"
#include <WiFiManager.h>

ESP8266WebServer server(80);

AudioGeneratorMP3 *mp3;
AudioFileSourceLittleFS *file;
AudioOutputI2S *out;
File uploadFile; 

bool isPlaying = false;
float currentVolume = 1.0; 

// --- HTML PAGE ---
const char* htmlPage = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: sans-serif; background: #222; color: #fff; text-align: center; padding: 20px; }
    .card { background: #333; padding: 20px; border-radius: 12px; margin: 0 auto; max-width: 400px; }
    input[type=range] { width: 100%; margin: 20px 0; height: 30px; }
    button { background: #d9534f; color: white; border: none; padding: 15px; font-size: 18px; border-radius: 8px; width: 100%; margin-top: 10px;}
    .vol { font-size: 24px; font-weight: bold; color: #00bc8c; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Horn Control</h1>
    <p>Volume: <span id="volText" class="vol">100%</span></p>
    <input type="range" min="0" max="150" value="100" oninput="upd(this.value)" onchange="set(this.value)">
    <button onclick="stop()">EMERGENCY STOP</button>
  </div>
<script>
  function upd(v) { document.getElementById('volText').innerText = v + "%"; }
  function set(v) { fetch('/set_volume?val=' + (v/100.0)); }
  function stop() { fetch('/stop'); }
</script>
</body>
</html>
)rawliteral";

// --- HANDLERS ---

void handleUpload() {
  HTTPUpload& upload = server.upload();
  
  if (upload.status == UPLOAD_FILE_START) {
    // 1. KILL AUDIO to save power
    if (mp3 && mp3->isRunning()) mp3->stop();
    // We don't delete 'out' here to avoid null pointer crashes, 
    // but we stop it to save the Brownout crash.
    if (out) out->stop(); 
    
    uploadFile = LittleFS.open("/current.mp3", "w");
  } 
  else if (upload.status == UPLOAD_FILE_WRITE) {
    if (uploadFile) uploadFile.write(upload.buf, upload.currentSize);
    yield(); // Prevent Watchdog Crash
  } 
  else if (upload.status == UPLOAD_FILE_END) {
    if (uploadFile) uploadFile.close();
    server.send(200, "text/plain", "OK");
  }
}

void handlePlay() {
  // 1. DELETE OLD OBJECTS (The Fix)
  // We destroy the old audio driver to ensure the new one starts fresh.
  if (mp3) { delete mp3; mp3 = NULL; }
  if (file) { delete file; file = NULL; }
  if (out) { delete out; out = NULL; }

  if (!LittleFS.exists("/current.mp3")) {
    server.send(404, "text/plain", "No File");
    return;
  }

  // 2. CREATE NEW OBJECTS
  file = new AudioFileSourceLittleFS("/current.mp3");
  out = new AudioOutputI2S(); // Create fresh driver
  out->begin();               // Start it up
  out->SetGain(currentVolume); // Apply Volume immediately
  
  mp3 = new AudioGeneratorMP3();
  
  if (mp3->begin(file, out)) {
    isPlaying = true;
    server.send(200, "text/plain", "Playing");
  } else {
    server.send(500, "text/plain", "Error");
  }
}

void handleStop() {
  if (mp3 && mp3->isRunning()) mp3->stop();
  isPlaying = false;
  if (LittleFS.exists("/current.mp3")) LittleFS.remove("/current.mp3");
  server.send(200, "text/plain", "Stopped");
}

void setup() {
  Serial.begin(115200);
  
  // Filesystem
  if (!LittleFS.begin()) { LittleFS.format(); LittleFS.begin(); }

  // WiFi
  WiFi.setSleepMode(WIFI_NONE_SLEEP);
  WiFiManager wifiManager;
  if (!wifiManager.autoConnect("ESP-Horn-Setup")) ESP.restart();
  Serial.println("\nIP: " + WiFi.localIP().toString());

  // Audio Init (Just for startup)
  out = new AudioOutputI2S();
  out->begin();

  // Routes
  server.on("/", [](){ server.send(200, "text/html", htmlPage); });
  server.on("/set_volume", [](){ 
    if(server.hasArg("val")) {
      currentVolume = server.arg("val").toFloat();
      // Only apply to hardware if it exists
      if(out) out->SetGain(currentVolume);
      server.send(200, "text/plain", "OK");
    }
  });
  server.on("/stop", handleStop);
  server.on("/upload", HTTP_POST, [](){ server.send(200); }, handleUpload);
  server.on("/play", handlePlay);
  
  server.begin();
}

void loop() {
  server.handleClient();

  if (isPlaying && mp3) {
    if (mp3->isRunning()) {
      if (!mp3->loop()) { 
        mp3->stop(); 
        isPlaying = false;
        // Cleanup
        delete mp3; mp3 = NULL;
        delete file; file = NULL;
        LittleFS.remove("/current.mp3");
      }
    } else {
      isPlaying = false;
    }
  }
}