void applyConfiguredTimezone() {
  String timezoneSpec = configuredTimezone;
  timezoneSpec.trim();
  if (timezoneSpec.length() == 0 || timezoneSpec == DEFAULT_TIMEZONE || timezoneSpec == "US/Eastern") {
    timezoneSpec = DEFAULT_TIMEZONE_SPEC;
  }
  if (timezoneSpec != appliedTimezone) {
    configTzTime(timezoneSpec.c_str(), "pool.ntp.org", "time.nist.gov");
    appliedTimezone = timezoneSpec;
  }
}

void refreshPreparedClock() {
  applyConfiguredTimezone();
  if (displayMode != "clock") {
    preparedClockValid = false;
    return;
  }
  preparedClockValid = getLocalTime(&preparedClock, 50);
}

void sendHeartbeat() {
  if (WiFi.status() != WL_CONNECTED || !registered) {
    return;
  }

  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (!http.begin(heartbeatUrl)) {
    return;
  }

  JsonDocument heartbeat;
  heartbeat["metadata"]["build"] = "esp32s3-hub75";
  heartbeat["metadata"]["mode"] = displayMode;
  const char* modes[] = {"sports", "stock", "weather", "music", "flights", "airports", "clock"};
  for (uint8_t index = 0; index < sizeof(modes) / sizeof(modes[0]); ++index) {
    heartbeat["metadata"]["capabilities"][index] = modes[index];
  }
  heartbeat["metadata"]["uptime_seconds"] = millis() / 1000;
  String body;
  serializeJson(heartbeat, body);
  http.addHeader("Content-Type", "application/json");
  http.POST(body);
  http.end();
}

bool fetchData() {
  if (WiFi.status() != WL_CONNECTED) {
    showFetchError("WIFI LOST");
    return false;
  }
  if (!registered) {
    showFetchError("REGISTER");
    return false;
  }

  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (!http.begin(dataUrl)) {
    showFetchError("HTTP SETUP");
    return false;
  }

  int status = http.GET();
  Serial.print("Data HTTP status: ");
  Serial.println(status);
  if (status != HTTP_CODE_OK) {
    if (status == HTTP_CODE_NOT_FOUND) {
      registered = false;
      tickerId = "";
      dataUrl = "";
      heartbeatUrl = "";
      pageCount = 0;
      message = "REGISTER";
    } else {
      showFetchError("HTTP " + String(status));
    }
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();
  updateFromPayload(body);
  return message.length() == 0;
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);
  if (!scanForSavedWifi()) {
    Serial.println("Saved Wi-Fi was not listed. Trying direct association.");
    drawMessage("WIFI...");
  }
  if (!wifiStarted) {
    WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str());
    wifiStarted = true;
  } else {
    WiFi.reconnect();
  }
  uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) {
    if (!wifiPairingMode) drawMessage("WIFI...");
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi address: ");
    Serial.println(WiFi.localIP());
    appliedTimezone = "";
    applyConfiguredTimezone();
    wifiWaitStartedAt = 0;
    if (wifiPairingMode) {
      wifiPairingMode = false;
      pairingMode = false;
      setupCode = "";
    }
    message = "";
    renderCurrent();
  } else {
    if (wifiPairingMode) {
      renderCurrent();
    } else {
      showFetchError("WIFI LOST");
    }
  }
}

void applyPendingWifiCredentials() {
  char nextSsid[sizeof(pendingWifiSsid)] = {};
  char nextPassword[sizeof(pendingWifiPassword)] = {};
  portENTER_CRITICAL(&bleProvisioningMux);
  if (!pendingWifiReady) {
    portEXIT_CRITICAL(&bleProvisioningMux);
    return;
  }
  memcpy(nextSsid, pendingWifiSsid, sizeof(nextSsid));
  memcpy(nextPassword, pendingWifiPassword, sizeof(nextPassword));
  pendingWifiReady = false;
  memset(pendingWifiSsid, 0, sizeof(pendingWifiSsid));
  memset(pendingWifiPassword, 0, sizeof(pendingWifiPassword));
  portEXIT_CRITICAL(&bleProvisioningMux);

  wifiSsid = nextSsid;
  wifiPassword = nextPassword;
  saveWifiCredentials(wifiSsid, wifiPassword);
  if (blePairingStarted) {
    stopBlePairing();
  }
  wifiPairingMode = false;
  pairingMode = false;
  WiFi.disconnect();
  wifiStarted = false;
  wifiWaitStartedAt = millis();
  lastWifiRetryAt = millis() - WIFI_RETRY_INTERVAL_MS;
  message = "WIFI...";
  renderCurrent();
  Serial.print("Applying Wi-Fi network: ");
  Serial.println(wifiSsid);
}

void miniSetup() {
  Serial.begin(115200);
  Serial0.begin(115200);
  delay(5000);
  const uint32_t serialWaitStartedAt = millis();
  while (!Serial && millis() - serialWaitStartedAt < 5000) delay(10);
  Serial.printf("Reset reason: %d, free heap: %u\n", static_cast<int>(esp_reset_reason()), ESP.getFreeHeap());
  Serial0.printf("Reset reason: %d, free heap: %u\n", static_cast<int>(esp_reset_reason()), ESP.getFreeHeap());
  setupLogoCache();
  loadWifiCredentials();
  setupMatrix();
  drawMessage("STARTING");
  logoCacheMutex = xSemaphoreCreateMutex();
  logoDecodeMutex = xSemaphoreCreateMutex();
  logoDownloadMutex = xSemaphoreCreateMutex();
  logoWorkMutex = xSemaphoreCreateMutex();
  if (logoCacheMutex == nullptr || logoDecodeMutex == nullptr ||
      logoDownloadMutex == nullptr || logoWorkMutex == nullptr) {
    Serial.println("Logo synchronization setup failed");
  }
  if (logoCacheMutex != nullptr && logoDecodeMutex != nullptr &&
      logoDownloadMutex != nullptr && logoWorkMutex != nullptr) {
    const BaseType_t workerResult = xTaskCreatePinnedToCore(
      logoWorkerTask, "logo-worker", 8192, nullptr, 1, &logoWorkerHandle, 0
    );
    if (workerResult != pdPASS || logoWorkerHandle == nullptr) {
      logoWorkerHandle = nullptr;
      Serial.println("Logo worker creation failed");
    }
  } else {
    Serial.println("Logo worker creation failed");
  }
  if (FORCE_PAIRING_TEST) {
    startPairingMode();
    lastWifiRetryAt = millis();
  } else if (SOLID_COLOR_TEST) {
    // Keep the ticker startup below for the next test. The color test isolates panel output.
    drawSolidColorTest();
    lastSolidColorAt = millis();
  } else {
    wifiWaitStartedAt = millis();
    lastWifiRetryAt = millis() - WIFI_RETRY_INTERVAL_MS;
    connectWifi();
    lastFetchAt = millis() - FETCH_INTERVAL_MS;
    lastHeartbeatAt = millis() - HEARTBEAT_INTERVAL_MS;
    lastRegisterAt = millis() - REGISTER_INTERVAL_MS;
    lastPageAt = millis();
  }
}

void miniTick() {
  const uint32_t now = millis();
  refreshPreparedClock();

  bool workerFinished = false;
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  workerFinished = logoWorkerCompleted;
  if (workerFinished) {
    logoWorkerCompleted = false;
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  if (workerFinished) {
    message = "";
    renderCurrent();
  }

  if (now - lastDebugLogAt >= 1000) {
    lastDebugLogAt = now;
    Serial.printf("Heartbeat ms=%lu wifi=%d pairing=%d ble=%d heap=%u\n",
                  static_cast<unsigned long>(now), WiFi.status(), wifiPairingMode,
                  blePairingStarted, ESP.getFreeHeap());
    Serial0.printf("Heartbeat ms=%lu wifi=%d pairing=%d ble=%d heap=%u\n",
                   static_cast<unsigned long>(now), WiFi.status(), wifiPairingMode,
                   blePairingStarted, ESP.getFreeHeap());
  }

  if (SOLID_COLOR_TEST) {
    if (now - lastSolidColorAt >= SOLID_COLOR_INTERVAL_MS) {
      lastSolidColorAt = now;
      drawSolidColorTest();
    }
    return;
  } else {
    applyPendingWifiCredentials();

    if (wifiPairingMode) {
      return;
    }

    if (WiFi.status() != WL_CONNECTED && wifiWaitStartedAt == 0) {
      wifiWaitStartedAt = now;
    }
    if (WiFi.status() != WL_CONNECTED && !wifiPairingMode && now - wifiWaitStartedAt >= WIFI_PAIRING_TIMEOUT_MS) {
      startPairingMode();
    }

    if (wifiPairingMode) {
      return;
    }

    if (WiFi.status() != WL_CONNECTED && !wifiPairingMode && now - lastWifiRetryAt >= WIFI_RETRY_INTERVAL_MS) {
      lastWifiRetryAt = now;
      connectWifi();
    }

    // Rotate before network work so a due page cannot wait behind a refresh.
    if (message.length() == 0 && pageCount > 1 && now - lastPageAt >= pageHoldMillis(pageHoldSeconds)) {
      pageIndex = (pageIndex + 1) % pageCount;
      prepareSportsLogoWorkingSet();
      renderCurrent();
      lastPageAt = millis();
    }

    if (WiFi.status() == WL_CONNECTED && !registered && now - lastRegisterAt >= REGISTER_INTERVAL_MS) {
      lastRegisterAt = now;
      registerDevice();
    }

    if (registered && now - lastFetchAt >= FETCH_INTERVAL_MS) {
      lastFetchAt = now;
      fetchData();
    }

    if (now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
      lastHeartbeatAt = now;
      sendHeartbeat();
    }

    bool loading = false;
    uint16_t complete = 0;
    uint16_t total = 0;
    logoProgressSnapshot(loading, complete, total);
    if (loading && now - lastAssetFrameAt >= 250) {
      lastAssetFrameAt = now;
      drawDownloadingProgress(complete, total);
    }

    if (message.length() > 0) {
      if (now - lastMessageAt >= MESSAGE_REFRESH_MS) {
        lastMessageAt = now;
        drawMessage(message);
      }
      return;
    }

  }
}
// Owns polling, heartbeat, Wi-Fi scheduling, startup, and the Arduino tick.
