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
bool firmwareUpdateAcknowledged = false;
uint32_t firmwareUpdateFailureAt = 0;
uint32_t firmwareUpdateLastFrameAt = 0;
TaskHandle_t firmwareUpdateTaskHandle = nullptr;

void setFirmwareUpdateDetail(const char* value) {
  portENTER_CRITICAL(&firmwareUpdateMux);
  strncpy(firmwareUpdateDetail, value == nullptr ? "ERROR" : value, sizeof(firmwareUpdateDetail) - 1);
  firmwareUpdateDetail[sizeof(firmwareUpdateDetail) - 1] = '\0';
  portEXIT_CRITICAL(&firmwareUpdateMux);
}

void setFirmwareUpdateState(FirmwareUpdateState state, uint32_t complete, uint32_t total) {
  portENTER_CRITICAL(&firmwareUpdateMux);
  firmwareUpdateState = state;
  firmwareUpdateComplete = complete;
  firmwareUpdateTotal = total;
  portEXIT_CRITICAL(&firmwareUpdateMux);
}

void setFirmwareUpdateVersion(char* destination, size_t destinationSize, const String& value) {
  value.substring(0, destinationSize - 1).toCharArray(destination, destinationSize);
}

bool copyFirmwareUpdateVersion(const char* source, String& destination) {
  char value[sizeof(firmwareUpdateRequestedVersion)] = {};
  portENTER_CRITICAL(&firmwareUpdateMux);
  strncpy(value, source, sizeof(value) - 1);
  portEXIT_CRITICAL(&firmwareUpdateMux);
  destination = value;
  destination.trim();
  return destination.length() > 0;
}

void firmwareUpdateDisplaySnapshot(uint8_t& state, uint32_t& complete, uint32_t& total, char* detail, size_t detailSize) {
  portENTER_CRITICAL(&firmwareUpdateMux);
  state = static_cast<uint8_t>(firmwareUpdateState);
  complete = firmwareUpdateComplete;
  total = firmwareUpdateTotal;
  strncpy(detail, firmwareUpdateDetail, detailSize - 1);
  detail[detailSize - 1] = '\0';
  portEXIT_CRITICAL(&firmwareUpdateMux);
}

bool firmwareUpdateDisplayActive() {
  portENTER_CRITICAL(&firmwareUpdateMux);
  const bool active = firmwareUpdateState != FIRMWARE_UPDATE_IDLE;
  portEXIT_CRITICAL(&firmwareUpdateMux);
  return active;
}

bool firmwareUpdateTransferActive() {
  portENTER_CRITICAL(&firmwareUpdateMux);
  const bool active = firmwareUpdateState == FIRMWARE_UPDATE_CHECKING ||
                      firmwareUpdateState == FIRMWARE_UPDATE_DOWNLOADING ||
                      firmwareUpdateState == FIRMWARE_UPDATE_INSTALLING;
  portEXIT_CRITICAL(&firmwareUpdateMux);
  return active;
}

bool parseSha256(const String& value, uint8_t* output) {
  if (value.length() != 64) {
    return false;
  }
  for (uint8_t index = 0; index < 32; ++index) {
    const char high = value[index * 2];
    const char low = value[index * 2 + 1];
    auto hexValue = [](char digit) -> int {
      if (digit >= '0' && digit <= '9') return digit - '0';
      if (digit >= 'a' && digit <= 'f') return digit - 'a' + 10;
      if (digit >= 'A' && digit <= 'F') return digit - 'A' + 10;
      return -1;
    };
    const int highValue = hexValue(high);
    const int lowValue = hexValue(low);
    if (highValue < 0 || lowValue < 0) {
      return false;
    }
    output[index] = static_cast<uint8_t>((highValue << 4) | lowValue);
  }
  return true;
}

bool isSafeFirmwareVersion(const String& value) {
  if (value.length() == 0 || value.length() >= 64) {
    return false;
  }
  for (size_t index = 0; index < value.length(); ++index) {
    const char character = value[index];
    if (!((character >= 'a' && character <= 'z') ||
          (character >= 'A' && character <= 'Z') ||
          (character >= '0' && character <= '9') ||
          character == '-' || character == '_' || character == '.')) {
      return false;
    }
  }
  return true;
}

bool constantTimeEqual(const uint8_t* left, const uint8_t* right, size_t length) {
  uint8_t difference = 0;
  for (size_t index = 0; index < length; ++index) {
    difference |= left[index] ^ right[index];
  }
  return difference == 0;
}

bool parseFirmwareManifest(const String& body, const String& requestedVersion, FirmwareManifestPayload& manifest) {
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
  if (!isSafeFirmwareVersion(requestedVersion) || manifest.version.length() == 0 || manifest.version != requestedVersion ||
      manifest.target != MINI_FIRMWARE_TARGET || manifest.hardware != MINI_FIRMWARE_HARDWARE ||
      !manifest.binaryUrl.startsWith("https://") || rawSize < static_cast<long long>(FIRMWARE_MIN_IMAGE_SIZE) ||
      rawSize > static_cast<long long>(FIRMWARE_MAX_IMAGE_SIZE) ||
      !parseSha256(checksum, manifest.sha256)) {
    return false;
  }
  manifest.size = static_cast<size_t>(rawSize);
  return true;
}

bool fetchFirmwareManifest(const String& requestedVersion, FirmwareManifestPayload& manifest) {
  if (WiFi.status() != WL_CONNECTED || tickerId.length() == 0 || !acquireNetwork(FIRMWARE_HTTP_TIMEOUT_MS)) {
    return false;
  }
  WiFiClientSecure client;
  client.setInsecure();
  client.setTimeout(FIRMWARE_HTTP_TIMEOUT_MS / 1000);
  client.setHandshakeTimeout(FIRMWARE_HTTP_TIMEOUT_MS / 1000);
  HTTPClient http;
  http.useHTTP10(true);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(FIRMWARE_HTTP_TIMEOUT_MS);
  String url = backendEndpoint("/api/v2/tickers/") + tickerId + "/firmware?version=" + requestedVersion;
  if (!http.begin(client, url)) {
    releaseNetwork();
    return false;
  }
  const int status = http.GET();
  if (status != HTTP_CODE_OK) {
    logSecureHttpError("Firmware manifest", status, client);
    http.end();
    releaseNetwork();
    return false;
  }
  String body = http.getString();
  http.end();
  releaseNetwork();
  return parseFirmwareManifest(body, requestedVersion, manifest);
}

void abortFirmwareWrite() {
  Update.abort();
}

bool verifyFirmwareImage(const esp_partition_t* target) {
  if (target == nullptr) {
    return false;
  }
  esp_image_metadata_t metadata = {};
  const esp_partition_pos_t position = {target->address, target->size};
  return esp_image_verify(ESP_IMAGE_VERIFY, &position, &metadata) == ESP_OK;
}

bool downloadFirmware(const FirmwareManifestPayload& manifest) {
  if (logoDownloadMutex != nullptr) {
    xSemaphoreTake(logoDownloadMutex, portMAX_DELAY);
  }
  if (!acquireNetwork(FIRMWARE_HTTP_TIMEOUT_MS)) {
    if (logoDownloadMutex != nullptr) xSemaphoreGive(logoDownloadMutex);
    return false;
  }
  WiFiClientSecure client;
  client.setInsecure();
  client.setTimeout(FIRMWARE_HTTP_TIMEOUT_MS / 1000);
  client.setHandshakeTimeout(FIRMWARE_HTTP_TIMEOUT_MS / 1000);
  HTTPClient http;
  http.useHTTP10(false);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(FIRMWARE_HTTP_TIMEOUT_MS);
  if (!http.begin(client, manifest.binaryUrl)) {
    if (logoDownloadMutex != nullptr) xSemaphoreGive(logoDownloadMutex);
    releaseNetwork();
    return false;
  }
  const int status = http.GET();
  const int contentLength = http.getSize();
  if (status != HTTP_CODE_OK || (contentLength >= 0 && static_cast<size_t>(contentLength) != manifest.size)) {
    logSecureHttpError("Firmware image", status, client);
    http.end();
    abortFirmwareWrite();
    if (logoDownloadMutex != nullptr) xSemaphoreGive(logoDownloadMutex);
    releaseNetwork();
    return false;
  }

  const esp_partition_t* target = esp_ota_get_next_update_partition(nullptr);
  if (target == nullptr || manifest.size > target->size || !Update.begin(manifest.size, U_FLASH)) {
    http.end();
    abortFirmwareWrite();
    if (logoDownloadMutex != nullptr) xSemaphoreGive(logoDownloadMutex);
    releaseNetwork();
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
      if (millis() - lastDataAt > FIRMWARE_HTTP_TIMEOUT_MS) {
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
  if (!valid || received != manifest.size || !constantTimeEqual(actualSha256, manifest.sha256, sizeof(actualSha256)) || !Update.end()) {
    http.end();
    abortFirmwareWrite();
    if (logoDownloadMutex != nullptr) xSemaphoreGive(logoDownloadMutex);
    releaseNetwork();
    return false;
  }
  http.end();
  const bool imageValid = verifyFirmwareImage(target);
  const bool bootSet = imageValid && esp_ota_set_boot_partition(target) == ESP_OK;
  if (!bootSet) {
    esp_ota_set_boot_partition(esp_ota_get_running_partition());
  }
  if (logoDownloadMutex != nullptr) xSemaphoreGive(logoDownloadMutex);
  releaseNetwork();
  if (!bootSet) {
    return false;
  }
  preferences.putString("ota_pending_version", manifest.version);
  return true;
}

void finishFirmwareUpdateTask(bool success, const char* detail) {
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

void firmwareUpdateTask(void*) {
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

void firmwareUpdateObserve(JsonVariantConst command) {
  if (!registered || pairingMode) {
    return;
  }
  JsonObjectConst update = command.as<JsonObjectConst>();
  if (update.isNull()) {
    return;
  }
  const String requested = update["version"] | "";
  if (!isSafeFirmwareVersion(requested) || requested == MINI_FIRMWARE_VERSION) {
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
    if (millis() - firmwareUpdateFailureAt < FIRMWARE_RETRY_BACKOFF_MS) {
      return;
    }
    portENTER_CRITICAL(&firmwareUpdateMux);
    firmwareUpdateFailedVersion[0] = '\0';
    portEXIT_CRITICAL(&firmwareUpdateMux);
  }
  const String persistedFailure = preferences.getString("ota_failed_version", "");
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
  if (xTaskCreatePinnedToCore(firmwareUpdateTask, "firmware-update", 12288, nullptr, 1, &firmwareUpdateTaskHandle, 0) != pdPASS) {
    finishFirmwareUpdateTask(false, "NO TASK");
  }
}

void firmwareUpdateInitialize() {
  String pending = preferences.getString("ota_pending_version", "");
  pending.trim();
  if (pending == MINI_FIRMWARE_VERSION) {
    pending.toCharArray(firmwareUpdateConfirmedVersion, sizeof(firmwareUpdateConfirmedVersion));
  } else if (pending.length() > 0) {
    preferences.putString("ota_failed_version", pending);
    preferences.remove("ota_pending_version");
    firmwareUpdateConfirmedVersion[0] = '\0';
    setFirmwareUpdateDetail("ROLLBACK");
    setFirmwareUpdateState(FIRMWARE_UPDATE_FAILED, 0, 0);
    firmwareUpdateFailureAt = millis();
    Serial.printf("Firmware rollback detected for %s\n", pending.c_str());
  }
}

void acknowledgeConfirmedFirmware() {
  if (!firmwareUpdateBootValidated || firmwareUpdateAcknowledged ||
      firmwareUpdateConfirmedVersion[0] == '\0' || !registered ||
      WiFi.status() != WL_CONNECTED) {
    return;
  }
  if (!acquireNetwork(1000)) {
    return;
  }
  WiFiClientSecure client;
  client.setInsecure();
  client.setTimeout(4);
  HTTPClient http;
  http.useHTTP10(true);
  http.setReuse(false);
  http.setConnectTimeout(3000);
  http.setTimeout(4000);
  const String url = backendEndpoint("/api/v2/tickers/") + tickerId + "/updates/ack";
  bool acknowledged = false;
  if (http.begin(client, url)) {
    JsonDocument request;
    request["version"] = firmwareUpdateConfirmedVersion;
    String body;
    serializeJson(request, body);
    http.addHeader("Content-Type", "application/json");
    const int status = http.POST(body);
    acknowledged = status == HTTP_CODE_OK;
    if (!acknowledged) {
      logSecureHttpError("Firmware acknowledgement", status, client);
    }
    http.end();
  }
  releaseNetwork();
  if (acknowledged) {
    firmwareUpdateAcknowledged = true;
    preferences.remove("ota_pending_version");
    firmwareUpdateConfirmedVersion[0] = '\0';
    Serial.println("Firmware boot confirmed and acknowledged");
  }
}

void firmwareUpdateTick(uint32_t now) {
  if (!firmwareUpdateBootChecked && now >= FIRMWARE_BOOT_VALIDATION_MS) {
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
  acknowledgeConfirmedFirmware();
  if (firmwareUpdateState == FIRMWARE_UPDATE_FAILED && now - firmwareUpdateFailureAt >= FIRMWARE_FAILURE_DISPLAY_MS) {
    setFirmwareUpdateState(FIRMWARE_UPDATE_IDLE, 0, 0);
    setFirmwareUpdateDetail("");
    renderCurrent();
  }
  if (firmwareUpdateDisplayActive() && now - firmwareUpdateLastFrameAt >= 250) {
    firmwareUpdateLastFrameAt = now;
    renderCurrent();
  }
}
