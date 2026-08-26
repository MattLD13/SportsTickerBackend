#include <Arduino.h>
#include <ArduinoJson.h>
#include <NimBLEDevice.h>
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include <HTTPClient.h>
#include <JPEGDEC.h>
#include <LittleFS.h>
#include <Preferences.h>
#undef INTELSHORT
#undef INTELLONG
#undef MOTOSHORT
#undef MOTOLONG
#include <PNGdec.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Update.h>
#include <esp_image_format.h>
#include <esp_ota_ops.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include <mbedtls/base64.h>
#include <mbedtls/gcm.h>
#include <mbedtls/hkdf.h>
#include <mbedtls/md.h>
#include <time.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <new>
#include "../platform/config.h"
#include "../platform/matrix_driver.h"
#include "../assets/logo_sources.h"

PNG pngDecoder;
JPEGDEC jpegDecoder;
JsonDocument payload;
uint32_t rotationSignature = 0;
uint32_t logoWorkingSetSignature = 0;
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
String displayMode = "sports";
bool registered = false;
bool wifiStarted = false;
bool wifiPairingMode = false;
bool blePairingStarted = false;
uint32_t wifiWaitStartedAt = 0;
uint32_t lastWifiRetryAt = 0;
uint32_t lastDebugLogAt = 0;
bool savedWifiVisible = false;
String wifiSsid;
String wifiPassword;
String setupCode;
Preferences preferences;
portMUX_TYPE bleProvisioningMux = portMUX_INITIALIZER_UNLOCKED;
char pendingWifiSsid[33] = {};
char pendingWifiPassword[65] = {};
bool pendingWifiReady = false;

static constexpr char BLE_SERVICE_UUID[] = "8F8B0001-6E2A-4D8A-9F31-8D4B77F0B001";
static constexpr char BLE_CHALLENGE_UUID[] = "8F8B0002-6E2A-4D8A-9F31-8D4B77F0B001";
static constexpr char BLE_CREDENTIALS_UUID[] = "8F8B0003-6E2A-4D8A-9F31-8D4B77F0B001";
static constexpr char BLE_RESULT_UUID[] = "8F8B0004-6E2A-4D8A-9F31-8D4B77F0B001";
static constexpr char BLE_PAIRING_UUID[] = "8F8B0005-6E2A-4D8A-9F31-8D4B77F0B001";
static constexpr char BLE_PROTOCOL_INFO[] = "SportsTicker BLE Wi-Fi v1";
static constexpr uint8_t BLE_CHALLENGE_LENGTH = 16;
static constexpr uint8_t BLE_MAX_CREDENTIAL_CHUNKS = 64;
uint8_t bleChallenge[BLE_CHALLENGE_LENGTH] = {};
String bleCredentialChunks[BLE_MAX_CREDENTIAL_CHUNKS];
bool bleCredentialChunkReceived[BLE_MAX_CREDENTIAL_CHUNKS] = {};
uint8_t bleCredentialChunkTotal = 0;
uint8_t bleCredentialChunkCount = 0;
NimBLECharacteristic* bleChallengeCharacteristic = nullptr;
NimBLECharacteristic* bleCredentialsCharacteristic = nullptr;
NimBLECharacteristic* bleResultCharacteristic = nullptr;
NimBLECharacteristic* blePairingCharacteristic = nullptr;

static constexpr uint8_t RAM_LOGO_WORKING_SET_LOGOS = RUNTIME_LOGO_SLOTS;
static constexpr uint8_t RAM_LOGO_WORKING_SET_GAMES = RAM_LOGO_WORKING_SET_LOGOS / 2;
static constexpr uint8_t LOGO_WORK_QUEUE_SLOTS = RAM_LOGO_WORKING_SET_LOGOS;

struct RuntimeLogo {
  String url;
  uint16_t pixels[RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE] = {};
  uint8_t mask[RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE] = {};
  bool valid = false;
  bool pinned = false;
};

struct PreparedGameLogos {
  String awayPrimary;
  String awayFallback;
  String homePrimary;
  String homeFallback;
};

struct PersistedLogo {
  uint32_t urlHash;
  char url[192];
  uint16_t pixels[RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE];
  uint8_t mask[RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE];
};

RuntimeLogo* runtimeLogos = nullptr;
uint8_t runtimeLogoSlotCount = 0;
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
uint32_t logoSampleCounts[LOGO_PIXEL_COUNT] = {};
uint32_t logoOpaqueCounts[LOGO_PIXEL_COUNT] = {};
uint32_t logoRedSums[LOGO_PIXEL_COUNT] = {};
uint32_t logoGreenSums[LOGO_PIXEL_COUNT] = {};
uint32_t logoBlueSums[LOGO_PIXEL_COUNT] = {};
String logoFailureUrls[LOGO_FAILURE_SLOTS];
uint8_t logoFailureCount = 0;
uint8_t logoFailureIndex = 0;
String logoRetryUrls[LOGO_FAILURE_SLOTS];
uint32_t logoRetryAfter[LOGO_FAILURE_SLOTS] = {};
uint8_t logoRetryCount = 0;
uint8_t logoRetryIndex = 0;
bool lastLogoFailurePermanent = false;
bool logoCacheReady = false;
SemaphoreHandle_t logoCacheMutex = nullptr;
SemaphoreHandle_t logoDecodeMutex = nullptr;
SemaphoreHandle_t logoDownloadMutex = nullptr;
SemaphoreHandle_t logoWorkMutex = nullptr;
SemaphoreHandle_t logoStorageMutex = nullptr;
SemaphoreHandle_t networkMutex = nullptr;
TaskHandle_t logoWorkerHandle = nullptr;
String logoWorkPrimary[LOGO_WORK_QUEUE_SLOTS];
String logoWorkFallback[LOGO_WORK_QUEUE_SLOTS];
uint8_t logoWorkCount = 0;
String logoForegroundPrimary[LOGO_FOREGROUND_GAMES * 2];
String logoForegroundFallback[LOGO_FOREGROUND_GAMES * 2];
uint8_t logoForegroundCount = 0;
bool logoWorkerBusy = false;
bool logoWorkerPending = false;
bool logoWorkerCompleted = false;
bool assetsLoading = false;
bool sportsFrameReady = false;
uint16_t logoPlanPageIndex = 0;
uint16_t logoProgressComplete = 0;
uint16_t logoProgressTotal = 0;
uint32_t logoPlanGeneration = 0;
uint32_t logoWorkerGeneration = 0;
bool logoPlanDisplayPending = false;
uint32_t lastAssetFrameAt = 0;
uint32_t assetLoadingStartedAt = 0;
struct tm preparedClock = {};
bool preparedClockValid = false;
PreparedGameLogos preparedGameLogos;
String configuredTimezone = DEFAULT_TIMEZONE;
String appliedTimezone;

void renderCurrent();
void drawDownloadingProgress(uint16_t complete, uint16_t total);
void drawFirmwareUpdate(uint8_t state, uint32_t complete, uint32_t total, const char* detail);
void logoWorkerTask(void* parameter);
void firmwareUpdateInitialize();
void firmwareUpdateObserve(JsonVariantConst command);
void firmwareUpdateTick(uint32_t now);
bool firmwareUpdateDisplayActive();
bool firmwareUpdateTransferActive();
void firmwareUpdateDisplaySnapshot(uint8_t& state, uint32_t& complete, uint32_t& total, char* detail, size_t detailSize);
void startBlePairing();
void startPairingMode();
void stopBlePairing();
void applyPendingWifiCredentials();
void saveWifiCredentials(const String& ssid, const String& password);

bool acquireNetwork(uint32_t timeoutMs) {
  return networkMutex == nullptr ||
    xSemaphoreTake(networkMutex, pdMS_TO_TICKS(timeoutMs)) == pdTRUE;
}

void releaseNetwork() {
  if (networkMutex != nullptr) {
    xSemaphoreGive(networkMutex);
  }
}

void logoProgressSnapshot(bool& loading, uint16_t& complete, uint16_t& total) {
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  loading = assetsLoading;
  complete = logoProgressComplete;
  total = logoProgressTotal;
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
}

#include "../platform/connectivity.inc"
#include "../protocol/backend.inc"
#include "../platform/firmware_update.inc"
#include "../rendering/primitives.inc"
#include "../assets/logo_pipeline.inc"
#include "../features/renderers.inc"
#include "../protocol/payload.inc"
#include "scheduler.inc"
