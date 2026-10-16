#include "firmware_update.h"
#include "tls.h"
#include "http_diagnostics.h"
#include "../protocol/payload_reader.h"
#include <WiFi.h>
#include <Update.h>
#include <esp_image_format.h>
#include <mbedtls/md.h>

static constexpr char FIRMWARE_PENDING_NVS_KEY[] = "ota_pending";
static constexpr char FIRMWARE_FAILED_NVS_KEY[] = "ota_failed";
static_assert(sizeof(FIRMWARE_PENDING_NVS_KEY) <= 16, "NVS keys allow 15 characters");
static_assert(sizeof(FIRMWARE_FAILED_NVS_KEY) <= 16, "NVS keys allow 15 characters");


FirmwareUpdater::FirmwareUpdater(Preferences& preferences, NetworkGate& gate, NetworkWorker& worker,
                                 const String& backendUrl, FirmwareUpdateConfig config)
    : preferences_(preferences), gate_(gate), worker_(worker), baseUrl_(backendUrl), config_(config) {
  while (baseUrl_.endsWith("/")) baseUrl_.remove(baseUrl_.length() - 1);
}

void FirmwareUpdater::taskEntry(void* context) {
  static_cast<FirmwareUpdater*>(context)->runTask();
}

void FirmwareUpdater::setFirmwareUpdateDetail(const char* value) {
  portENTER_CRITICAL(&firmwareUpdateMux);
  strncpy(firmwareUpdateDetail, value == nullptr ? "ERROR" : value, sizeof(firmwareUpdateDetail) - 1);
  firmwareUpdateDetail[sizeof(firmwareUpdateDetail) - 1] = '\0';
  portEXIT_CRITICAL(&firmwareUpdateMux);
}

void FirmwareUpdater::setFirmwareUpdateState(FirmwareUpdateState state, uint32_t complete, uint32_t total) {
  portENTER_CRITICAL(&firmwareUpdateMux);
  firmwareUpdateState = state;
  firmwareUpdateComplete = complete;
  firmwareUpdateTotal = total;
  portEXIT_CRITICAL(&firmwareUpdateMux);
}

void FirmwareUpdater::setFirmwareUpdateVersion(char* destination, size_t destinationSize, const String& value) {
  value.substring(0, destinationSize - 1).toCharArray(destination, destinationSize);
}

bool FirmwareUpdater::copyFirmwareUpdateVersion(const char* source, String& destination) {
  char value[sizeof(firmwareUpdateRequestedVersion)] = {};
  portENTER_CRITICAL(&firmwareUpdateMux);
  strncpy(value, source, sizeof(value) - 1);
  portEXIT_CRITICAL(&firmwareUpdateMux);
  destination = value;
  destination.trim();
  return destination.length() > 0;
}

void FirmwareUpdater::displaySnapshot(uint8_t& state, uint32_t& complete, uint32_t& total, char* detail, size_t detailSize) {
  portENTER_CRITICAL(&firmwareUpdateMux);
  state = static_cast<uint8_t>(firmwareUpdateState);
  complete = firmwareUpdateComplete;
  total = firmwareUpdateTotal;
  strncpy(detail, firmwareUpdateDetail, detailSize - 1);
  detail[detailSize - 1] = '\0';
  portEXIT_CRITICAL(&firmwareUpdateMux);
}

bool FirmwareUpdater::displayActive() {
  portENTER_CRITICAL(&firmwareUpdateMux);
  const bool active = firmwareUpdateState != FIRMWARE_UPDATE_IDLE;
  portEXIT_CRITICAL(&firmwareUpdateMux);
  return active;
}

bool FirmwareUpdater::transferActive() {
  portENTER_CRITICAL(&firmwareUpdateMux);
  const bool active = firmwareUpdateState == FIRMWARE_UPDATE_CHECKING ||
                      firmwareUpdateState == FIRMWARE_UPDATE_DOWNLOADING ||
                      firmwareUpdateState == FIRMWARE_UPDATE_INSTALLING;
  portEXIT_CRITICAL(&firmwareUpdateMux);
  return active;
}

bool FirmwareUpdater::parseFirmwareManifest(const String& body, const String& requestedVersion, FirmwareManifestPayload& manifest) {
  JsonDocument response;
  if (deserializeJson(response, body)) {
    return false;
  }
  JsonObjectConst value = response["firmware"].as<JsonObjectConst>();
  if (value.isNull()) {
    return false;
  }
  manifest.version = value["version"] | "";
  manifest.target = value["target"] | "";
  manifest.hardware = value["hardware"] | "";
  manifest.binaryUrl = value["binary_url"] | "";
  manifest.version.trim();
  manifest.target.trim();
  manifest.target.toLowerCase();
  manifest.hardware.trim();
  manifest.hardware.toLowerCase();
  manifest.binaryUrl.trim();
  const String checksum = value["sha256"] | "";
  const long rawSize = value["size"] | 0L;
  if (!mini_firmware::manifestMatches(requestedVersion, manifest.version, manifest.target, manifest.hardware,
      manifest.binaryUrl, rawSize, config_.target, config_.hardware, config_.minImageSize, config_.maxImageSize) ||
      !mini_firmware::parseSha256(checksum, manifest.sha256)) {
    return false;
  }
  manifest.size = static_cast<size_t>(rawSize);
  return true;
}

bool FirmwareUpdater::fetchFirmwareManifest(const String& requestedVersion, FirmwareManifestPayload& manifest) {
  if (WiFi.status() != WL_CONNECTED || tickerId_.length() == 0 || !gate_.acquire(config_.httpTimeoutMs)) {
    return false;
  }
  BackendTlsClient client;
  configureTls(client);
  client.setTimeout(config_.httpTimeoutMs / 1000);
  client.setHandshakeTimeout(config_.httpTimeoutMs / 1000);
  HTTPClient http;
  http.useHTTP10(true);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(config_.httpTimeoutMs);
  String url = (baseUrl_ + "/api/v2/tickers/") + tickerId_ + "/firmware?version=" + requestedVersion;
  if (!http.begin(client, url)) {
    gate_.release();
    return false;
  }
  const int status = http.GET();
  if (status != HTTP_CODE_OK) {
    logSecureHttpError("Firmware manifest", status, client);
    http.end();
    gate_.release();
    return false;
  }
  String body = http.getString();
  http.end();
  gate_.release();
  return parseFirmwareManifest(body, requestedVersion, manifest);
}

void FirmwareUpdater::abortFirmwareWrite() {
  Update.abort();
}

bool FirmwareUpdater::verifyFirmwareImage(const esp_partition_t* target) {
  if (target == nullptr) {
    return false;
  }
  esp_image_metadata_t metadata = {};
  const esp_partition_pos_t position = {target->address, target->size};
  return esp_image_verify(ESP_IMAGE_VERIFY, &position, &metadata) == ESP_OK;
}

bool FirmwareUpdater::downloadFirmware(const FirmwareManifestPayload& manifest) {
  if (!gate_.acquire(config_.httpTimeoutMs)) {
    return false;
  }
  BackendTlsClient client;
  configureTls(client);
  client.setTimeout(config_.httpTimeoutMs / 1000);
  client.setHandshakeTimeout(config_.httpTimeoutMs / 1000);
  HTTPClient http;
  http.useHTTP10(false);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(config_.httpTimeoutMs);
  if (!http.begin(client, manifest.binaryUrl)) {
    gate_.release();
    return false;
  }
  const int status = http.GET();
  const int contentLength = http.getSize();
  if (status != HTTP_CODE_OK || (contentLength >= 0 && static_cast<size_t>(contentLength) != manifest.size)) {
    logSecureHttpError("Firmware image", status, client);
    http.end();
    abortFirmwareWrite();
    gate_.release();
    return false;
  }

  const esp_partition_t* target = esp_ota_get_next_update_partition(nullptr);
  if (target == nullptr || manifest.size > target->size || !Update.begin(manifest.size, U_FLASH)) {
    http.end();
    abortFirmwareWrite();
    gate_.release();
    return false;
  }
  mbedtls_md_context_t digest;
  const mbedtls_md_info_t* sha256 = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  mbedtls_md_init(&digest);
  bool digestReady = sha256 != nullptr && mbedtls_md_setup(&digest, sha256, 0) == 0 &&
                     mbedtls_md_starts(&digest) == 0;
  WiFiClient* stream = http.getStreamPtr();
  uint8_t buffer[4096] = {};
  size_t received = 0;
  uint32_t lastDataAt = millis();
  bool valid = digestReady;
  while (valid && received < manifest.size) {
    const size_t available = stream->available();
    if (available == 0) {
      if (millis() - lastDataAt > config_.httpTimeoutMs) {
        valid = false;
        break;
      }
      delay(2);
      continue;
    }
    const size_t requested = min(sizeof(buffer), min(available, manifest.size - received));
    const size_t readCount = stream->readBytes(buffer, requested);
    if (readCount == 0 || mbedtls_md_update(&digest, buffer, readCount) != 0 || Update.write(buffer, readCount) != readCount) {
      valid = false;
      break;
    }
    received += readCount;
    lastDataAt = millis();
    setFirmwareUpdateState(FIRMWARE_UPDATE_DOWNLOADING, received, manifest.size);
    delay(1);
  }
  if (contentLength < 0) {
    stream->setTimeout(1);
    uint8_t extraByte = 0;
    if (stream->readBytes(&extraByte, 1) > 0) {
      valid = false;
    }
  }
  uint8_t actualSha256[32] = {};
  if (valid && mbedtls_md_finish(&digest, actualSha256) != 0) {
    valid = false;
  }
  mbedtls_md_free(&digest);
  if (!mini_firmware::transferComplete(valid, received, manifest.size, actualSha256, manifest.sha256)) {
    http.end();
    abortFirmwareWrite();
    gate_.release();
    return false;
  }
  if (preferences_.putString(FIRMWARE_PENDING_NVS_KEY, manifest.version) == 0) {
    http.end();
    abortFirmwareWrite();
    gate_.release();
    return false;
  }
  if (!Update.end()) {
    preferences_.remove(FIRMWARE_PENDING_NVS_KEY);
    http.end();
    abortFirmwareWrite();
    gate_.release();
    return false;
  }
  http.end();
  const bool imageValid = verifyFirmwareImage(target);
  const bool bootSet = imageValid && esp_ota_set_boot_partition(target) == ESP_OK;
  if (!bootSet) {
    esp_ota_set_boot_partition(esp_ota_get_running_partition());
    preferences_.remove(FIRMWARE_PENDING_NVS_KEY);
  }
  gate_.release();
  if (!bootSet) {
    return false;
  }
  return true;
}

void FirmwareUpdater::finishFirmwareUpdateTask(bool success, const char* detail) {
  if (!success) {
    char requested[sizeof(firmwareUpdateRequestedVersion)] = {};
    portENTER_CRITICAL(&firmwareUpdateMux);
    strncpy(requested, firmwareUpdateRequestedVersion, sizeof(requested) - 1);
    strncpy(firmwareUpdateFailedVersion, requested, sizeof(firmwareUpdateFailedVersion) - 1);
    firmwareUpdateFailureAt = millis();
    portEXIT_CRITICAL(&firmwareUpdateMux);
    setFirmwareUpdateDetail(detail);
    setFirmwareUpdateState(FIRMWARE_UPDATE_FAILED, 0, 0);
    Serial.printf("Firmware update failed: %s\n", detail);
  }
  portENTER_CRITICAL(&firmwareUpdateMux);
  firmwareUpdateTaskRunning = false;
  firmwareUpdateTaskHandle = nullptr;
  portEXIT_CRITICAL(&firmwareUpdateMux);
}

void FirmwareUpdater::runTask() {
  String requestedVersion;
  if (!copyFirmwareUpdateVersion(firmwareUpdateRequestedVersion, requestedVersion)) {
    finishFirmwareUpdateTask(false, "BAD VERSION");
    vTaskDelete(nullptr);
    return;
  }
  setFirmwareUpdateState(FIRMWARE_UPDATE_CHECKING, 0, 0);
  FirmwareManifestPayload manifest;
  if (!fetchFirmwareManifest(requestedVersion, manifest)) {
    finishFirmwareUpdateTask(false, "MANIFEST");
    vTaskDelete(nullptr);
    return;
  }
  setFirmwareUpdateState(FIRMWARE_UPDATE_DOWNLOADING, 0, manifest.size);
  if (!downloadFirmware(manifest)) {
    finishFirmwareUpdateTask(false, "DOWNLOAD");
    vTaskDelete(nullptr);
    return;
  }
  setFirmwareUpdateState(FIRMWARE_UPDATE_INSTALLING, manifest.size, manifest.size);
  setFirmwareUpdateDetail("RESTARTING");
  Serial.printf("Firmware update verified: %s bytes=%u\n", manifest.version.c_str(), static_cast<unsigned>(manifest.size));
  delay(500);
  ESP.restart();
  vTaskDelete(nullptr);
}

void FirmwareUpdater::observe(JsonVariantConst command, bool registered, bool pairingMode, const String& tickerId) {
  if (!registered || pairingMode) {
    return;
  }
  JsonObjectConst update = command.as<JsonObjectConst>();
  if (update.isNull()) {
    return;
  }
  const String requested = update["version"] | "";
  if (!mini_firmware::safeVersion(requested)) {
    return;
  }
  if (requested == config_.version) {
    const String commandId = update["id"] | "";
    if (commandId.length() == 0 || commandId == firmwareUpdateReceiptCommandId) return;
    firmwareUpdateReceiptCommandId = commandId;
    firmwareUpdateAcknowledged = false;
    setFirmwareUpdateVersion(firmwareUpdateConfirmedVersion, sizeof(firmwareUpdateConfirmedVersion), requested);
    return;
  }
  char failedVersion[sizeof(firmwareUpdateFailedVersion)] = {};
  portENTER_CRITICAL(&firmwareUpdateMux);
  const bool taskRunning = firmwareUpdateTaskRunning;
  strncpy(failedVersion, firmwareUpdateFailedVersion, sizeof(failedVersion) - 1);
  portEXIT_CRITICAL(&firmwareUpdateMux);
  if (taskRunning) {
    return;
  }
  if (requested == failedVersion) {
    if (millis() - firmwareUpdateFailureAt < config_.retryBackoffMs) {
      return;
    }
    portENTER_CRITICAL(&firmwareUpdateMux);
    firmwareUpdateFailedVersion[0] = '\0';
    portEXIT_CRITICAL(&firmwareUpdateMux);
  }
  const String persistedFailure = preferences_.getString(FIRMWARE_FAILED_NVS_KEY, "");
  if (persistedFailure == requested) {
    setFirmwareUpdateDetail("RETRY BLOCKED");
    setFirmwareUpdateState(FIRMWARE_UPDATE_FAILED, 0, 0);
    firmwareUpdateFailureAt = millis();
    return;
  }
  char requestedBuffer[sizeof(firmwareUpdateRequestedVersion)] = {};
  setFirmwareUpdateVersion(requestedBuffer, sizeof(requestedBuffer), requested);
  portENTER_CRITICAL(&firmwareUpdateMux);
  strncpy(firmwareUpdateRequestedVersion, requestedBuffer, sizeof(firmwareUpdateRequestedVersion) - 1);
  firmwareUpdateRequestedVersion[sizeof(firmwareUpdateRequestedVersion) - 1] = '\0';
  firmwareUpdateTaskRunning = true;
  portEXIT_CRITICAL(&firmwareUpdateMux);
  setFirmwareUpdateDetail("CHECKING");
  setFirmwareUpdateState(FIRMWARE_UPDATE_CHECKING, 0, 0);
  tickerId_ = tickerId;
  if (xTaskCreatePinnedToCore(taskEntry, "firmware-update", 12288, this, 1, &firmwareUpdateTaskHandle, 0) != pdPASS) {
    finishFirmwareUpdateTask(false, "NO TASK");
  }
}

void FirmwareUpdater::initialize() {
  String pending = preferences_.getString(FIRMWARE_PENDING_NVS_KEY, "");
  pending.trim();
  if (mini_firmware::bootReceipt(pending, String(config_.version)) == mini_firmware::BootReceipt::Confirm) {
    pending.toCharArray(firmwareUpdateConfirmedVersion, sizeof(firmwareUpdateConfirmedVersion));
  } else if (mini_firmware::bootReceipt(pending, String(config_.version)) == mini_firmware::BootReceipt::Rollback) {
    preferences_.putString(FIRMWARE_FAILED_NVS_KEY, pending);
    preferences_.remove(FIRMWARE_PENDING_NVS_KEY);
    firmwareUpdateConfirmedVersion[0] = '\0';
    setFirmwareUpdateDetail("ROLLBACK");
    setFirmwareUpdateState(FIRMWARE_UPDATE_FAILED, 0, 0);
    firmwareUpdateFailureAt = millis();
    Serial.printf("Firmware rollback detected for %s\n", pending.c_str());
  }
}

void FirmwareUpdater::acknowledgeConfirmedFirmware(bool registered, const String& tickerId) {
  if (!firmwareUpdateBootValidated || firmwareUpdateAcknowledged ||
      firmwareUpdateConfirmedVersion[0] == '\0' || !registered ||
      WiFi.status() != WL_CONNECTED) {
    return;
  }
  const uint32_t now = millis();
  if (now - firmwareUpdateLastAckAt < 5000 || !worker_.available()) return;
  auto* job = new (std::nothrow) NetworkJob(NetworkKind::FirmwareAck);
  if (!job) return;
  job->url = (baseUrl_ + "/api/v2/tickers/") + tickerId + "/updates/ack";
  job->identity = firmwareUpdateConfirmedVersion;
  job->command = firmwareUpdateReceiptCommandId;
  JsonDocument request;
  request["version"] = job->identity;
  serializeJson(request, job->request);
  if (worker_.enqueue(job)) firmwareUpdateLastAckAt = now;
}

void FirmwareUpdater::applyAckResponse(const NetworkJob& job) {
  if (!mini_firmware::sameReceipt(job.identity, job.command, String(firmwareUpdateConfirmedVersion), firmwareUpdateReceiptCommandId)) return;
  JsonDocument response;
  PayloadReader reader(job.response.body.data(), job.response.body.size());
  const bool acknowledged = job.status == HTTP_CODE_OK && job.complete() &&
    !deserializeJson(response, reader) && response["acknowledged"].is<bool>() && response["acknowledged"].as<bool>();
  if (acknowledged) {
    firmwareUpdateAcknowledged = true;
    preferences_.remove(FIRMWARE_PENDING_NVS_KEY);
    firmwareUpdateConfirmedVersion[0] = '\0';
    Serial.println("Firmware boot confirmed and acknowledged");
  } else Serial.println("Firmware acknowledgement declined");
}

bool FirmwareUpdater::tick(uint32_t now, bool registered, const String& tickerId) {
  if (!firmwareUpdateBootChecked && now >= config_.bootValidationMs) {
    firmwareUpdateBootChecked = true;
    const esp_partition_t* running = esp_ota_get_running_partition();
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    const bool stateReady = running != nullptr &&
      esp_ota_get_state_partition(running, &state) == ESP_OK;
    if (firmwareUpdateConfirmedVersion[0] == '\0') {
      firmwareUpdateBootValidated = true;
    } else if (stateReady && state == ESP_OTA_IMG_PENDING_VERIFY) {
      firmwareUpdateBootValidated = esp_ota_mark_app_valid_cancel_rollback() == ESP_OK;
      if (firmwareUpdateBootValidated) {
        Serial.println("Firmware boot validation passed");
      } else {
        Serial.println("Firmware boot validation failed");
        setFirmwareUpdateDetail("BOOT VERIFY");
        setFirmwareUpdateState(FIRMWARE_UPDATE_FAILED, 0, 0);
        firmwareUpdateFailureAt = now;
      }
    } else if (stateReady && (state == ESP_OTA_IMG_VALID || state == ESP_OTA_IMG_UNDEFINED)) {
      firmwareUpdateBootValidated = true;
      Serial.println("Firmware boot was already validated");
    } else {
      Serial.println("Firmware boot state is not valid");
      setFirmwareUpdateDetail("BOOT STATE");
      setFirmwareUpdateState(FIRMWARE_UPDATE_FAILED, 0, 0);
      firmwareUpdateFailureAt = now;
    }
  }
  bool redraw = false;
  acknowledgeConfirmedFirmware(registered, tickerId);
  if (firmwareUpdateState == FIRMWARE_UPDATE_FAILED && now - firmwareUpdateFailureAt >= config_.failureDisplayMs) {
    setFirmwareUpdateState(FIRMWARE_UPDATE_IDLE, 0, 0);
    setFirmwareUpdateDetail("");
    redraw = true;
  }
  if (displayActive() && now - firmwareUpdateLastFrameAt >= 250) {
    firmwareUpdateLastFrameAt = now;
    redraw = true;
  }
  return redraw;
}
