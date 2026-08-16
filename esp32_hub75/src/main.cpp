#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include <HTTPClient.h>
#include <JPEGDEC.h>
#include <LittleFS.h>
#undef INTELSHORT
#undef INTELLONG
#undef MOTOSHORT
#undef MOTOLONG
#include <PNGdec.h>
#include <WiFi.h>

// Set these network values before flashing the ESP32.
static const char* WIFI_SSID = "Rem 6";
static const char* WIFI_PASSWORD = "11Raspberry";
static const char* BACKEND_URL = "https://ticker.mattdicks.org";
static const char* DEVICE_NAME = "MiniTicker";

// This map targets the pictured ESP32-S3 board and one 64x32, 1/16-scan HUB75 panel.
static constexpr int R1_PIN = 4;
static constexpr int G1_PIN = 6;
static constexpr int B1_PIN = 5;
static constexpr int R2_PIN = 7;
static constexpr int G2_PIN = 16;
static constexpr int B2_PIN = 15;
static constexpr int A_PIN = 10;
static constexpr int B_PIN = 11;
static constexpr int C_PIN = 12;
static constexpr int D_PIN = 13;
static constexpr int E_PIN = -1;
static constexpr int LAT_PIN = 18;
static constexpr int OE_PIN = 8;
static constexpr int CLK_PIN = 17;

static constexpr uint32_t FETCH_INTERVAL_MS = 5000;
static constexpr uint32_t HEARTBEAT_INTERVAL_MS = 30000;
static constexpr uint32_t REGISTER_INTERVAL_MS = 10000;
static constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 10000;
static constexpr uint32_t MESSAGE_REFRESH_MS = 1000;
static constexpr uint8_t PANEL_BRIGHTNESS = 96;
// Temporary hardware test. Set false to restore the ticker loop below.
static constexpr bool SOLID_COLOR_TEST = false;
static constexpr uint32_t SOLID_COLOR_INTERVAL_MS = 1500;

MatrixPanel_I2S_DMA* matrix = nullptr;
PNG pngDecoder;
JPEGDEC jpegDecoder;
JsonDocument payload;
uint32_t payloadSignature = 0;
uint32_t lastFetchAt = 0;
uint32_t lastHeartbeatAt = 0;
uint32_t lastRegisterAt = 0;
uint32_t lastPageAt = 0;
uint32_t lastMessageAt = 0;
uint16_t pageIndex = 0;
uint16_t pageCount = 0;
float pageHoldSeconds = 3.0f;
String message = "STARTING";
uint8_t solidColorIndex = 0;
uint32_t lastSolidColorAt = 0;
String tickerId;
String dataUrl;
String heartbeatUrl;
String pairingCode;
bool pairingMode = false;
bool sportsMode = true;
bool registered = false;
bool wifiStarted = false;

static constexpr uint8_t RUNTIME_LOGO_SIZE = 14;
static constexpr uint8_t RUNTIME_LOGO_SLOTS = 8;
static constexpr uint16_t FLASH_LOGO_CACHE_SLOTS = 256;
static constexpr uint8_t FLASH_LOGO_PROBE_LIMIT = 8;
static constexpr size_t LOGO_DOWNLOAD_LIMIT = 64 * 1024;
static constexpr uint16_t LOGO_DECODE_WIDTH_LIMIT = 1024;
static constexpr char LOGO_CACHE_FILE[] = "/logo_cache_v2.bin";

struct RuntimeLogo {
  String url;
  uint16_t pixels[RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE] = {};
  uint8_t mask[RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE] = {};
  bool valid = false;
};

struct PersistedLogo {
  uint32_t urlHash;
  char url[192];
  uint16_t pixels[RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE];
  uint8_t mask[RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE];
};

RuntimeLogo runtimeLogos[RUNTIME_LOGO_SLOTS];
uint8_t* logoDownloadBuffer = nullptr;
size_t logoDownloadCapacity = 0;
uint16_t logoDecodeLine[LOGO_DECODE_WIDTH_LIMIT];
uint8_t logoDecodeMask[(LOGO_DECODE_WIDTH_LIMIT + 7) / 8];
RuntimeLogo* activeLogoDecode = nullptr;
int activeLogoWidth = 0;
int activeLogoHeight = 0;
int activeLogoScaledWidth = 0;
int activeLogoScaledHeight = 0;
int activeLogoOffsetX = 0;
int activeLogoOffsetY = 0;
bool logoCacheReady = false;

void renderCurrent();

void showFetchError(const String& value) {
  String displayValue = value;
  if (displayValue.startsWith("REGISTER ")) {
    displayValue = "REG " + displayValue.substring(9);
  }
  if (displayValue.startsWith("REGISTER")) {
    displayValue = "REG" + displayValue.substring(8);
  }
  if (pageCount == 0) {
    message = displayValue;
    return;
  }
  // Keep the last valid sports page visible while the backend is unavailable.
  message = "";
  renderCurrent();
}

uint32_t hashBody(const String& body) {
  uint32_t hash = 2166136261u;
  for (size_t index = 0; index < body.length(); ++index) {
    hash ^= static_cast<uint8_t>(body[index]);
    hash *= 16777619u;
  }
  return hash;
}

String localDeviceId() {
  const uint64_t mac = ESP.getEfuseMac();
  String high = String(static_cast<uint32_t>(mac >> 32), HEX);
  String low = String(static_cast<uint32_t>(mac), HEX);
  while (high.length() < 4) high = "0" + high;
  while (low.length() < 8) low = "0" + low;
  high.toUpperCase();
  low.toUpperCase();
  return "esp32s3-" + high + low;
}

String backendEndpoint(const String& suffix) {
  String base = BACKEND_URL;
  while (base.endsWith("/")) {
    base.remove(base.length() - 1);
  }
  return base + suffix;
}

bool registerDevice() {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }

  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (!http.begin(backendEndpoint("/api/v2/devices/register"))) {
    showFetchError("REGISTER SETUP");
    return false;
  }

  JsonDocument request;
  request["device_id"] = localDeviceId();
  request["name"] = DEVICE_NAME;
  request["profile"]["product_family"] = "mini";
  request["profile"]["hardware"] = "esp32-s3";
  request["profile"]["firmware"] = "mini-1.0.0";
  request["profile"]["display"]["width"] = 64;
  request["profile"]["display"]["height"] = 32;
  request["profile"]["display"]["panel_count"] = 1;
  request["profile"]["capabilities"]["modes"][0] = "sports";
  request["profile"]["capabilities"]["asset_cache"] = false;
  request["profile"]["capabilities"]["ota"] = true;
  request["profile"]["capabilities"]["color_depth"] = 16;
  request["metadata"]["build"] = "esp32s3-hub75";
  request["metadata"]["mode"] = "sports";
  request["metadata"]["capabilities"][0] = "sports";
  String body;
  serializeJson(request, body);
  http.addHeader("Content-Type", "application/json");
  int status = http.POST(body);
  Serial.print("Register HTTP status: ");
  Serial.println(status);
  if (status != HTTP_CODE_OK && status != HTTP_CODE_CREATED) {
    showFetchError("REGISTER " + String(status));
    http.end();
    return false;
  }

  String responseBody = http.getString();
  http.end();
  JsonDocument response;
  if (deserializeJson(response, responseBody)) {
    showFetchError("REGISTER JSON");
    return false;
  }

  String nextTickerId = response["ticker_id"] | "";
  nextTickerId.trim();
  if (nextTickerId.length() == 0) {
    showFetchError("REGISTER ID");
    return false;
  }

  tickerId = nextTickerId;
  dataUrl = backendEndpoint("/api/v2/tickers/") + tickerId + "/data";
  heartbeatUrl = backendEndpoint("/api/v2/tickers/") + tickerId + "/heartbeat";
  pairingMode = !(response["paired"] | false);
  pairingCode = response["pairing_code"] | "";
  registered = true;
  pageCount = 0;
  message = "";
  renderCurrent();
  return true;
}

uint16_t color(uint8_t red, uint8_t green, uint8_t blue) {
  return matrix->color565(red, green, blue);
}

void drawText(const String& value, int16_t x, int16_t y, uint16_t foreground) {
  matrix->setTextColor(foreground);
  matrix->setCursor(x, y);
  matrix->print(value);
}

void drawTextFit(const String& value, int16_t x, int16_t y, uint16_t foreground, int16_t width) {
  String clipped = value;
  const size_t maxCharacters = width > 0 ? static_cast<size_t>(width / 6) : 0;
  if (clipped.length() > maxCharacters) {
    clipped.remove(maxCharacters);
  }
  drawText(clipped, x, y, foreground);
}

void drawTextRight(const String& value, int16_t right, int16_t y, uint16_t foreground, int16_t left) {
  String clipped = value;
  const int16_t width = right - left;
  const size_t maxCharacters = width > 0 ? static_cast<size_t>(width / 6) : 0;
  if (clipped.length() > maxCharacters) {
    clipped.remove(maxCharacters);
  }
  const int16_t x = right - static_cast<int16_t>(clipped.length() * 6);
  drawText(clipped, x, y, foreground);
}

void presentFrame() {
  matrix->flipDMABuffer();
}

String shortValue(JsonVariantConst value, const char* fallback, size_t limit) {
  String result = value.isNull() ? String(fallback) : value.as<String>();
  result.trim();
  result.toUpperCase();
  if (result.length() > limit) {
    result.remove(limit);
  }
  return result;
}

String sportName(JsonObjectConst game) {
  String sport = game["sport"] | game["league"] | "SPORTS";
  sport.trim();
  sport.toUpperCase();
  if (sport == "NFL") return "FOOTBALL";
  if (sport == "NHL") return "HOCKEY";
  if (sport == "MLB") return "BASEBALL";
  if (sport == "NBA") return "BASKETBALL";
  if (sport.length() == 0) return "SPORTS";
  if (sport.length() > 10) sport.remove(10);
  return sport;
}

bool shownItem(JsonObjectConst item) {
  return item["is_shown"].isNull() || item["is_shown"].as<bool>();
}

uint16_t countShownGames() {
  uint16_t count = 0;
  JsonObjectConst content = payload["content"].as<JsonObjectConst>();
  JsonArrayConst items = content["sports"].as<JsonArrayConst>();
  for (JsonObjectConst item : items) {
    if (shownItem(item)) {
      ++count;
    }
  }
  return count;
}

bool selectedGame(JsonObjectConst& selected) {
  uint16_t index = 0;
  JsonObjectConst content = payload["content"].as<JsonObjectConst>();
  JsonArrayConst items = content["sports"].as<JsonArrayConst>();
  for (JsonObjectConst item : items) {
    if (!shownItem(item)) {
      continue;
    }
    if (index == pageIndex) {
      selected = item["data"].as<JsonObjectConst>();
      return !selected.isNull();
    }
    ++index;
  }
  return false;
}

uint32_t pageHoldMillis(float scrollSpeed) {
  // The backend stores seconds per scroll pixel. On this panel, that value
  // controls page dwell. The default 0.03 value gives three seconds per page.
  if (!(scrollSpeed > 0.0f)) {
    scrollSpeed = 0.03f;
  }
  uint32_t dwell = static_cast<uint32_t>(scrollSpeed * 100000.0f);
  if (dwell < 1000) dwell = 1000;
  if (dwell > 10000) dwell = 10000;
  return dwell;
}

void drawMessage(const String& value) {
  matrix->fillScreen(0);
  matrix->drawFastHLine(0, 0, 64, color(30, 150, 220));
  drawTextFit(value, 2, 13, color(255, 220, 80), 60);
  presentFrame();
}

void drawSolidColorTest() {
  const uint16_t colors[] = {
    color(255, 0, 0),
    color(0, 255, 0),
    color(0, 0, 255),
    color(255, 255, 255),
    color(0, 0, 0),
  };
  matrix->fillScreen(colors[solidColorIndex]);
  presentFrame();
  Serial.print("Solid color test index: ");
  Serial.println(solidColorIndex);
  solidColorIndex = (solidColorIndex + 1) % (sizeof(colors) / sizeof(colors[0]));
}

void drawPairingCode() {
  matrix->fillScreen(0);
  matrix->drawFastHLine(0, 0, 64, color(30, 150, 220));
  drawTextFit("PAIR", 2, 3, color(40, 190, 230), 24);
  drawTextFit(pairingCode.length() > 0 ? pairingCode : "------", 8, 16, color(255, 220, 80), 54);
  presentFrame();
}

const char* pixelGlyph(char value) {
  switch (toupper(value)) {
    case '0': return "111101101101111";
    case '1': return "010110010010111";
    case '2': return "111001111100111";
    case '3': return "111001111001111";
    case '4': return "101101111001001";
    case '5': return "111100111001111";
    case '6': return "111100111101111";
    case '7': return "111001010010010";
    case '8': return "111101111101111";
    case '9': return "111101111001111";
    case 'A': return "010101111101101";
    case 'B': return "110101110101110";
    case 'C': return "011100100100011";
    case 'D': return "110101101101110";
    case 'E': return "111100110100111";
    case 'F': return "111100110100100";
    case 'G': return "011100101101011";
    case 'H': return "101101111101101";
    case 'I': return "111010010010111";
    case 'J': return "001001001101010";
    case 'K': return "101110100110101";
    case 'L': return "100100100100111";
    case 'M': return "101111101101101";
    case 'N': return "101111111111101";
    case 'O': return "010101101101010";
    case 'P': return "110101110100100";
    case 'Q': return "010101101111011";
    case 'R': return "110101110101101";
    case 'S': return "011100010001110";
    case 'T': return "111010010010010";
    case 'U': return "101101101101011";
    case 'V': return "101101101101010";
    case 'W': return "101101101111101";
    case 'X': return "101101010101101";
    case 'Y': return "101101010010010";
    case 'Z': return "111001010100111";
    case '&': return "010101010101011";
    case '-': return "000000111000000";
    case ':': return "000010000010000";
    case '/': return "001001010100100";
    case '.': return "000000000000010";
    default: return "000000000000000";
  }
}

void drawPixelText(const String& value, int16_t x, int16_t y, uint16_t foreground, uint8_t scale = 1) {
  int16_t cursor = x;
  for (size_t characterIndex = 0; characterIndex < value.length(); ++characterIndex) {
    const char* glyph = pixelGlyph(value[characterIndex]);
    for (uint8_t row = 0; row < 5; ++row) {
      for (uint8_t column = 0; column < 3; ++column) {
        if (glyph[row * 3 + column] == '1') {
          matrix->fillRect(cursor + column * scale, y + row * scale, scale, scale, foreground);
        }
      }
    }
    cursor += 4 * scale;
  }
}

void drawPixelTextFit(const String& value, int16_t x, int16_t y, uint16_t foreground, uint8_t scale, int16_t width) {
  String clipped = value;
  const size_t maximumCharacters = width > 0 ? static_cast<size_t>(width / (4 * scale)) : 0;
  if (clipped.length() > maximumCharacters) {
    clipped.remove(maximumCharacters);
  }
  drawPixelText(clipped, x, y, foreground, scale);
}

void drawPixelTextRight(const String& value, int16_t right, int16_t y, uint16_t foreground, uint8_t scale, int16_t left) {
  String clipped = value;
  const int16_t width = right - left;
  const size_t maximumCharacters = width > 0 ? static_cast<size_t>(width / (4 * scale)) : 0;
  if (clipped.length() > maximumCharacters) {
    clipped.remove(maximumCharacters);
  }
  const int16_t x = right - static_cast<int16_t>(clipped.length() * 4 * scale);
  drawPixelText(clipped, x, y, foreground, scale);
}

uint16_t teamColor(JsonVariantConst value, uint16_t fallback) {
  String raw = value | "";
  raw.trim();
  if (raw.startsWith("#")) raw.remove(0, 1);
  if (raw.length() != 6) return fallback;
  const uint32_t rgb = strtoul(raw.c_str(), nullptr, 16);
  return color((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF);
}

uint32_t logoUrlHash(const String& url) {
  return hashBody(url);
}

RuntimeLogo* freeRuntimeLogoSlot(uint32_t urlHash) {
  for (uint8_t index = 0; index < RUNTIME_LOGO_SLOTS; ++index) {
    if (!runtimeLogos[index].valid) {
      return &runtimeLogos[index];
    }
  }
  return &runtimeLogos[urlHash % RUNTIME_LOGO_SLOTS];
}

bool readPersistedLogo(uint16_t slot, PersistedLogo& record) {
  if (!LittleFS.exists(LOGO_CACHE_FILE)) {
    return false;
  }
  File file = LittleFS.open(LOGO_CACHE_FILE, "r");
  if (!file || file.size() < static_cast<size_t>(slot + 1) * sizeof(PersistedLogo)) {
    return false;
  }
  file.seek(static_cast<size_t>(slot) * sizeof(PersistedLogo));
  const size_t readCount = file.readBytes(reinterpret_cast<char*>(&record), sizeof(record));
  file.close();
  return readCount == sizeof(record);
}

int findPersistedLogoSlot(uint32_t urlHash, const String& url, bool allowEmpty) {
  const uint16_t start = urlHash % FLASH_LOGO_CACHE_SLOTS;
  PersistedLogo record = {};
  for (uint8_t attempt = 0; attempt < FLASH_LOGO_PROBE_LIMIT; ++attempt) {
    const uint16_t slot = (start + attempt) % FLASH_LOGO_CACHE_SLOTS;
    if (!readPersistedLogo(slot, record)) {
      return allowEmpty ? slot : -1;
    }
    if (record.urlHash == 0) {
      return allowEmpty ? slot : -1;
    }
    if (record.urlHash == urlHash && (url.length() >= sizeof(record.url) || strcmp(record.url, url.c_str()) == 0)) {
      return slot;
    }
  }
  return allowEmpty ? start : -1;
}

void persistLogo(const String& url, RuntimeLogo* logo) {
  if (!logoCacheReady || logo == nullptr || !logo->valid) {
    return;
  }
  PersistedLogo record = {};
  record.urlHash = logoUrlHash(url);
  url.substring(0, sizeof(record.url) - 1).toCharArray(record.url, sizeof(record.url));
  memcpy(record.pixels, logo->pixels, sizeof(record.pixels));
  memcpy(record.mask, logo->mask, sizeof(record.mask));
  int slot = findPersistedLogoSlot(record.urlHash, url, true);
  if (slot < 0) {
    slot = record.urlHash % FLASH_LOGO_CACHE_SLOTS;
  }
  File file = LittleFS.exists(LOGO_CACHE_FILE)
    ? LittleFS.open(LOGO_CACHE_FILE, "r+")
    : LittleFS.open(LOGO_CACHE_FILE, "w+");
  if (file) {
    file.seek(static_cast<size_t>(slot) * sizeof(PersistedLogo));
    file.write(reinterpret_cast<const uint8_t*>(&record), sizeof(record));
    file.close();
  }
}

RuntimeLogo* loadPersistedLogo(const String& url) {
  if (!logoCacheReady || url.length() == 0) {
    return nullptr;
  }
  const uint32_t wantedHash = logoUrlHash(url);
  const int slot = findPersistedLogoSlot(wantedHash, url, false);
  if (slot >= 0) {
    PersistedLogo record = {};
    if (readPersistedLogo(static_cast<uint16_t>(slot), record)) {
      RuntimeLogo* result = freeRuntimeLogoSlot(wantedHash);
      result->url = url;
      memcpy(result->pixels, record.pixels, sizeof(result->pixels));
      memcpy(result->mask, record.mask, sizeof(result->mask));
      result->valid = true;
      return result;
    }
  }
  return nullptr;
}

void releaseLogoDownloadBuffer() {
  if (logoDownloadBuffer != nullptr) {
    free(logoDownloadBuffer);
    logoDownloadBuffer = nullptr;
    logoDownloadCapacity = 0;
  }
}

bool downloadLogo(const String& url, size_t& length) {
  length = 0;
  if (WiFi.status() != WL_CONNECTED || url.length() == 0) {
    return false;
  }
  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(8000);
  if (!http.begin(url)) {
    return false;
  }
  const int status = http.GET();
  const int expected = http.getSize();
  if (status != HTTP_CODE_OK || (expected > static_cast<int>(LOGO_DOWNLOAD_LIMIT))) {
    http.end();
    return false;
  }

  logoDownloadCapacity = expected > 0 ? static_cast<size_t>(expected) : LOGO_DOWNLOAD_LIMIT;
  logoDownloadBuffer = static_cast<uint8_t*>(malloc(logoDownloadCapacity));
  if (logoDownloadBuffer == nullptr) {
    logoDownloadCapacity = 0;
    http.end();
    return false;
  }

  WiFiClient* stream = http.getStreamPtr();
  uint32_t lastDataAt = millis();
  while (length < logoDownloadCapacity) {
    const size_t available = stream->available();
    if (available > 0) {
      const size_t requested = min(available, logoDownloadCapacity - length);
      const size_t readCount = stream->readBytes(logoDownloadBuffer + length, requested);
      length += readCount;
      lastDataAt = millis();
      if (readCount == 0) {
        break;
      }
      continue;
    }
    if (expected >= 0 && length >= static_cast<size_t>(expected)) {
      break;
    }
    if (!http.connected() && stream->available() == 0) {
      break;
    }
    if (millis() - lastDataAt > 8000) {
      break;
    }
    delay(1);
  }
  http.end();
  const bool complete = length > 0 && (expected < 0 || length == static_cast<size_t>(expected));
  if (!complete) {
    releaseLogoDownloadBuffer();
  }
  return complete;
}

void prepareLogoDecode(RuntimeLogo* logo, int width, int height) {
  activeLogoDecode = logo;
  activeLogoWidth = max(1, width);
  activeLogoHeight = max(1, height);
  const float scale = min(
    static_cast<float>(RUNTIME_LOGO_SIZE) / activeLogoWidth,
    static_cast<float>(RUNTIME_LOGO_SIZE) / activeLogoHeight
  );
  activeLogoScaledWidth = max(1, static_cast<int>(activeLogoWidth * scale + 0.5f));
  activeLogoScaledHeight = max(1, static_cast<int>(activeLogoHeight * scale + 0.5f));
  activeLogoOffsetX = (RUNTIME_LOGO_SIZE - activeLogoScaledWidth) / 2;
  activeLogoOffsetY = (RUNTIME_LOGO_SIZE - activeLogoScaledHeight) / 2;
  memset(logo->pixels, 0, sizeof(logo->pixels));
  memset(logo->mask, 0, sizeof(logo->mask));
}

void storeDecodedLogoPixel(int sourceX, int sourceY, uint16_t pixel, bool opaque) {
  if (activeLogoDecode == nullptr || !opaque) {
    return;
  }
  const int targetX = activeLogoOffsetX + (sourceX * activeLogoScaledWidth) / activeLogoWidth;
  const int targetY = activeLogoOffsetY + (sourceY * activeLogoScaledHeight) / activeLogoHeight;
  if (targetX < 0 || targetX >= RUNTIME_LOGO_SIZE || targetY < 0 || targetY >= RUNTIME_LOGO_SIZE) {
    return;
  }
  const size_t index = static_cast<size_t>(targetY) * RUNTIME_LOGO_SIZE + targetX;
  activeLogoDecode->pixels[index] = pixel;
  activeLogoDecode->mask[index] = 1;
}

int pngLogoDraw(PNGDRAW* draw) {
  if (activeLogoDecode == nullptr || draw->iWidth > LOGO_DECODE_WIDTH_LIMIT) {
    return 0;
  }
  pngDecoder.getLineAsRGB565(draw, logoDecodeLine, PNG_RGB565_LITTLE_ENDIAN, 0xffffffff);
  const bool hasOpaque = pngDecoder.getAlphaMask(draw, logoDecodeMask, 8) != 0;
  if (!hasOpaque) {
    return 1;
  }
  for (int sourceX = 0; sourceX < draw->iWidth; ++sourceX) {
    const bool opaque = (logoDecodeMask[sourceX / 8] & (0x80 >> (sourceX % 8))) != 0;
    storeDecodedLogoPixel(sourceX, draw->y, logoDecodeLine[sourceX], opaque);
  }
  return 1;
}

int jpegLogoDraw(JPEGDRAW* draw) {
  if (activeLogoDecode == nullptr) {
    return 0;
  }
  for (int row = 0; row < draw->iHeight; ++row) {
    for (int column = 0; column < draw->iWidthUsed; ++column) {
      const size_t index = static_cast<size_t>(row) * draw->iWidth + column;
      storeDecodedLogoPixel(draw->x + column, draw->y + row, draw->pPixels[index], true);
    }
  }
  return 1;
}

bool decodePngLogo(RuntimeLogo* logo, size_t length) {
  const int result = pngDecoder.openRAM(logoDownloadBuffer, static_cast<int>(length), pngLogoDraw);
  if (result != PNG_SUCCESS) {
    return false;
  }
  prepareLogoDecode(logo, pngDecoder.getWidth(), pngDecoder.getHeight());
  const int decodeResult = pngDecoder.decode(nullptr, 0);
  pngDecoder.close();
  activeLogoDecode = nullptr;
  return decodeResult == PNG_SUCCESS;
}

bool decodeJpegLogo(RuntimeLogo* logo, size_t length) {
  if (jpegDecoder.openRAM(logoDownloadBuffer, static_cast<int>(length), jpegLogoDraw) == 0) {
    return false;
  }
  const int width = jpegDecoder.getWidth();
  const int height = jpegDecoder.getHeight();
  int options = 0;
  if (max(width, height) > RUNTIME_LOGO_SIZE * 8) {
    options = JPEG_SCALE_EIGHTH;
  } else if (max(width, height) > RUNTIME_LOGO_SIZE * 4) {
    options = JPEG_SCALE_QUARTER;
  } else if (max(width, height) > RUNTIME_LOGO_SIZE * 2) {
    options = JPEG_SCALE_HALF;
  }
  const int divisor = options == JPEG_SCALE_EIGHTH ? 8 : options == JPEG_SCALE_QUARTER ? 4 : options == JPEG_SCALE_HALF ? 2 : 1;
  jpegDecoder.setPixelType(RGB565_LITTLE_ENDIAN);
  prepareLogoDecode(logo, max(1, width / divisor), max(1, height / divisor));
  const int decodeResult = jpegDecoder.decode(0, 0, options);
  jpegDecoder.close();
  activeLogoDecode = nullptr;
  return decodeResult == 1;
}

bool decodeDownloadedLogo(RuntimeLogo* logo, size_t length) {
  if (length >= 8 && memcmp(logoDownloadBuffer, "\x89PNG\r\n\x1a\n", 8) == 0) {
    return decodePngLogo(logo, length);
  }
  if (length >= 2 && logoDownloadBuffer[0] == 0xff && logoDownloadBuffer[1] == 0xd8) {
    return decodeJpegLogo(logo, length);
  }
  return decodePngLogo(logo, length) || decodeJpegLogo(logo, length);
}

RuntimeLogo* ensureRuntimeLogo(const String& url) {
  if (url.length() == 0) {
    return nullptr;
  }
  for (uint8_t index = 0; index < RUNTIME_LOGO_SLOTS; ++index) {
    if (runtimeLogos[index].valid && runtimeLogos[index].url == url) {
      return &runtimeLogos[index];
    }
  }
  if (RuntimeLogo* persisted = loadPersistedLogo(url)) {
    return persisted;
  }

  size_t length = 0;
  RuntimeLogo decoded;
  if (!downloadLogo(url, length)) {
    releaseLogoDownloadBuffer();
    return nullptr;
  }
  const bool decodedOk = decodeDownloadedLogo(&decoded, length);
  releaseLogoDownloadBuffer();
  if (!decodedOk) {
    return nullptr;
  }
  RuntimeLogo* result = freeRuntimeLogoSlot(logoUrlHash(url));
  result->url = url;
  memcpy(result->pixels, decoded.pixels, sizeof(result->pixels));
  memcpy(result->mask, decoded.mask, sizeof(result->mask));
  result->valid = true;
  persistLogo(url, result);
  Serial.print("Logo cached: ");
  Serial.println(url);
  return result;
}

void setupLogoCache() {
  logoCacheReady = LittleFS.begin(true);
}

void drawFallbackLogo(const String& abbreviation, int16_t x, int16_t y, uint16_t background) {
  const uint8_t red = ((background >> 11) & 0x1F) * 255 / 31;
  const uint8_t green = ((background >> 5) & 0x3F) * 255 / 63;
  const uint8_t blue = (background & 0x1F) * 255 / 31;
  const uint16_t foreground = (red * 299 + green * 587 + blue * 114) > 145000
    ? color(0, 0, 0)
    : color(255, 255, 255);
  String mark = abbreviation;
  if (mark.length() > 3) {
    mark.remove(3);
  }
  const int16_t textWidth = static_cast<int16_t>(mark.length() * 4);
  matrix->fillRoundRect(x, y, 14, 14, 2, background);
  matrix->drawRoundRect(x, y, 14, 14, 2, color(255, 255, 255));
  drawPixelText(mark, x + (14 - textWidth) / 2, y + 4, foreground, 1);
}

void drawRuntimeLogo(const RuntimeLogo* logo, int16_t x, int16_t y) {
  if (logo == nullptr || !logo->valid) {
    return;
  }
  for (uint8_t row = 0; row < RUNTIME_LOGO_SIZE; ++row) {
    for (uint8_t column = 0; column < RUNTIME_LOGO_SIZE; ++column) {
      const size_t index = static_cast<size_t>(row) * RUNTIME_LOGO_SIZE + column;
      if (logo->mask[index] != 0) {
        matrix->drawPixel(x + column, y + row, logo->pixels[index]);
      }
    }
  }
}

void drawLogo(const String& url, const String& abbreviation, int16_t x, int16_t y, uint16_t fallback) {
  if (RuntimeLogo* logo = ensureRuntimeLogo(url)) {
    drawRuntimeLogo(logo, x, y);
    return;
  }
  drawFallbackLogo(abbreviation, x, y, fallback);
}

void drawFootballPossessionIndicator(int16_t x, int16_t y, uint16_t teamColor) {
  const uint16_t leather = color(165, 78, 25);
  const uint16_t laces = color(255, 240, 190);
  matrix->fillRoundRect(x, y, 9, 6, 2, color(12, 16, 28));
  matrix->drawRoundRect(x, y, 9, 6, 2, teamColor);
  matrix->fillRoundRect(x + 2, y + 1, 5, 4, 2, leather);
  matrix->drawFastVLine(x + 4, y + 1, 4, laces);
  matrix->drawPixel(x + 3, y + 2, laces);
  matrix->drawPixel(x + 5, y + 2, laces);
  matrix->drawPixel(x + 3, y + 3, laces);
  matrix->drawPixel(x + 5, y + 3, laces);
}

void drawScoreCenter(const String& awayScore, const String& homeScore) {
  String score = awayScore + "-" + homeScore;
  uint8_t scale = score.length() <= 4 ? 2 : 1;
  int16_t width = static_cast<int16_t>(score.length() * 4 * scale);
  int16_t x = (64 - width) / 2;
  drawPixelText(score, x, scale == 2 ? 9 : 12, color(255, 255, 255), scale);
}

bool sportIs(const String& sport, const char* value) {
  return sport == value;
}

void drawBaseballIndicators(JsonObjectConst situation) {
  const uint16_t ballColor = color(70, 210, 80);
  const uint16_t strikeColor = color(255, 150, 35);
  const uint16_t outColor = color(220, 65, 65);
  const uint16_t offColor = color(45, 45, 55);
  const int balls = min(3, static_cast<int>(situation["balls"] | 0));
  const int strikes = min(2, static_cast<int>(situation["strikes"] | 0));
  const int outs = min(3, static_cast<int>(situation["outs"] | 0));
  for (int index = 0; index < 3; ++index) {
    matrix->fillCircle(18 + index * 4, 27, 1, index < balls ? ballColor : offColor);
  }
  for (int index = 0; index < 2; ++index) {
    matrix->fillCircle(31 + index * 4, 27, 1, index < strikes ? strikeColor : offColor);
  }
  for (int index = 0; index < 3; ++index) {
    matrix->fillCircle(41 + index * 4, 27, 1, index < outs ? outColor : offColor);
  }

  const uint16_t baseColor = color(255, 200, 55);
  const uint16_t baseOff = color(45, 45, 55);
  const int baseX = 56;
  const bool onFirst = situation["onFirst"] | false;
  const bool onSecond = situation["onSecond"] | false;
  const bool onThird = situation["onThird"] | false;
  matrix->fillRect(baseX - 1, 25, 3, 3, onSecond ? baseColor : baseOff);
  matrix->fillRect(baseX - 5, 28, 3, 3, onThird ? baseColor : baseOff);
  matrix->fillRect(baseX + 3, 28, 3, 3, onFirst ? baseColor : baseOff);
}

void drawHockeyIndicators(JsonObjectConst situation, const String& away, const String& home) {
  const bool powerPlay = situation["powerPlay"] | false;
  const bool emptyNet = situation["emptyNet"] | false;
  if (!powerPlay && !emptyNet) {
    return;
  }
  String label = emptyNet ? "EN" : "PP";
  String side = situation["emptyNetSide"] | "";
  if (side.length() == 0) {
    side = situation["activeTeam"] | "";
  }
  side.toUpperCase();
  const bool homeSide = side == home || side == "HOME" || side == "H";
  const int16_t x = homeSide ? 50 : 2;
  drawPixelText(label, x, 1, emptyNet ? color(255, 90, 90) : color(255, 220, 70), 1);
}

void drawSoccerIndicators(JsonObjectConst situation) {
  JsonArrayConst redCards = situation["red_cards"].as<JsonArrayConst>();
  uint8_t awayCards = 0;
  uint8_t homeCards = 0;
  for (JsonObjectConst card : redCards) {
    if (card["is_home"] | false) {
      ++homeCards;
    } else {
      ++awayCards;
    }
  }
  if (awayCards > 0) {
    matrix->fillRect(16, 1, 3, 5, color(220, 35, 45));
  }
  if (homeCards > 0) {
    matrix->fillRect(45, 1, 3, 5, color(220, 35, 45));
  }
}

void drawGame(JsonObjectConst game) {
  const uint16_t cyan = color(35, 190, 235);
  const uint16_t navy = color(0, 0, 0);
  const uint16_t muted = color(55, 76, 130);
  const uint16_t red = color(220, 45, 60);
  const uint16_t awayColor = teamColor(game["away_color"], color(255, 130, 40));
  const uint16_t homeColor = teamColor(game["home_color"], color(70, 155, 255));

  String sport = sportName(game);
  String away = shortValue(game["away_abbr"], "AWY", 4);
  String home = shortValue(game["home_abbr"], "HOM", 4);
  String awayScore = shortValue(game["away_score"], "-", 3);
  String homeScore = shortValue(game["home_score"], "-", 3);
  String status = shortValue(game["status"], "UPCOMING", 12);
  String state = shortValue(game["state"], "", 5);
  JsonObjectConst situation = game["situation"].as<JsonObjectConst>();
  const bool football = sportIs(sport, "FOOTBALL");
  const bool baseball = sportIs(sport, "BASEBALL");
  const bool hockey = sportIs(sport, "HOCKEY");
  const bool soccer = sport.startsWith("SOCCER");
  String detail = football ? shortValue(situation["downDist"], "", 12) : "";
  String possession = situation["activeTeam"] | "";
  if (possession.length() == 0) possession = situation["possession"] | "";
  possession.toUpperCase();
  const bool active = state == "IN";
  const bool homePossession = possession == home || possession == "HOME" || possession == "H";
  const bool awayPossession = possession == away || possession == "AWAY" || possession == "A";

  matrix->fillScreen(navy);
  matrix->drawFastHLine(0, 7, 64, muted);
  const int16_t statusWidth = static_cast<int16_t>(status.length() * 4);
  drawPixelTextFit(status, (64 - statusWidth) / 2, 1, color(255, 240, 150), 1, 60);

  drawLogo(game["away_logo"] | "", away, 1, 9, awayColor);
  drawLogo(game["home_logo"] | "", home, 49, 9, homeColor);
  drawScoreCenter(awayScore, homeScore);

  if (football && active && awayPossession) drawFootballPossessionIndicator(2, 1, awayColor);
  if (football && active && homePossession) drawFootballPossessionIndicator(53, 1, homeColor);
  if (football && detail.length() > 0) {
    const int16_t detailWidth = static_cast<int16_t>(detail.length() * 4);
    drawPixelTextFit(detail, (64 - detailWidth) / 2, 24, active ? red : color(255, 220, 90), 1, 60);
  } else if (baseball && active) {
    drawBaseballIndicators(situation);
  } else if (hockey && active) {
    drawHockeyIndicators(situation, away, home);
  } else if (soccer) {
    drawSoccerIndicators(situation);
  }
  presentFrame();
}

void renderCurrent() {
  if (pairingMode) {
    drawPairingCode();
    return;
  }
  if (!sportsMode) {
    drawMessage("SPORTS ONLY");
    return;
  }
  if (pageCount == 0) {
    drawMessage("NO SPORTS");
    return;
  }
  if (pageIndex >= pageCount) {
    pageIndex = 0;
  }
  JsonObjectConst game;
  if (!selectedGame(game)) {
    drawMessage("BAD DATA");
    return;
  }
  drawGame(game);
}

void updateFromPayload(const String& body) {
  // Parse directly into the retained document to avoid duplicating the payload tree.
  JsonDocument filter;
  filter["meta"]["pairing"]["paired"] = true;
  filter["meta"]["pairing"]["code"] = true;
  filter["settings"]["mode"] = true;
  filter["settings"]["scroll_speed"] = true;
  filter["settings"]["brightness"] = true;
  filter["content"]["sports"][0]["is_shown"] = true;
  JsonObject filterGame = filter["content"]["sports"][0]["data"].to<JsonObject>();
  filterGame["sport"] = true;
  filterGame["league"] = true;
  filterGame["away_logo"] = true;
  filterGame["home_logo"] = true;
  filterGame["away_abbr"] = true;
  filterGame["home_abbr"] = true;
  filterGame["away_score"] = true;
  filterGame["home_score"] = true;
  filterGame["away_color"] = true;
  filterGame["home_color"] = true;
  filterGame["status"] = true;
  filterGame["state"] = true;
  JsonObject filterSituation = filterGame["situation"].to<JsonObject>();
  filterSituation["downDist"] = true;
  filterSituation["activeTeam"] = true;
  filterSituation["possession"] = true;
  filterSituation["balls"] = true;
  filterSituation["strikes"] = true;
  filterSituation["outs"] = true;
  filterSituation["onFirst"] = true;
  filterSituation["onSecond"] = true;
  filterSituation["onThird"] = true;
  filterSituation["powerPlay"] = true;
  filterSituation["emptyNet"] = true;
  filterSituation["emptyNetSide"] = true;
  filterSituation["red_cards"][0]["is_home"] = true;

  payload.clear();
  DeserializationError error = deserializeJson(payload, body, DeserializationOption::Filter(filter));
  if (error) {
    Serial.print("Data JSON error: ");
    Serial.print(error.c_str());
    Serial.print(" bytes=");
    Serial.println(body.length());
    showFetchError("JSON ERROR");
    return;
  }

  JsonObjectConst meta = payload["meta"].as<JsonObjectConst>();
  JsonObjectConst pairing = meta["pairing"].as<JsonObjectConst>();
  pairingMode = !(pairing["paired"] | false);
  pairingCode = pairing["code"] | "";
  String displayBody;
  serializeJson(payload["settings"], displayBody);
  serializeJson(payload["content"], displayBody);
  serializeJson(payload["meta"], displayBody);
  uint32_t signature = hashBody(displayBody);
  JsonObjectConst settings = payload["settings"].as<JsonObjectConst>();
  String mode = settings["mode"] | "sports";
  mode.toLowerCase();
  sportsMode = mode == "sports";
  pageHoldSeconds = settings["scroll_speed"] | 0.03f;
  pageCount = sportsMode && !pairingMode ? countShownGames() : 0;
  float brightness = settings["brightness"] | 100.0f;
  if (brightness < 0.0f) brightness = 0.0f;
  if (brightness > 100.0f) brightness = 100.0f;
  matrix->setBrightness8(static_cast<uint8_t>(brightness * 2.55f));
  if (signature != payloadSignature) {
    payloadSignature = signature;
    pageIndex = 0;
    lastPageAt = millis();
  }
  message = "";
  renderCurrent();
}

void sendHeartbeat() {
  if (WiFi.status() != WL_CONNECTED || !registered) {
    return;
  }

  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (!http.begin(heartbeatUrl)) {
    return;
  }

  JsonDocument heartbeat;
  heartbeat["metadata"]["build"] = "esp32s3-hub75";
  heartbeat["metadata"]["mode"] = "sports";
  heartbeat["metadata"]["capabilities"][0] = "sports";
  heartbeat["metadata"]["uptime_seconds"] = millis() / 1000;
  String body;
  serializeJson(heartbeat, body);
  http.addHeader("Content-Type", "application/json");
  http.POST(body);
  http.end();
}

bool fetchData() {
  if (WiFi.status() != WL_CONNECTED) {
    showFetchError("WIFI LOST");
    return false;
  }
  if (!registered) {
    showFetchError("REGISTER");
    return false;
  }

  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (!http.begin(dataUrl)) {
    showFetchError("HTTP SETUP");
    return false;
  }

  int status = http.GET();
  Serial.print("Data HTTP status: ");
  Serial.println(status);
  if (status != HTTP_CODE_OK) {
    if (status == HTTP_CODE_NOT_FOUND) {
      registered = false;
      tickerId = "";
      dataUrl = "";
      heartbeatUrl = "";
      pageCount = 0;
      message = "REGISTER";
    } else {
      showFetchError("HTTP " + String(status));
    }
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();
  updateFromPayload(body);
  return message.length() == 0;
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);
  if (!wifiStarted) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    wifiStarted = true;
  } else {
    WiFi.reconnect();
  }
  uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) {
    drawMessage("WIFI...");
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi address: ");
    Serial.println(WiFi.localIP());
    message = "";
  } else {
    showFetchError("WIFI LOST");
  }
}

void setupMatrix() {
  HUB75_I2S_CFG::i2s_pins pins = {
    R1_PIN, G1_PIN, B1_PIN, R2_PIN, G2_PIN, B2_PIN,
    A_PIN, B_PIN, C_PIN, D_PIN, E_PIN, LAT_PIN, OE_PIN, CLK_PIN
  };
  HUB75_I2S_CFG config(64, 32, 1, pins);
  config.double_buff = true;
  config.clkphase = true;
  config.latch_blanking = 3;
  config.i2sspeed = HUB75_I2S_CFG::HZ_16M;
  config.min_refresh_rate = 240;
  matrix = new MatrixPanel_I2S_DMA(config);
  matrix->begin();
  matrix->setBrightness8(PANEL_BRIGHTNESS);
  matrix->setTextWrap(false);
  matrix->setTextSize(1);
  drawMessage("STARTING");
}

void setup() {
  Serial.begin(115200);
  setupLogoCache();
  setupMatrix();
  if (SOLID_COLOR_TEST) {
    // Keep the ticker startup below for the next test. The color test isolates panel output.
    drawSolidColorTest();
    lastSolidColorAt = millis();
  } else {
    connectWifi();
    lastFetchAt = millis() - FETCH_INTERVAL_MS;
    lastHeartbeatAt = millis() - HEARTBEAT_INTERVAL_MS;
    lastRegisterAt = millis() - REGISTER_INTERVAL_MS;
    lastPageAt = millis();
  }
}

void loop() {
  const uint32_t now = millis();

  if (SOLID_COLOR_TEST) {
    if (now - lastSolidColorAt >= SOLID_COLOR_INTERVAL_MS) {
      lastSolidColorAt = now;
      drawSolidColorTest();
    }
    return;
  } else {
    if (WiFi.status() != WL_CONNECTED && now - lastFetchAt >= WIFI_RETRY_INTERVAL_MS) {
      lastFetchAt = now;
      connectWifi();
    }

    if (WiFi.status() == WL_CONNECTED && !registered && now - lastRegisterAt >= REGISTER_INTERVAL_MS) {
      lastRegisterAt = now;
      registerDevice();
    }

    if (registered && now - lastFetchAt >= FETCH_INTERVAL_MS) {
      lastFetchAt = now;
      fetchData();
    }

    if (now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
      lastHeartbeatAt = now;
      sendHeartbeat();
    }

    if (message.length() > 0) {
      if (now - lastMessageAt >= MESSAGE_REFRESH_MS) {
        lastMessageAt = now;
        drawMessage(message);
      }
      return;
    }

    if (pageCount > 1 && now - lastPageAt >= pageHoldMillis(pageHoldSeconds)) {
      pageIndex = (pageIndex + 1) % pageCount;
      lastPageAt = now;
      renderCurrent();
    }
  }
}
