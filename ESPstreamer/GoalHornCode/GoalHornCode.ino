#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <LittleFS.h> 
#include <FastLED.h> 

#include "AudioFileSourceLittleFS.h"
#include "AudioGeneratorMP3.h"
#include "AudioOutputI2S.h"
#include <WiFiManager.h>

// --- CONFIGURATION ---
// IMPORTANT: Data wire MUST be on D5 (GPIO 14) 
#define LED_PIN     14      
#define NUM_LEDS    60      // Change to your LED count
#define LED_TYPE    WS2812B
#define COLOR_ORDER GRB     

CRGB leds[NUM_LEDS];

ESP8266WebServer server(80);

// Audio Pointers
AudioGeneratorMP3 *mp3 = NULL;
AudioFileSourceLittleFS *file = NULL;
AudioOutputI2S *out = NULL;
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
    <h1>📢 Horn Control</h1>
    <p>Volume: <span id="volText" class="vol">100%</span></p>
    <input type="range" min="0" max="150" value="100" oninput="upd(this.value)" onchange="set(this.value)">
    <button onclick="stop()">⏹ EMERGENCY STOP</button>
  </div>
<script>
  function upd(v) { document.getElementById('volText').innerText = v + "%"; }
  function set(v) { fetch('/set_volume?val=' + (v/100.0)); }
  function stop() { fetch('/stop'); }
</script>
</body>
</html>
)rawliteral";

// --- LED EFFECT ---
void drawRotatingBeacon() {
  fadeToBlackBy(leds, NUM_LEDS, 60);

  int numBeams = 5;
  int beamWidth = 6;
  // Speed control: Lower '30' = Faster spin
  int rotationPos = (millis() / 30) % NUM_LEDS; 

  for (int i = 0; i < numBeams; i++) {
    int beamStart = (rotationPos + (i * (NUM_LEDS / numBeams))) % NUM_LEDS;
    for (int w = 0; w < beamWidth; w++) {
      int pixelPos = (beamStart + w) % NUM_LEDS;
      leds[pixelPos] = CHSV(0, 255, random(180, 255)); 
    }
  }
  
  // CRITICAL: Yield to allow audio buffer to refill
  yield(); 
  FastLED.show();
  yield();
}

// --- HANDLERS ---

void handleUpload() {
  HTTPUpload& upload = server.upload();
  
  if (upload.status == UPLOAD_FILE_START) {
    Serial.println("Upload Start: Stopping Audio Hardware...");
    
    // 1. HARD STOP EVERYTHING to prevent Flash/Audio conflict
    isPlaying = false;
    
    // Delete MP3 Decoder
    if (mp3) { mp3->stop(); delete mp3; mp3 = NULL; }
    // Delete File Handle
    if (file) { file->close(); delete file; file = NULL; }
    // CRITICAL: Delete Output Driver (Stops Interrupts)
    if (out) { delete out; out = NULL; }
    
    // Reset LEDs
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    FastLED.show();
    
    // Open file for writing
    if (LittleFS.exists("/current.mp3")) LittleFS.remove("/current.mp3");
    uploadFile = LittleFS.open("/current.mp3", "w");
  } 
  else if (upload.status == UPLOAD_FILE_WRITE) {
    if (uploadFile) uploadFile.write(upload.buf, upload.currentSize);
    yield(); // Prevent Watchdog Timer crash
  } 
  else if (upload.status == UPLOAD_FILE_END) {
    if (uploadFile) uploadFile.close();
    Serial.println("Upload Complete");
    server.send(200, "text/plain", "OK");
  }
}

void handlePlay() {
  // 1. Cleanup old objects
  if (mp3) { delete mp3; mp3 = NULL; }
  if (file) { delete file; file = NULL; }
  
  if (!LittleFS.exists("/current.mp3")) {
    server.send(404, "text/plain", "No File");
    return;
  }

  // 2. WAKE UP AUDIO HARDWARE
  if (!out) {
    out = new AudioOutputI2S();
    out->begin();
    delay(50); // Give the I2S bus a moment to stabilize
  }
  
  // Force Volume Set (Important!)
  out->SetGain(currentVolume > 0.1 ? currentVolume : 1.0); 

  file = new AudioFileSourceLittleFS("/current.mp3");
  mp3 = new AudioGeneratorMP3();
  
  // 3. START PLAYBACK
  if (mp3->begin(file, out)) {
    isPlaying = true;
    server.send(200, "text/plain", "Playing");
    Serial.println("Playback Started!");
  } else {
    server.send(500, "text/plain", "MP3 Decode Error");
    Serial.println("MP3 Begin Failed");
  }
}

void handleStop() {
  if (mp3 && mp3->isRunning()) mp3->stop();
  isPlaying = false;
  
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();
  
  if (LittleFS.exists("/current.mp3")) LittleFS.remove("/current.mp3");
  server.send(200, "text/plain", "Stopped");
}

void setup() {
  Serial.begin(115200);

  // LED Init
  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS);
  FastLED.setBrightness(100); 
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();
  
  // Filesystem Init
  if (!LittleFS.begin()) { LittleFS.format(); LittleFS.begin(); }

  // WiFi Init
  WiFi.setSleepMode(WIFI_NONE_SLEEP);
  WiFiManager wifiManager;
  if (!wifiManager.autoConnect("ESP-Horn-Setup")) ESP.restart();
  Serial.println("\nIP: " + WiFi.localIP().toString());

  // Audio Init (Startup only)
  out = new AudioOutputI2S();
  out->begin();

  // Web Server Routes
  server.on("/", [](){ server.send(200, "text/html", htmlPage); });
  server.on("/set_volume", [](){ 
    if(server.hasArg("val")) {
      currentVolume = server.arg("val").toFloat();
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
        // --- Song Finished ---
        mp3->stop(); 
        isPlaying = false;
        
        // LEDs OFF
        fill_solid(leds, NUM_LEDS, CRGB::Black);
        FastLED.show();
        
        // Cleanup Memory
        delete mp3; mp3 = NULL;
        delete file; file = NULL;
        LittleFS.remove("/current.mp3");
        
      } else {
        // --- Animation Loop ---
        // Updates every 50ms (20 FPS) to minimize crackling
        static unsigned long lastUpdate = 0;
        if (millis() - lastUpdate > 50) {
          lastUpdate = millis();
          drawRotatingBeacon();
        }
      }
    } else {
      isPlaying = false;
    }
  }
}