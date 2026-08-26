void updateFromPayload(const String& body) {
  // Parse directly into the retained document to avoid duplicating the payload tree.
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
  filter["content"]["weather"][0]["is_shown"] = true;
  filter["content"]["weather"][0]["data"] = true;
  filter["content"]["music"][0]["is_shown"] = true;
  filter["content"]["music"][0]["data"] = true;
  filter["content"]["flights"][0]["is_shown"] = true;
  filter["content"]["flights"][0]["data"] = true;
  filter["content"]["airports"][0]["is_shown"] = true;
  filter["content"]["airports"][0]["data"] = true;
  filter["content"]["stock"][0]["is_shown"] = true;
  filter["content"]["stock"][0]["data"] = true;
  filter["content"]["clock"][0]["is_shown"] = true;
  filter["content"]["clock"][0]["data"] = true;
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

  JsonDocument candidate;
  DeserializationError error = deserializeJson(candidate, body, DeserializationOption::Filter(filter));
  if (error) {
    Serial.print("Data JSON error: ");
    Serial.print(error.c_str());
    Serial.print(" bytes=");
    Serial.println(body.length());
    showFetchError("JSON ERROR");
    return;
  }

  // Commit only a complete filtered document. A transient HTTP or JSON error
  // keeps the last valid payload available for rendering and later refresh.
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
  float brightness = settings["brightness"] | 100.0f;
  if (brightness < 0.0f) brightness = 0.0f;
  if (brightness > 100.0f) brightness = 100.0f;
  matrix->setBrightness8(static_cast<uint8_t>(brightness * 2.55f));
  const uint32_t newRotationSignature = sportsRotationSignature();
  const bool workingSetChanged = newRotationSignature != rotationSignature;
  const bool keepVisibleSportsFrame = sportsMode && sportsFrameReady;
  if (workingSetChanged) {
    rotationSignature = newRotationSignature;
  }
  if (workingSetChanged || logoWorkingSetSignature != newRotationSignature) {
    logoWorkingSetSignature = newRotationSignature;
    prepareSportsLogoWorkingSet(sportsMode ? 0 : pageIndex);
  }
  message = "";
  const bool newSportsPlanReady = !sportsMode || foregroundLogoPlanReady();
  if (!keepVisibleSportsFrame || !workingSetChanged || !sportsMode || newSportsPlanReady) {
    renderCurrent();
  }
  if (workingSetChanged) {
    lastPageAt = millis();
  }
  firmwareUpdateObserve(payload["meta"]["update"]);
}
// Owns retained V2 payload filtering and runtime state projection.
