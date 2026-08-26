#pragma once

// Set these network values before flashing the ESP32.
static const char* WIFI_SSID = "MattsWifi2.4";
static const char* WIFI_PASSWORD = "11Raspberry";
static const char* BACKEND_URL = "https://ticker.mattdicks.org";
static const char* DEVICE_NAME = "MiniTicker";
static const char* DEFAULT_TIMEZONE = "America/New_York";
static const char* DEFAULT_TIMEZONE_SPEC = "EST5EDT,M3.2.0,M11.1.0";
static constexpr char MINI_FIRMWARE_VERSION[] = "mini-1.2.1";
static constexpr char MINI_FIRMWARE_TARGET[] = "esp32s3";
static constexpr char MINI_FIRMWARE_HARDWARE[] = "esp32-s3";

// Matrix Portal S3 pin map for one 64x32, 1/16-scan HUB75 panel.
static constexpr int R1_PIN = 42;
// The common 64x32 panel swaps green and blue at its HUB75 input.
static constexpr int G1_PIN = 40;
static constexpr int B1_PIN = 41;
static constexpr int R2_PIN = 38;
static constexpr int G2_PIN = 37;
static constexpr int B2_PIN = 39;
static constexpr int A_PIN = 45;
static constexpr int B_PIN = 36;
static constexpr int C_PIN = 48;
static constexpr int D_PIN = 35;
static constexpr int E_PIN = -1;
static constexpr int LAT_PIN = 47;
static constexpr int OE_PIN = 14;
static constexpr int CLK_PIN = 2;

static constexpr uint32_t FETCH_INTERVAL_MS = 5000;
static constexpr uint32_t HEARTBEAT_INTERVAL_MS = 30000;
static constexpr uint32_t REGISTER_INTERVAL_MS = 10000;
static constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 10000;
static constexpr uint32_t WIFI_PAIRING_TIMEOUT_MS = 30000;
static constexpr uint32_t MESSAGE_REFRESH_MS = 1000;
static constexpr uint8_t PANEL_BRIGHTNESS = 96;
static constexpr int16_t CONTENT_X_OFFSET = 1;
static constexpr bool SOLID_COLOR_TEST = false;
static constexpr bool FORCE_PAIRING_TEST = false;
static constexpr uint32_t SOLID_COLOR_INTERVAL_MS = 1500;
static constexpr uint32_t FIRMWARE_FAILURE_DISPLAY_MS = 12000;
static constexpr uint32_t FIRMWARE_RETRY_BACKOFF_MS = 60000;
static constexpr uint32_t FIRMWARE_BOOT_VALIDATION_MS = 15000;
static constexpr uint32_t FIRMWARE_HTTP_TIMEOUT_MS = 15000;
static constexpr size_t FIRMWARE_MIN_IMAGE_SIZE = 64 * 1024;
static constexpr size_t FIRMWARE_MAX_IMAGE_SIZE = 2 * 1024 * 1024 - 4096;

// Logo cache and decoder limits.
static constexpr uint8_t RUNTIME_LOGO_SIZE = 18;
static constexpr uint8_t RUNTIME_LOGO_SLOTS = 32;
static constexpr uint8_t LOGO_FOREGROUND_GAMES = 2;
static constexpr uint8_t LOGO_FAILURE_SLOTS = 64;
static constexpr uint32_t LOGO_RETRY_BACKOFF_MS = 120000;
static constexpr uint32_t LOGO_STARTUP_TIMEOUT_MS = 15000;
static constexpr uint32_t LOGO_PROGRESS_REFRESH_MS = 200;
static constexpr uint16_t FLASH_LOGO_CACHE_SLOTS = 256;
static constexpr uint16_t FLASH_LOGO_PROBE_LIMIT = FLASH_LOGO_CACHE_SLOTS;
static constexpr size_t LOGO_DOWNLOAD_LIMIT = 256 * 1024;
static constexpr uint16_t LOGO_DECODE_WIDTH_LIMIT = 1024;
static constexpr char LOGO_CACHE_FILE[] = "/logo_cache_v9.bin";
static constexpr size_t LOGO_PIXEL_COUNT = RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE;
