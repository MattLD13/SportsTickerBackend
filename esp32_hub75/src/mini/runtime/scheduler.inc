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
  if (!acquireNetwork(1000)) {
    return;
  }

  WiFiClientSecure client;
  client.setInsecure();
  client.setTimeout(8);
  client.setHandshakeTimeout(8);
  HTTPClient http;
  http.useHTTP10(true);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (!http.begin(client, heartbeatUrl)) {
    releaseNetwork();
    return;
  }

  JsonDocument heartbeat;
  heartbeat["metadata"]["build"] = MINI_FIRMWARE_VERSION;
  heartbeat["metadata"]["mode"] = displayMode;
  const char* modes[] = {"sports", "stock", "weather", "music", "flights", "airports", "clock"};
  for (uint8_t index = 0; index < sizeof(modes) / sizeof(modes[0]); ++index) {
    heartbeat["metadata"]["capabilities"][index] = modes[index];
  }
  heartbeat["metadata"]["uptime_seconds"] = millis() / 1000;
  String body;
  serializeJson(heartbeat, body);
  http.addHeader("Content-Type", "application/json");
  const int status = http.POST(body);
  logSecureHttpError("Heartbeat", status, client);
  http.end();
  releaseNetwork();
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
  if (!acquireNetwork(10000)) {
    Serial.println("Data fetch deferred: network busy");
    return false;
  }

  WiFiClientSecure client;
  client.setInsecure();
  client.setTimeout(8);
  client.setHandshakeTimeout(8);
  HTTPClient http;
  http.useHTTP10(true);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (!http.begin(client, dataUrl)) {
    releaseNetwork();
    showFetchError("HTTP SETUP");
    return false;
  }

  int status = http.GET();
  Serial.print("Data HTTP status: ");
  Serial.println(status);
  logSecureHttpError("Data", status, client);
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
    releaseNetwork();
    return false;
  }

  String body = http.getString();
  http.end();
  releaseNetwork();
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
  setupRuntimeLogoMemory();
  setupLogoCache();
  loadWifiCredentials();
  firmwareUpdateInitialize();
  setupMatrix();
  drawMessage("STARTING");
  logoCacheMutex = xSemaphoreCreateMutex();
  logoDecodeMutex = xSemaphoreCreateMutex();
  logoDownloadMutex = xSemaphoreCreateMutex();
  logoWorkMutex = xSemaphoreCreateMutex();
  logoStorageMutex = xSemaphoreCreateMutex();
  networkMutex = xSemaphoreCreateMutex();
  if (logoCacheMutex == nullptr || logoDecodeMutex == nullptr ||
      logoDownloadMutex == nullptr || logoWorkMutex == nullptr ||
      logoStorageMutex == nullptr || networkMutex == nullptr) {
    Serial.println("Logo synchronization setup failed");
  }
  if (logoCacheMutex != nullptr && logoDecodeMutex != nullptr &&
      logoDownloadMutex != nullptr && logoWorkMutex != nullptr &&
      logoStorageMutex != nullptr && networkMutex != nullptr) {
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
  firmwareUpdateTick(now);
  if (firmwareUpdateTransferActive()) {
    delay(1);
    return;
  }
  refreshPreparedClock();

  bool workerFinished = false;
  uint32_t workerGeneration = 0;
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  workerFinished = logoWorkerCompleted;
  if (workerFinished) {
    workerGeneration = logoWorkerGeneration;
    logoWorkerCompleted = false;
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  if (workerFinished) {
    if (logoPlanDisplayPending) {
      commitReadySportsLogoPlan(workerGeneration);
    }
    if (message.length() == 0) {
      renderCurrent();
    }
  }
  if (sportsMode && logoPlanDisplayPending && foregroundLogoPlanReady()) {
    if (commitReadySportsLogoPlan(logoPlanGeneration)) {
      if (message.length() == 0) {
        renderCurrent();
      }
    }
  }
  if (sportsMode && logoPlanDisplayPending && !sportsFrameReady &&
      assetLoadingStartedAt != 0 && now - assetLoadingStartedAt >= LOGO_STARTUP_TIMEOUT_MS) {
    pageIndex = logoPlanPageIndex;
    sportsFrameReady = true;
    assetsLoading = false;
    logoPlanDisplayPending = false;
    assetLoadingStartedAt = 0;
    lastPageAt = now;
    Serial.println("Logo startup timed out. Showing the scoreboard while downloads continue.");
    if (message.length() == 0) {
      renderCurrent();
    }
  }
  if (assetsLoading && !sportsFrameReady && now - lastAssetFrameAt >= LOGO_PROGRESS_REFRESH_MS) {
    lastAssetFrameAt = now;
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

    bool logoPlanBusy = false;
    if (logoWorkMutex != nullptr) {
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      logoPlanBusy = logoWorkerBusy || logoWorkerPending;
      xSemaphoreGive(logoWorkMutex);
    }

    // Page timing does not wait for background asset work.
    if (message.length() == 0 && sportsMode && sportsFrameReady &&
        pageCount > 1 && now - lastPageAt >= pageHoldMillis(pageHoldSeconds)) {
      const uint16_t nextPage = (pageIndex + 1) % pageCount;
      pageIndex = nextPage;
      lastPageAt = now;
      renderCurrent();
      if (!logoPlanBusy) {
        JsonObjectConst nextGame;
        if (selectedGame(nextGame) && !sportsGameAssetsCached(nextGame)) {
          prepareSportsLogoWorkingSet(pageIndex);
        }
      }
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
