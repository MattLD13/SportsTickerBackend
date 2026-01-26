#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <LittleFS.h>
#include <FastLED.h>
#include "Audio.h" // Library: "ESP32-audioI2S" by Schreibfaul1

// --- PINS (XIAO ESP32S3) ---
#define LED_PIN     0       // D0
#define I2S_BCLK    1       // D1
#define I2S_LRC     2       // D2
#define I2S_DOUT    3       // D3

// --- LED CONFIG ---
#define NUM_LEDS    60
#define LED_TYPE    WS2812B
#define COLOR_ORDER GRB
CRGB leds[NUM_LEDS];

// --- OBJECTS ---
WebServer server(80);
Audio audio;

// --- STATE VARIABLES ---
volatile bool isPlaying = false; // "volatile" because it's shared between cores
int currentVolume = 21;          // ESP32 Audio Lib uses 0-21 range

// --- MULTI-TASKING ---
TaskHandle_t Task1;

// --- HTML PAGE ---
const char* htmlPage = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: sans-serif; background: #1a1a1a; color: #fff; text-align: center; padding: 20px; }
    .card { background: #2d2d2d; padding: 20px; border-radius: 12px; margin: 0 auto; max-width: 400px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
    input[type=range] { width: 100%; margin: 20px 0; height: 30px; accent-color: #e50914; }
    button { background: #e50914; color: white; border: none; padding: 15px; font-size: 18px; border-radius: 8px; width: 100%; margin-top: 10px; cursor: pointer; font-weight: bold;}
    button:active { transform: scale(0.98); }
    .vol { font-size: 24px; font-weight: bold; color: #e50914; }
  </style>
</head>
<body>
  <div class="card">
    <h1>🚨 ESP32-S3 Horn</h1>
    <p>Volume: <span id="volText" class="vol">100%</span></p>
    <input type="range" min="0" max="21" value="21" oninput="upd(this.value)" onchange="set(this.value)">
    <button onclick="stop()">⏹ EMERGENCY STOP</button>
  </div>
<script>
  function upd(v) { document.getElementById('volText').innerText = Math.round((v/21)*100) + "%"; }
  function set(v) { fetch('/set_volume?val=' + v); }
  function stop() { fetch('/stop'); }
</script>
</body>
</html>
)rawliteral";

// --- CORE 0: LED ANIMATION TASK ---
// This runs independently of the Audio/WiFi (which run on Core 1)
void ledTask(void * parameter) {
  // Setup FastLED on Core 0
  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS);
  FastLED.setBrightness(150);
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();

  for(;;) { // Infinite Loop
    if (isPlaying) {
      // --- ROTATING BEACON PATTERN ---
      fadeToBlackBy(leds, NUM_LEDS, 50); // Create trails
      
      int numBeams = 5;
      // Faster rotation speed because ESP32 is powerful
      int rotationPos = (millis() / 25) % NUM_LEDS; 
      
      for (int i = 0; i < numBeams; i++) {
        int beamStart = (rotationPos + (i * (NUM_LEDS / numBeams))) % NUM_LEDS;
        for (int w = 0; w < 6; w++) { // Beam width
          int pixelPos = (beamStart + w) % NUM_LEDS;
          // Red with sparkle
          leds[pixelPos] = CHSV(0, 255, random(200, 255)); 
        }
      }
      FastLED.show();
      // Wait 15ms (~60 FPS). No crackling because we are on a separate core!
      vTaskDelay(15 / portTICK_PERIOD_MS); 
    } else {
      // Idle State: Turn off
      fill_solid(leds, NUM_LEDS, CRGB::Black);
      FastLED.show();
      vTaskDelay(100 / portTICK_PERIOD_MS);
    }
  }
}

// --- HANDLERS ---

void handleUpload() {
  HTTPUpload& upload = server.upload();
  
  if (upload.status == UPLOAD_FILE_START) {
    Serial.println("Upload Start...");
    isPlaying = false; // Stops LED animation immediately
    audio.stopSong();  // Release Audio Buffer
    
    if (LittleFS.exists("/current.mp3")) LittleFS.remove("/current.mp3");
    File f = LittleFS.open("/current.mp3", "w");
    if(f) f.close();
  } 
  else if (upload.status == UPLOAD_FILE_WRITE) {
    File f = LittleFS.open("/current.mp3", "a");
    if (f) {
      f.write(upload.buf, upload.currentSize);
      f.close();
    }
  } 
  else if (upload.status == UPLOAD_FILE_END) {
    Serial.println("Upload Done");
    server.send(200, "text/plain", "OK");
  }
}

void handlePlay() {
  if (!LittleFS.exists("/current.mp3")) {
    server.send(404, "text/plain", "No File");
    return;
  }
  
  // Start Playback
  audio.connecttoFS(LittleFS, "/current.mp3");
  isPlaying = true; // Wake up LED task
  server.send(200, "text/plain", "Playing");
}

void handleStop() {
  audio.stopSong();
  isPlaying = false; // Sleep LED task
  server.send(200, "text/plain", "Stopped");
}

void setup() {
  Serial.begin(115200);
  
  // Add this delay! 
  // It gives the computer time to "catch" the USB connection before printing starts.
  delay(2000);

  if(!LittleFS.begin(true)){ Serial.println("LittleFS Failed"); return; }

  // 1. WiFi Manager (or Hardcoded)
  // Replace with WiFiManager logic if you prefer, or hardcode for speed:
  WiFi.begin("YOUR_WIFI_NAME", "YOUR_WIFI_PASSWORD"); 
  while (WiFi.status() != WL_CONNECTED) {
    delay(500); Serial.print(".");
  }
  Serial.println("\nIP: " + WiFi.localIP().toString());

  // 2. Audio Setup (I2S)
  audio.setPinout(I2S_BCLK, I2S_LRC, I2S_DOUT);
  audio.setVolume(currentVolume); 

  // 3. Launch LED Task on CORE 0
  // xTaskCreatePinnedToCore(function, name, stack_size, params, priority, handle, core_id)
  xTaskCreatePinnedToCore(
    ledTask,   "LED_Task",  4096,      NULL,   1,        &Task1,  0 
  );

  // 4. Server Routes
  server.on("/", [](){ server.send(200, "text/html", htmlPage); });
  server.on("/set_volume", [](){ 
    if(server.hasArg("val")) {
      currentVolume = server.arg("val").toInt();
      audio.setVolume(currentVolume);
      server.send(200, "text/plain", "OK");
    }
  });
  server.on("/stop", handleStop);
  server.on("/upload", HTTP_POST, [](){ server.send(200); }, handleUpload);
  server.on("/play", handlePlay);
  
  server.begin();
}

void loop() {
  // Core 1 handles these heavy lifting tasks:
  server.handleClient();
  audio.loop(); // Must be called frequently for audio to play

  // Auto-detect song end
  if (!audio.isRunning() && isPlaying) {
    isPlaying = false; // Turns off LEDs
  }
}