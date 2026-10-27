#include <Arduino.h>
#include <ArduinoJson.h>
#include <NimBLEDevice.h>
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <mbedtls/base64.h>
#include <mbedtls/gcm.h>
#include <mbedtls/hkdf.h>
#include <mbedtls/md.h>
#include <time.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <freertos/queue.h>
#include <new>
#include "../platform/config.h"
#include "../platform/tls.h"
#include "../platform/matrix_driver.h"
#include "../platform/device_sensors.h"
#include "../assets/logo_sources.h"
#include "../rendering/sports_pane.h"
#include "../rendering/utility_panels.h"
#include "../rendering/text_primitives.h"
#include "../protocol/payload_reader.h"
#include "network.h"
#include "../platform/firmware_update.h"
#include "../platform/http_diagnostics.h"
#include "../platform/network_recovery.h"
#include "../platform/wifi_station.h"

#include "../protocol/device_payload.h"
#include "../assets/sprite_assets.h"
#include "../assets/artwork_assets.h"
#include "../platform/device_credentials.h"

DevicePayload payload;
MiniDeviceSensors deviceSensors;
uint32_t rotationSignature = 0;
uint32_t logoWorkingSetSignature = 0;
uint32_t lastFetchAt = 0;
uint64_t lastPrefetchPageUs = 0;
uint32_t lastHeartbeatSuccessAt = 0, heartbeatFailures = 0;
int lastHeartbeatStatus = 0;
bool heartbeatSucceeded = false;
uint32_t lastRegisterAt = 0;
uint32_t lastMessageAt = 0;
uint16_t pageIndex = 0;
uint16_t pageCount = 0;
float pageHoldSeconds = 3.0f;
String message = "PLEASE WAIT";
ticker_ui::SystemKind messageKind = ticker_ui::SystemKind::Startup;
uint8_t solidColorIndex = 0;
uint32_t lastSolidColorAt = 0;
String tickerId;
String dataUrl;
String pairingCode;
bool pairingMode = false;
bool sportsMode = true;
String displayMode = "sports";
String selectedModeItemId;
bool registered = false;
int lastDataStatus = 0;
int lastRegistrationStatus = 0;
String lastNetworkError, lastResolvedAddress;
NetworkRecovery networkRecovery;
bool networkReconnectRequested = false;
uint32_t networkReconnects = 0;
int lastDataExpectedBytes = 0;
int lastDataTransferBytes = 0;
size_t lastDataBytes = 0;
String lastDataContentType;
String lastDataEncoding;
String lastDataJsonError;
size_t lastDataJsonOffset = 0;
uint32_t dataJsonFailures = 0;
uint32_t lastDataDurationMs = 0;
uint32_t lastDataSuccessAt = 0;
uint32_t dataDeadlineTimeouts = 0;
uint32_t reusedDataConnections = 0, freshDataConnections = 0;
bool lastDataExpired = false;
uint32_t nextPollBudgetMs = TransferDeadline::DefaultBudgetMs;
uint32_t lastDataGateWaitMs = 0, lastDataHeadersMs = 0, lastDataBodyMs = 0;
bool wifiWasConnected = false;
bool wifiKnownWorking = false;
bool wifiPairingMode = false;
bool blePairingStarted = false;
uint32_t wifiWaitStartedAt = 0;
uint32_t lastDebugLogAt = 0;
String wifiSsid;
String wifiPassword;
String setupCode;
Preferences preferences;
portMUX_TYPE bleProvisioningMux = portMUX_INITIALIZER_UNLOCKED;
char pendingWifiSsid[33] = {};
char pendingWifiPassword[65] = {};
bool pendingWifiReady = false;
bool pendingWifiResultRead = false;
bool logoWorkbenchMode = false;
static uint8_t logoWorkbenchFrameRgb[64 * 32 * 3] = {};

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
static constexpr uint8_t LOGO_WORK_QUEUE_SLOTS = RAM_LOGO_WORKING_SET_LOGOS;

struct PreparedGameLogos {
  String awayPrimary;
  String homePrimary;
};

String logoRetryUrls[LOGO_FAILURE_SLOTS];
uint32_t logoRetryAfter[LOGO_FAILURE_SLOTS] = {};
uint32_t spriteRetryDueAt = 0;
uint8_t logoRetryCount = 0;
uint8_t logoRetryIndex = 0;
SemaphoreHandle_t logoWorkMutex = nullptr;
DeviceCredentials deviceCredentials;
NetworkGate networkGate;
NetworkWorker networkWorker(networkGate, deviceCredentials.token());
SpriteAssets spriteAssets(networkWorker, networkGate, BACKEND_URL);
ArtworkAssets musicArtwork(networkWorker, BACKEND_URL);
uint32_t lastAnimatedFrameAt = 0;
WifiStation wifiStation(networkGate);
FirmwareUpdater firmwareUpdater(preferences, networkGate, networkWorker, BACKEND_URL, deviceCredentials.token(), {
  MINI_FIRMWARE_VERSION, MINI_FIRMWARE_TARGET, MINI_FIRMWARE_HARDWARE,
  FIRMWARE_MIN_IMAGE_SIZE, FIRMWARE_MAX_IMAGE_SIZE, FIRMWARE_HTTP_TIMEOUT_MS,
  FIRMWARE_RETRY_BACKOFF_MS, FIRMWARE_BOOT_VALIDATION_MS, FIRMWARE_FAILURE_DISPLAY_MS
});
TaskHandle_t logoWorkerHandle = nullptr;
String logoWorkPrimary[LOGO_WORK_QUEUE_SLOTS];
uint8_t logoWorkCount = 0;
String logoForegroundPrimary[LOGO_FOREGROUND_GAMES * 2];
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
int lastPresentedClockSecond = -1;
bool lastPresentedClockReady = false;
PreparedGameLogos preparedGameLogos;
String configuredTimezone = DEFAULT_TIMEZONE;
String appliedTimezone;

bool drawLogoAsset(const String& key, int16_t x, int16_t y) { return spriteAssets.draw(key, x, y, *matrix); }

void renderCurrent();
void drawDownloadingProgress(uint16_t complete, uint16_t total);
void drawFirmwareUpdate(uint8_t state, uint32_t complete, uint32_t total, const char* detail);
void logoWorkerTask(void* parameter);
void startBlePairing();
void startPairingMode();
void stopBlePairing();
void applyPendingWifiCredentials(uint32_t now);
void saveWifiCredentials(const String& ssid, const String& password);

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
#include "../rendering/presentation.inc"
#include "../assets/sprite_pipeline.inc"
#include "../features/renderers.inc"
#include "diagnostics.inc"
#include "../protocol/payload.inc"
#include "network_results.inc"
#include "scheduler.inc"
