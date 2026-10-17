bool updateFromPayload(const ResponseBody& body) {
  JsonObjectConst visibleItem;
  String visibleId;
  if (sportsMode && sportsFrameReady && selectedSportsItem(visibleItem)) visibleId = visibleItem["id"] | "";
  const bool accepted = payload.accept(body);
  lastDataJsonError = payload.error();
  lastDataJsonOffset = payload.offset();
  if (!accepted) {
    ++dataJsonFailures;
    Serial.printf("Data JSON error: %s bytes=%u offset=%u\n", payload.error(),
                  static_cast<unsigned>(body.size()), static_cast<unsigned>(payload.offset()));
    showFetchError("JSON ERROR");
    return false;
  }

  JsonObjectConst meta = payload.document()["meta"].as<JsonObjectConst>();
  JsonObjectConst pairing = meta["pairing"].as<JsonObjectConst>();
  const bool backendPaired = pairing["paired"] | false;
  pairingMode = !backendPaired;
  savePairingCode(pairing["code"] | "");
  if (backendPaired && blePairingStarted) {
    stopBlePairing();
  } else if (!backendPaired) {
    if (blePairingCharacteristic != nullptr && pairingCode.length() > 0) {
      blePairingCharacteristic->setValue(std::string(pairingCode.c_str()));
    }
  }
  JsonObjectConst settings = payload.document()["settings"].as<JsonObjectConst>();
  String mode = settings["mode"] | "sports";
  mode.toLowerCase();
  displayMode = mode;
  configuredTimezone = settings["timezone"] | DEFAULT_TIMEZONE;
  configuredTimezone.trim();
  if (configuredTimezone.length() == 0) configuredTimezone = DEFAULT_TIMEZONE;
  const bool wasSportsMode = sportsMode;
  sportsMode = displayMode == "sports";
  if (sportsMode && !wasSportsMode) {
    sportsFrameReady = false;
  }
  pageHoldSeconds = settings["scroll_speed"] | 0.03f;
  pageCount = sportsMode && !pairingMode ? countShownGames() : 0;
  if (visibleId.length() > 0 && sportsMode) {
    uint16_t index = 0;
    for (JsonObjectConst item : payload.document()["content"]["sports"].as<JsonArrayConst>()) {
      if (!shownItem(item)) continue;
      if (visibleId == (item["id"] | "")) { pageIndex = index; break; }
      ++index;
    }
  }
  if (pageIndex >= pageCount) pageIndex = 0;
  float brightness = settings["brightness"] | 100.0f;
  if (brightness < 0.0f) brightness = 0.0f;
  if (brightness > 100.0f) brightness = 100.0f;
  matrix->setBrightness8(static_cast<uint8_t>(brightness * 2.55f));
  const uint32_t newRotationSignature = sportsRotationSignature();
  const bool workingSetChanged = newRotationSignature != rotationSignature;
  if (workingSetChanged) {
    rotationSignature = newRotationSignature;
  }
  if (workingSetChanged || logoWorkingSetSignature != newRotationSignature) {
    logoWorkingSetSignature = newRotationSignature;
    prepareSportsLogoWorkingSet(pageIndex);
  }
  message = "";
  renderCurrent();
  firmwareUpdater.observe(payload.document()["meta"]["update"], registered, pairingMode, tickerId);
  return true;
}
// Owns retained V2 payload filtering and runtime state projection.

void applyDataResponse(const NetworkJob& job) {
  lastDataStatus = job.status;
  if (job.reusedConnection) ++reusedDataConnections;
  else ++freshDataConnections;
  lastDataExpired = job.expired;
  if (job.expired) ++dataDeadlineTimeouts;
  lastHeartbeatStatus = job.status;
  if (job.status == HTTP_CODE_OK && job.complete()) {
    heartbeatSucceeded = true;
    lastHeartbeatSuccessAt = millis();
    heartbeatFailures = 0;
  } else ++heartbeatFailures;
  lastDataExpectedBytes = job.expectedBytes;
  lastDataTransferBytes = job.transferredBytes;
  lastDataBytes = job.response.body.size();
  lastDataContentType = job.contentType;
  lastDataEncoding = job.contentEncoding;
  lastDataDurationMs = job.durationMs;
  lastDataGateWaitMs = job.gateWaitMs;
  lastDataHeadersMs = job.headersMs;
  lastDataBodyMs = job.bodyMs;
  Serial.printf("Data HTTP status: %d duration_ms=%lu bytes=%u\n", job.status,
                static_cast<unsigned long>(job.durationMs), static_cast<unsigned>(lastDataBytes));
  if (job.status == HTTP_CODE_NOT_FOUND) {
    registered = false;
    tickerId = dataUrl = "";
    pageCount = 0;
    message = "REGISTER";
    return;
  }
  if (job.status != HTTP_CODE_OK) { showFetchError("HTTP " + String(job.status)); return; }
  if (!job.complete()) { showFetchError("DATA TRANSFER"); return; }
  if (updateFromPayload(job.response.body)) lastDataSuccessAt = millis();
}
