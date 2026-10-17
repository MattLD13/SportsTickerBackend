#pragma once

#include <ArduinoJson.h>
#include <Preferences.h>
#include <esp_ota_ops.h>
#include "../runtime/network.h"
#include "firmware_validation.h"

enum FirmwareUpdateState : uint8_t {
  FIRMWARE_UPDATE_IDLE = 0,
  FIRMWARE_UPDATE_CHECKING = 1,
  FIRMWARE_UPDATE_DOWNLOADING = 2,
  FIRMWARE_UPDATE_INSTALLING = 3,
  FIRMWARE_UPDATE_FAILED = 4,
};

struct FirmwareManifestPayload {
  String version;
  String target;
  String hardware;
  String binaryUrl;
  size_t size = 0;
  uint8_t sha256[32] = {};
};

struct FirmwareUpdateConfig {
  const char* version;
  const char* target;
  const char* hardware;
  size_t minImageSize, maxImageSize;
  uint32_t httpTimeoutMs, retryBackoffMs, bootValidationMs, failureDisplayMs;
};

// The instance must outlive its update task. Public methods run on the display task.
class FirmwareUpdater {
 public:
  FirmwareUpdater(Preferences& preferences, NetworkGate& gate, NetworkWorker& worker,
                  const String& backendUrl, FirmwareUpdateConfig config);
  FirmwareUpdater(const FirmwareUpdater&) = delete;
  FirmwareUpdater& operator=(const FirmwareUpdater&) = delete;
  void displaySnapshot(uint8_t& state, uint32_t& complete, uint32_t& total, char* detail, size_t detailSize);
  bool displayActive();
  bool transferActive();
  void observe(JsonVariantConst command, bool registered, bool pairingMode, const String& tickerId);
  void initialize();
  void applyAckResponse(const NetworkJob& job);
  bool tick(uint32_t now, bool registered, const String& tickerId);
  bool bootValidated() const { return firmwareUpdateBootValidated; }
  int bootState() const { return firmwareUpdateBootState; }
  int bootStateError() const { return firmwareUpdateBootStateError; }

 private:
  static void taskEntry(void* context);
  void setFirmwareUpdateDetail(const char* value);
  void setFirmwareUpdateState(FirmwareUpdateState state, uint32_t complete, uint32_t total);
  void setFirmwareUpdateVersion(char* destination, size_t destinationSize, const String& value);
  bool copyFirmwareUpdateVersion(const char* source, String& destination);
  bool parseFirmwareManifest(const String& body, const String& requestedVersion, FirmwareManifestPayload& manifest);
  bool fetchFirmwareManifest(const String& requestedVersion, FirmwareManifestPayload& manifest);
  void abortFirmwareWrite();
  bool verifyFirmwareImage(const esp_partition_t* target);
  bool downloadFirmware(const FirmwareManifestPayload& manifest);
  void finishFirmwareUpdateTask(bool success, const char* detail);
  void runTask();
  void acknowledgeConfirmedFirmware(bool registered, const String& tickerId);
  Preferences& preferences_;
  NetworkGate& gate_;
  NetworkWorker& worker_;
  String baseUrl_, tickerId_;
  FirmwareUpdateConfig config_;
  volatile FirmwareUpdateState firmwareUpdateState = FIRMWARE_UPDATE_IDLE;
  volatile uint32_t firmwareUpdateComplete = 0;
  volatile uint32_t firmwareUpdateTotal = 0;
  portMUX_TYPE firmwareUpdateMux = portMUX_INITIALIZER_UNLOCKED;
  char firmwareUpdateRequestedVersion[64] = {};
  char firmwareUpdateFailedVersion[64] = {};
  char firmwareUpdateDetail[24] = {};
  char firmwareUpdateConfirmedVersion[64] = {};
  bool firmwareUpdateTaskRunning = false;
  bool firmwareUpdateBootChecked = false;
  bool firmwareUpdateBootValidated = false;
  int firmwareUpdateBootState = ESP_OTA_IMG_UNDEFINED;
  int firmwareUpdateBootStateError = ESP_ERR_INVALID_STATE;
  bool firmwareUpdateAcknowledged = false;
  String firmwareUpdateReceiptCommandId;
  uint32_t firmwareUpdateLastAckAt = 0;
  uint32_t firmwareUpdateFailureAt = 0;
  uint32_t firmwareUpdateLastFrameAt = 0;
  TaskHandle_t firmwareUpdateTaskHandle = nullptr;
};
