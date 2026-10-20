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

bool fetchData() {
  if (WiFi.status() != WL_CONNECTED || wifiPairingMode || !registered || !networkWorker.available()) return false;
  JsonDocument heartbeat;
  heartbeat["metadata"]["build"] = MINI_FIRMWARE_VERSION;
  heartbeat["metadata"]["mode"] = displayMode;
  const char* modes[] = {"sports", "stock", "weather", "music", "flights", "airports", "clock"};
  for (uint8_t index = 0; index < sizeof(modes) / sizeof(modes[0]); ++index) {
    heartbeat["metadata"]["capabilities"][index] = modes[index];
  }
  heartbeat["metadata"]["uptime_seconds"] = millis() / 1000;
  if (std::isfinite(deviceSensors.temperatureC())) heartbeat["metadata"]["temperature_c"] = deviceSensors.temperatureC();
  else heartbeat["metadata"]["temperature_c"] = nullptr;
  heartbeat["metadata"]["mini_sprite_protocol"] = 1;
  heartbeat["metadata"]["wifi_available"] = WiFi.status() == WL_CONNECTED;
  heartbeat["metadata"]["wifi_setup_active"] = wifiPairingMode;
  heartbeat["metadata"]["sprite_cache"]["flash_hits"] = spriteAssets.metrics().flashHits;
  heartbeat["metadata"]["sprite_cache"]["downloads"] = spriteAssets.metrics().downloads;
  heartbeat["metadata"]["sprite_cache"]["invalid_files"] = spriteAssets.metrics().invalidFiles;
  heartbeat["metadata"]["sprite_cache"]["evictions"] = spriteAssets.metrics().evictions;
  heartbeat["metadata"]["sprite_cache"]["heap_before_tls"] = spriteAssets.metrics().heapBeforeTls;
  heartbeat["metadata"]["sprite_cache"]["heap_during_tls"] = spriteAssets.metrics().heapDuringTls;
  heartbeat["metadata"]["sprite_cache"]["heap_after_tls"] = spriteAssets.metrics().heapAfterTls;
  heartbeat["metadata"]["sprite_cache"]["largest_during_tls"] = spriteAssets.metrics().largestDuringTls;
  populateDisplayMetrics(heartbeat["metadata"]["display_metrics"].to<JsonObject>(), false);
  String body;
  serializeJson(heartbeat, body);
  auto* job = new (std::nothrow) NetworkJob(NetworkKind::DevicePoll);
  if (!job) return false;
  job->url = dataUrl;
  job->request = body;
  job->budgetMs = nextPollBudgetMs;
  const bool queued = networkWorker.enqueue(job);
  if (queued) nextPollBudgetMs = TransferDeadline::DefaultBudgetMs;
  return queued;
}


void pollMiniSerial();

void serviceWifi(uint32_t now) {
  if (networkReconnectRequested) {
    networkReconnectRequested = false;
    ++networkReconnects;
    wifiStation.renew(now);
  }
  const bool connected = wifiStation.tick(now, networkWorker.available() && !firmwareUpdater.transferActive());
  if (connected) {
    if (!wifiWasConnected) {
      portENTER_CRITICAL(&bleProvisioningMux);
      const bool handoffPending = pendingWifiReady && !pendingWifiResultRead;
      portEXIT_CRITICAL(&bleProvisioningMux);
      if (handoffPending) return;
      if (wifiPairingMode && blePairingStarted) stopBlePairing();
      if (wifiPairingMode && blePairingStarted) return;
      if (wifiPairingMode) { wifiPairingMode = false; pairingMode = false; setupCode = ""; }
      wifiWasConnected = true;

      appliedTimezone = "";
      applyConfiguredTimezone();
      lastFetchAt = now - FETCH_INTERVAL_MS;
      message = "";
      Serial.println("Wi-Fi address acquired. Data polling resumes.");
      renderCurrent();
    }
    if (!wifiKnownWorking) {
      NetworkLease flash(networkGate, 0, NetworkAccess::DeviceRequests);
      if (flash && preferences.putBool("wifi_confirmed", true)) wifiKnownWorking = true;
    }
    wifiWaitStartedAt = 0;
  } else {
    wifiWasConnected = false;
    if (wifiWaitStartedAt == 0) wifiWaitStartedAt = now;
    if (!pairingMode) {
      message = wifiKnownWorking ? "RECONNECTING" : "JOINING WIFI";
      messageKind = wifiKnownWorking ? ticker_ui::SystemKind::Offline : ticker_ui::SystemKind::Connecting;
    }
    if (wifiStation.setupReady() && !wifiPairingMode) startPairingMode();
    if (!wifiKnownWorking && !wifiPairingMode && now - wifiWaitStartedAt >= WIFI_PAIRING_TIMEOUT_MS) wifiStation.requestSetup();
  }
}

void applyPendingWifiCredentials(uint32_t now) {
  portENTER_CRITICAL(&bleProvisioningMux);
  const bool pending = pendingWifiReady && pendingWifiResultRead;
  portEXIT_CRITICAL(&bleProvisioningMux);
  if (!pending) return;
  NetworkLease flash(networkGate, 0);
  if (!flash) return;
  char nextSsid[sizeof(pendingWifiSsid)] = {};
  char nextPassword[sizeof(pendingWifiPassword)] = {};
  portENTER_CRITICAL(&bleProvisioningMux);
  if (!pendingWifiReady || !pendingWifiResultRead) {
    portEXIT_CRITICAL(&bleProvisioningMux);
    return;
  }
  memcpy(nextSsid, pendingWifiSsid, sizeof(nextSsid));
  memcpy(nextPassword, pendingWifiPassword, sizeof(nextPassword));
  pendingWifiReady = false;
  pendingWifiResultRead = false;
  memset(pendingWifiSsid, 0, sizeof(pendingWifiSsid));
  memset(pendingWifiPassword, 0, sizeof(pendingWifiPassword));
  portEXIT_CRITICAL(&bleProvisioningMux);

  networkReconnectRequested = false;
  networkRecovery = NetworkRecovery{};
  wifiSsid = nextSsid;
  wifiPassword = nextPassword;
  saveWifiCredentials(wifiSsid, wifiPassword);
  if (blePairingStarted) stopBlePairing();
  wifiPairingMode = false;
  setupCode = "";
  pairingMode = false;
  wifiStation.configure(wifiSsid, wifiPassword, now);
  wifiWasConnected = false;
  wifiWaitStartedAt = now;
  message = "JOINING WIFI";
  messageKind = ticker_ui::SystemKind::Connecting;
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
  pinMode(PIN_BUTTON_UP, INPUT_PULLUP);
  pinMode(PIN_BUTTON_DOWN, INPUT_PULLUP);
  networkGate.begin();
  spriteAssets.begin();
  Serial.printf("Music artwork RAM %s\n", musicArtwork.begin() ? "ready" : "unavailable");
  Serial.printf("Mini firmware: %s sprite_protocol=1\n", MINI_FIRMWARE_VERSION);
  loadWifiCredentials();
  firmwareUpdater.initialize();
  setupMatrix();
  deviceSensors.begin();
  deviceSensors.tick(millis());
  deviceCredentials.load();
  drawSystemNotice(deviceCredentials.ready() ? ticker_ui::SystemKind::Startup : ticker_ui::SystemKind::DeviceKey, deviceCredentials.ready() ? "PLEASE WAIT" : "AUTH REQUIRED");
  logoWorkMutex = xSemaphoreCreateMutex();
  networkWorker.begin();
  if (!spriteAssets.ready() || logoWorkMutex == nullptr || !networkGate.ready()) {
    Serial.println("Sprite synchronization setup failed");
  }
  if (spriteAssets.ready() && logoWorkMutex != nullptr && networkGate.ready()) {
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
  pollMiniSerial();
  if (logoWorkbenchMode) {
    Serial.println("Logo workbench active. Wi-Fi polling is paused.");
    return;
  }
  if (!deviceCredentials.ready()) return;
  if (!SOLID_COLOR_TEST) wifiStation.begin(wifiSsid, wifiPassword);
  if (FORCE_PAIRING_TEST) {
    wifiStation.requestSetup();
  } else if (SOLID_COLOR_TEST) {
    // Keep the ticker startup below for the next test. The color test isolates panel output.
    drawSolidColorTest();
    lastSolidColorAt = millis();
  } else {
    wifiWaitStartedAt = millis();
    lastFetchAt = millis() - FETCH_INTERVAL_MS;
    lastRegisterAt = millis() - REGISTER_INTERVAL_MS;
  }
}

void renderLogoWorkbenchFrame() {
  beginFrame("workbench");
  matrix->fillScreen(color(0, 0, 0));
  for (uint16_t y = 0; y < 32; ++y) {
    for (uint16_t x = 0; x < 64; ++x) {
      const size_t offset = (static_cast<size_t>(y) * 64 + x) * 3;
      matrix->drawPixelRGB888(x, y, logoWorkbenchFrameRgb[offset], logoWorkbenchFrameRgb[offset + 1], logoWorkbenchFrameRgb[offset + 2]);
    }
  }
  presentFrame();
}

void processMiniSerialCommand(Stream* input, const String& command) {
  if (command == "STATS") {
    JsonDocument document;
    document["v"] = 1;
    document["firmware"] = MINI_FIRMWARE_VERSION;
    populateDisplayMetrics(document["display"].to<JsonObject>(), true);
    writeDiagnosticJson(*input, "MINI_STATS:", document);
    return;
  }
  if (command == "CHECKAUTH" || command == "CHECKAUTH:COLD") {
    if (!registered || !networkWorker.available()) { input->print("MINI_AUTH_CHECK:BUSY\n"); return; }
    auto* job = new (std::nothrow) NetworkJob(NetworkKind::AuthCheck);
    if (!job) { input->print("MINI_AUTH_CHECK:BUSY\n"); return; }
    job->url = backendEndpoint("/api/v2/tickers/") + tickerId + "/device-credential/verify";
    job->request = "{}";
    job->requireFreshConnection = command.endsWith(":COLD");
    networkWorker.enqueue(job);
    return;
  }
  if (command.startsWith("AUTHSET:")) {
    NetworkLease flash(networkGate, 0, NetworkAccess::DeviceRequests);
    if (!flash) { input->print("MINI_AUTH:BUSY\n"); return; }
    if (firmwareUpdater.transferActive()) { input->print("MINI_AUTH:BUSY\n"); return; }
    if (!deviceCredentials.replace(command.substring(8))) { input->print("MINI_AUTH:REJECTED\n"); return; }
    input->print("MINI_AUTH:STORED\n");
    input->flush();
    ESP.restart();
    return;
  }
  if (command == "CAPTURE") { startFrameCapture(*input); return; }
  if (command == "WIFITEST:45000") {
    if (firmwareUpdater.transferActive()) { input->print("MINI_WIFI_TEST:BUSY\n"); return; }
    wifiStation.pauseForTest(millis(), 45000);
    input->print("MINI_WIFI_TEST:STARTED\n");
    return;
  }
  if (command == "TIMEOUTTEST:1") {
    if (firmwareUpdater.transferActive()) { input->print("MINI_TIMEOUT_TEST:BUSY\n"); return; }
    nextPollBudgetMs = 1;
    input->print("MINI_TIMEOUT_TEST:STARTED\n");
    return;
  }
  if (command == "WIFISETUP") { wifiStation.requestSetup(); input->print("MINI_WIFI_SETUP:STARTED\n"); return; }
  if (command == "WIFIRETRY") {
    if (blePairingStarted) stopBlePairing();
    if (blePairingStarted) { input->print("MINI_WIFI_SETUP:BUSY\n"); return; }
    wifiPairingMode = false;
    pairingMode = false;
    setupCode = "";
    wifiStation.leaveSetup(millis());
    input->print("MINI_WIFI_SETUP:RECOVERING\n");
    return;
  }
  if (command == "CHECKTLS") {
    NetworkLease flash(networkGate, 5000);
    if (!flash) { input->print("MINI_TLS_CHECK:BUSY\n"); return; }
    const char* path = "/tls-close-check.tmp";
    File file = LittleFS.open(path, "w+");
    if (!file) { input->print("MINI_TLS_CHECK:NO_FILE\n"); return; }
    bool valid = true;
    for (unsigned attempt = 0; attempt < 16; ++attempt) {
      TlsClient client;
      client.stop();
      valid = valid && client.fd() == -1;
      client.stop();
      valid = valid && client.fd() == -1;
    }
    const uint8_t expected[] = {0x54, 0x4c, 0x53};
    uint8_t actual[sizeof(expected)] = {};
    valid = valid && file.write(expected, sizeof(expected)) == sizeof(expected);
    file.flush();
    valid = valid && file.seek(0) && file.read(actual, sizeof(actual)) == sizeof(actual);
    valid = valid && memcmp(expected, actual, sizeof(actual)) == 0;
    file.close();
    LittleFS.remove(path);
    input->print(valid ? "MINI_TLS_CHECK:PASS\n" : "MINI_TLS_CHECK:FAIL\n");
    return;
  }
  if (command == "PING") {
    logoWorkbenchMode = true;
    beginFrame("workbench");
    matrix->fillScreen(color(0, 0, 0));
    presentFrame();
    input->printf("MINI_READY:%s\n", MINI_FIRMWARE_VERSION);
    return;
  }
  if (command == "EXITLOGO") {
    logoWorkbenchMode = false;
    input->println("LOGO_EXITED");
    renderCurrent();
    return;
  }
  if (!command.startsWith("FRAME64:")) return;
  const String encoded = command.substring(8);
  size_t decodedLength = 0;
  const size_t expectedLength = sizeof(logoWorkbenchFrameRgb);
  const int result = mbedtls_base64_decode(
    logoWorkbenchFrameRgb, expectedLength, &decodedLength,
    reinterpret_cast<const unsigned char*>(encoded.c_str()), encoded.length()
  );
  if (result != 0 || decodedLength != expectedLength) {
    input->println("FRAME_ERROR");
    return;
  }
  logoWorkbenchMode = true;
  renderLogoWorkbenchFrame();
  uint32_t checksum = 2166136261UL;
  for (const uint8_t value : logoWorkbenchFrameRgb) {
    checksum = (checksum ^ value) * 16777619UL;
  }
  input->printf("FRAME_OK:%08lx\n", static_cast<unsigned long>(checksum));
}


void pollMiniSerial() {
  static String commands[2];
  static bool discard[2] = {};
  Stream* inputs[] = {&Serial, &Serial0};
  for (unsigned index = 0; index < 2; ++index) {
    Stream* input = inputs[index];
    unsigned budget = 256;
    while (budget-- && input->available()) {
      const int value = input->read();
      if (value < 0) break;
      if (value == '\r') continue;
      if (value == '\n') {
        if (!discard[index]) processMiniSerialCommand(input, commands[index]);
        commands[index] = String();
        discard[index] = false;
      } else if (!discard[index]) {
        if (commands[index].length() >= 8300) {
          commands[index] = String();
          discard[index] = true;
          input->println("MINI_ERROR:command_too_long");
        } else commands[index] += static_cast<char>(value);
      }
    }
  }
  pumpFrameCapture();
}

void miniTick() {
  displayMetrics.loop(esp_timer_get_time());
  deviceSensors.tick(millis());
  pollMiniSerial();
  if (logoWorkbenchMode) {
    delay(1);
    return;
  }
  if (matrix->getRotation() != deviceSensors.rotation()) {
    matrix->setOrientation(deviceSensors.rotation());
    renderCurrent();
  }
  pollNetworkResults();
  const uint32_t now = millis();
  if (!deviceCredentials.ready()) {
    firmwareUpdater.tick(now, false, tickerId, false);
    delay(10);
    return;
  }
  serviceWifi(now);
  static uint32_t buttonsAt = 0;
  static bool buttonsHandled = false;
  if (digitalRead(PIN_BUTTON_UP) == LOW && digitalRead(PIN_BUTTON_DOWN) == LOW) {
    if (!buttonsAt) buttonsAt = now;
    if (!buttonsHandled && now - buttonsAt >= 3000 && !firmwareUpdater.transferActive()) {
      processMiniSerialCommand(&Serial, wifiPairingMode ? "WIFIRETRY" : "WIFISETUP");
      buttonsHandled = true;
    }
  } else { buttonsAt = 0; buttonsHandled = false; }
  if (firmwareUpdater.tick(now, registered, tickerId, matrix && displayMetrics.frames > 0 && matrix->calculated_refresh_rate >= 100)) renderCurrent();
  if (firmwareUpdater.transferActive()) {
    if (now - lastAnimatedFrameAt >= 100) { lastAnimatedFrameAt = now; renderCurrent(); }
    delay(1);
    return;
  }
  refreshPreparedClock();
  if (displayMode == "clock" && !pairingMode && message.length() == 0 && !firmwareUpdater.displayActive() &&
      (preparedClockValid != lastPresentedClockReady ||
       (preparedClockValid && preparedClock.tm_sec != lastPresentedClockSecond))) {
    renderCurrent();
  }

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
  if (((displayMode == "music" || displayMode == "weather" || displayMode == "airports" || (displayMode == "clock" && !preparedClockValid)) || pairingMode ||
       message.length() > 0 || firmwareUpdater.displayActive() || (assetsLoading && !sportsFrameReady)) &&
      now - lastAnimatedFrameAt >= 100) {
    lastAnimatedFrameAt = now;
    renderCurrent();
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
    applyPendingWifiCredentials(now);

    if (wifiPairingMode) {
      return;
    }

    bool logoPlanBusy = false;
    if (logoWorkMutex != nullptr) {
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      logoPlanBusy = logoWorkerBusy || logoWorkerPending;
      xSemaphoreGive(logoWorkMutex);
    }

    // Page timing does not wait for background asset work.
    bool retrySprites = false;
    if (logoWorkMutex != nullptr) {
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      retrySprites = !logoPlanBusy && spriteRetryDueAt != 0 && static_cast<int32_t>(now - spriteRetryDueAt) >= 0;
      if (retrySprites) spriteRetryDueAt = 0;
      xSemaphoreGive(logoWorkMutex);
    }
    if (retrySprites && sportsMode && !pairingMode) prepareSportsLogoWorkingSet(pageIndex);
    if (message.length() == 0 && sportsMode && sportsFrameReady &&
        pageCount > 1 && displayMetrics.rotationDue(esp_timer_get_time())) {
      const uint16_t nextPage = (pageIndex + 1) % pageCount;
      pageIndex = nextPage;
      prepareSportsLogoWorkingSet(pageIndex);
      renderCurrent();
    }

    if (WiFi.status() == WL_CONNECTED && !registered && now - lastRegisterAt >= REGISTER_INTERVAL_MS) {
      if (registerDevice()) lastRegisterAt = now;
    }
    const bool prefetch = sportsMode && displayMetrics.prefetchDue(esp_timer_get_time(), 1000) &&
                          lastPrefetchPageUs != displayMetrics.startedUs;
    if (registered && (prefetch || now - lastFetchAt >= FETCH_INTERVAL_MS)) {
      if (fetchData()) {
        lastFetchAt = now;
        if (prefetch) lastPrefetchPageUs = displayMetrics.startedUs;
      }
    }

    if (message.length() > 0) {
      if (now - lastMessageAt >= MESSAGE_REFRESH_MS) {
        lastMessageAt = now;
        drawSystemNotice(messageKind, message);
      }
      return;
    }

  }
}
// Owns polling, heartbeat, Wi-Fi scheduling, startup, and the Arduino tick.
