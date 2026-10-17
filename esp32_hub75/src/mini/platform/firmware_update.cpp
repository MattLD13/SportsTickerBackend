#include "firmware_update.h"
#include "tls.h"
#include "http_diagnostics.h"
#include "../protocol/payload_reader.h"
#include <WiFi.h>
#include <mbedtls/md.h>

static constexpr char FIRMWARE_PENDING_NVS_KEY[] = "ota_trial";
static constexpr char FIRMWARE_FAILED_NVS_KEY[] = "ota_failed";
static_assert(sizeof(FIRMWARE_PENDING_NVS_KEY) <= 16, "NVS keys allow 15 characters");
static_assert(sizeof(FIRMWARE_FAILED_NVS_KEY) <= 16, "NVS keys allow 15 characters");


FirmwareUpdater::FirmwareUpdater(Preferences& preferences, NetworkGate& gate, NetworkWorker& worker,
                                 const String& backendUrl, const String& deviceToken, FirmwareUpdateConfig config)
    : preferences_(preferences), gate_(gate), worker_(worker), baseUrl_(backendUrl), deviceToken_(deviceToken), config_(config) {
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
  if (WiFi.status() != WL_CONNECTED || tickerId_.length() == 0) {
    return false;
  }
  NetworkLease lease(gate_, config_.httpTimeoutMs);
  if (!lease) return false;
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
    return false;
  }
  http.addHeader("X-Device-Token", deviceToken_);
  const int status = http.GET();
  if (status != HTTP_CODE_OK) {
    logSecureHttpError("Firmware manifest", status, client);
    http.end();
    return false;
  }
  String body = http.getString();
  http.end();
  return parseFirmwareManifest(body, requestedVersion, manifest);
}

bool FirmwareUpdater::downloadFirmware(const FirmwareManifestPayload& manifest) {
  NetworkLease lease(gate_, config_.httpTimeoutMs);
  if (!lease) return false;
  BackendTlsClient client;
  client.setTransferBudget(300000);
  configureTls(client);
  client.setTimeout(config_.httpTimeoutMs / 1000);
  client.setHandshakeTimeout(config_.httpTimeoutMs / 1000);
  HTTPClient http;
  http.useHTTP10(false);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(config_.httpTimeoutMs);
  if (!http.begin(client, manifest.binaryUrl)) {
    return false;
  }
  const int status = http.GET();
  const int contentLength = http.getSize();
  if (status != HTTP_CODE_OK || (contentLength >= 0 && static_cast<size_t>(contentLength) != manifest.size)) {
    logSecureHttpError("Firmware image", status, client);
    http.end();
    return false;
  }

  const esp_partition_t* target = esp_ota_get_next_update_partition(nullptr);
  struct Transfer {
    esp_ota_handle_t handle = 0;
    bool active = false;
    ~Transfer() { if (active) esp_ota_abort(handle); }
  } transfer;
  if (target == nullptr || manifest.size > target->size ||
      esp_ota_begin(target, manifest.size, &transfer.handle) != ESP_OK) {
    http.end();
    return false;
  }
  transfer.active = true;
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
    if (readCount == 0 || mbedtls_md_update(&digest, buffer, readCount) != 0 || esp_ota_write(transfer.handle, buffer, readCount) != ESP_OK) {
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
    return false;
  }
  const esp_err_t imageStatus = esp_ota_end(transfer.handle);
  transfer.active = false;
  http.end();
  if (imageStatus != ESP_OK || !confirmServerAttempt(manifest.version) ||
      !saveTrial(manifest.version, "pending_boot", "") || esp_ota_set_boot_partition(target) != ESP_OK) {
    preferences_.remove(FIRMWARE_PENDING_NVS_KEY);
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
    saveTrial(String(requested), "download_failed", strcmp(detail, "MANIFEST") == 0 ? "manifest" : "download");
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
    saveTrial(requested, firmwareUpdateBootValidated ? "installed" : "pending_boot", "");
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
  NetworkLease flash(gate_, 0, NetworkAccess::DeviceRequests);
  if (!flash) return;
  const String persistedFailure = preferences_.getString(FIRMWARE_FAILED_NVS_KEY, "");
  if (persistedFailure == requested) {
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
  firmwareUpdateReceiptCommandId = update["id"] | "";
  if (xTaskCreatePinnedToCore(taskEntry, "firmware-update", 12288, this, 1, &firmwareUpdateTaskHandle, 0) != pdPASS) {
    finishFirmwareUpdateTask(false, "NO TASK");
  }
}

void FirmwareUpdater::initialize() {
  NetworkLease flash(gate_, config_.httpTimeoutMs, NetworkAccess::DeviceRequests);
  if (!flash) return;
  const esp_partition_t* running = esp_ota_get_running_partition();
  if (running) strncpy(firmwareUpdateBootPartition, running->label, sizeof(firmwareUpdateBootPartition) - 1);
  esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
  firmwareUpdateBootStateError = running ? esp_ota_get_state_partition(running, &state) : ESP_ERR_NOT_FOUND;
  firmwareUpdateBootState = state;
  JsonDocument trial;
  const String stored = preferences_.getString(FIRMWARE_PENDING_NVS_KEY, "");
  if (stored.isEmpty()) return;
  if (deserializeJson(trial, stored)) { Serial.println("Invalid durable update receipt"); return; }
  resultVersion_ = trial["version"] | "";
  firmwareUpdateReceiptCommandId = trial["id"] | "";
  resultStatus_ = trial["status"] | "";
  resultReason_ = trial["reason"] | "";
  if (resultStatus_ == "pending_boot" &&
      mini_firmware::bootReceipt(resultVersion_, String(config_.version), false) == mini_firmware::BootReceipt::Rollback) {
      saveTrial(resultVersion_, "rolled_back", "boot_reset");
      preferences_.putString(FIRMWARE_FAILED_NVS_KEY, resultVersion_);
      setFirmwareUpdateDetail("ROLLBACK");
      setFirmwareUpdateState(FIRMWARE_UPDATE_FAILED, 0, 0);
      firmwareUpdateFailureAt = millis();
  }
}

bool FirmwareUpdater::saveTrial(const String& version, const char* status, const char* reason) {
  NetworkLease flash(gate_, config_.httpTimeoutMs, NetworkAccess::DeviceRequests);
  if (!flash) return false;
  JsonDocument trial;
  trial["version"] = version;
  trial["id"] = firmwareUpdateReceiptCommandId;
  trial["status"] = status;
  trial["reason"] = reason;
  String stored;
  serializeJson(trial, stored);
  if (preferences_.putString(FIRMWARE_PENDING_NVS_KEY, stored) == 0) return false;
  resultVersion_ = version;
  resultStatus_ = status;
  resultReason_ = reason;
  firmwareUpdateAcknowledged = false;
  return true;
}

bool FirmwareUpdater::confirmServerAttempt(const String& version) {
  BackendTlsClient client;
  configureTls(client);
  client.setTransferBudget(config_.httpTimeoutMs);
  HTTPClient http;
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(config_.httpTimeoutMs);
  if (!http.begin(client, baseUrl_ + "/api/v2/tickers/" + tickerId_ + "/updates/result")) return false;
  http.addHeader("X-Device-Token", deviceToken_);
  http.addHeader("Content-Type", "application/json");
  JsonDocument report;
  report["id"] = firmwareUpdateReceiptCommandId;
  report["version"] = version;
  report["running_version"] = config_.version;
  report["status"] = "started";
  report["reason"] = "";
  String body;
  serializeJson(report, body);
  const int status = http.POST(body);
  JsonDocument response;
  const bool accepted = status == HTTP_CODE_OK && !deserializeJson(response, http.getString()) &&
      response["accepted"] == true && response["quarantined"] == false;
  http.end();
  return accepted;
}

void FirmwareUpdater::reportFirmwareResult(bool registered, const String& tickerId) {
  if (transferActive() || !firmwareUpdateBootValidated || firmwareUpdateAcknowledged || resultVersion_.isEmpty() ||
      resultStatus_ == "pending_boot" || !registered || WiFi.status() != WL_CONNECTED) return;
  const uint32_t now = millis();
  if (now - firmwareUpdateLastAckAt < 5000 || !worker_.available()) return;
  auto* job = new (std::nothrow) NetworkJob(NetworkKind::FirmwareResult);
  if (!job) return;
  job->url = baseUrl_ + "/api/v2/tickers/" + tickerId + "/updates/result";
  job->identity = resultVersion_;
  job->command = firmwareUpdateReceiptCommandId + "|" + resultStatus_;
  JsonDocument report;
  report["id"] = firmwareUpdateReceiptCommandId;
  report["version"] = resultVersion_;
  report["running_version"] = config_.version;
  report["status"] = resultStatus_;
  report["reason"] = resultReason_;
  serializeJson(report, job->request);
  if (worker_.enqueue(job)) firmwareUpdateLastAckAt = now;
}

void FirmwareUpdater::applyResultResponse(const NetworkJob& job) {
  if (job.identity != resultVersion_ || job.command != firmwareUpdateReceiptCommandId + "|" + resultStatus_) return;
  JsonDocument response;
  PayloadReader reader(job.response.body.data(), job.response.body.size());
  if (job.status == HTTP_CODE_OK && job.complete() && !deserializeJson(response, reader) && response["accepted"] == true) {
    NetworkLease flash(gate_, 0, NetworkAccess::DeviceRequests);
    if (!flash) return;
    firmwareUpdateAcknowledged = true;
    preferences_.remove(FIRMWARE_PENDING_NVS_KEY);
    Serial.println("Firmware result saved by server");
  }
}

bool FirmwareUpdater::tick(uint32_t now, bool registered, const String& tickerId, bool displayHealthy) {
  if (!firmwareUpdateBootChecked && now >= config_.bootValidationMs) {
    NetworkLease flash(gate_, 0, NetworkAccess::DeviceRequests);
    if (!flash) return false;
    firmwareUpdateBootChecked = true;
    const esp_partition_t* running = esp_ota_get_running_partition();
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    firmwareUpdateBootStateError = running != nullptr ? esp_ota_get_state_partition(running, &state) : ESP_ERR_NOT_FOUND;
    firmwareUpdateBootState = state;
    const bool stateReady = firmwareUpdateBootStateError == ESP_OK;
    if (stateReady && state == ESP_OTA_IMG_PENDING_VERIFY) {
      if (!displayHealthy) {
        Serial.println("Firmware display validation failed. Rolling back.");
        esp_ota_mark_app_invalid_rollback_and_reboot();
        return true;
      }
      firmwareUpdateBootValidated = esp_ota_mark_app_valid_cancel_rollback() == ESP_OK;
      if (firmwareUpdateBootValidated) {
        firmwareUpdateBootState = ESP_OTA_IMG_VALID;
        Serial.println("Firmware boot validation passed");
      } else {
        Serial.println("Firmware boot validation failed");
        setFirmwareUpdateDetail("BOOT VERIFY");
        setFirmwareUpdateState(FIRMWARE_UPDATE_FAILED, 0, 0);
        firmwareUpdateFailureAt = now;
      }
    } else if (stateReady && (state == ESP_OTA_IMG_VALID || state == ESP_OTA_IMG_UNDEFINED)) {
      firmwareUpdateBootValidated = displayHealthy;
      Serial.println(displayHealthy ? "Firmware boot was already validated" : "Firmware display validation failed");
    } else {
      Serial.println("Firmware boot state is not valid");
      setFirmwareUpdateDetail("BOOT STATE");
      setFirmwareUpdateState(FIRMWARE_UPDATE_FAILED, 0, 0);
      firmwareUpdateFailureAt = now;
    }
  }
  if (resultStatus_ == "pending_boot" &&
      mini_firmware::bootReceipt(resultVersion_, String(config_.version), firmwareUpdateBootValidated) == mini_firmware::BootReceipt::Confirm)
    saveTrial(resultVersion_, "installed", "");
  bool redraw = false;
  reportFirmwareResult(registered, tickerId);
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
