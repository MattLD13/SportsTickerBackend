bool updateFromPayload(const ResponseBody& body) {
  // Keep the previous document until the complete response passes validation.
  JsonDocument filter;
  filter["meta"]["pairing"]["paired"] = true;
  filter["meta"]["pairing"]["code"] = true;
  filter["meta"]["update"]["version"] = true;
  filter["meta"]["update"]["id"] = true;
  filter["meta"]["update"]["expires_at"] = true;
  filter["settings"]["mode"] = true;
  filter["settings"]["timezone"] = true;
  filter["settings"]["scroll_speed"] = true;
  filter["settings"]["brightness"] = true;
  filter["content"]["sports"][0]["is_shown"] = true;
  filter["content"]["sports"][0]["id"] = true;
  filter["content"]["sports"][0]["identifier"] = true;
  filter["content"]["sports"][0]["key"] = true;
  for (const char* family : {"weather", "music", "flights", "airports", "stock", "clock"}) {
    filter["content"][family][0]["is_shown"] = true;
    filter["content"][family][0]["id"] = true;
    filter["content"][family][0]["data"] = true;
  }
  JsonObject filterGame = filter["content"]["sports"][0]["data"].to<JsonObject>();
  filterGame["sport"] = true;
  filterGame["league"] = true;
  filterGame["away_logo_asset"] = true;
  filterGame["home_logo_asset"] = true;
  filterGame["away_abbr"] = true;
  filterGame["home_abbr"] = true;
  filterGame["away_score"] = true;
  filterGame["home_score"] = true;
  filterGame["away_color"] = true;
  filterGame["home_color"] = true;
  filterGame["status"] = true;
  filterGame["state"] = true;
  filterGame["baseball_inning"] = true;
  filterGame["away_rank"] = true;
  filterGame["home_rank"] = true;
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
  filterSituation["powerPlayTeam"] = true;
  filterSituation["manpower"]["scrollLabel"] = true;
  filterSituation["manpower"]["powerPlayLabel"] = true;
  filterSituation["manpower"]["penalties"][0]["timeRemaining"] = true;
  filterSituation["manpower"]["penalties"][0]["jerseyNumber"] = true;
  filterSituation["shootout"] = true;
  filterSituation["isRedZone"] = true;
  filterSituation["emptyNet"] = true;
  filterSituation["emptyNetSide"] = true;
  filterSituation["red_cards"][0]["is_home"] = true;

  JsonDocument candidate;
  PayloadReader reader(body.data(), body.size());
  DeserializationError error = deserializeJson(candidate, reader, DeserializationOption::Filter(filter));
  lastDataJsonError = error ? error.c_str() : "";
  lastDataJsonOffset = reader.position();
  if (error) {
    ++dataJsonFailures;
    Serial.printf("Data JSON error: %s bytes=%u offset=%u\n", error.c_str(),
                  static_cast<unsigned>(body.size()), static_cast<unsigned>(reader.position()));
    showFetchError("JSON ERROR");
    return false;
  }

  // Commit only a complete filtered document. A transient HTTP or JSON error
  // keeps the last valid payload available for rendering and later refresh.
  JsonObjectConst visibleItem;
  String visibleId;
  if (sportsMode && sportsFrameReady && selectedSportsItem(visibleItem)) visibleId = visibleItem["id"] | "";
  payload = candidate;

  JsonObjectConst meta = payload["meta"].as<JsonObjectConst>();
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
  JsonObjectConst settings = payload["settings"].as<JsonObjectConst>();
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
    for (JsonObjectConst item : payload["content"]["sports"].as<JsonArrayConst>()) {
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
  firmwareUpdater.observe(payload["meta"]["update"], registered, pairingMode, tickerId);
  return true;
}
// Owns retained V2 payload filtering and runtime state projection.

void applyDataResponse(const NetworkJob& job) {
  lastDataStatus = job.status;
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
    tickerId = dataUrl = heartbeatUrl = "";
    pageCount = 0;
    message = "REGISTER";
    return;
  }
  if (job.status != HTTP_CODE_OK) { showFetchError("HTTP " + String(job.status)); return; }
  if (!job.complete()) { showFetchError("DATA TRANSFER"); return; }
  updateFromPayload(job.response.body);
}
