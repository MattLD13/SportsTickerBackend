void describePane(JsonObject out, const mini_display::Pane& pane) {
  out["kind"] = pane.kind;
  out["item_id"] = pane.item;
  out["index"] = pane.index;
  out["count"] = pane.count;
  out["target_ms"] = pane.targetMs;
}

void populateDisplayMetrics(JsonObject out, bool history) {
  const uint64_t now = esp_timer_get_time();
  out["uptime_us"] = now;
  out["reset_reason"] = static_cast<int>(esp_reset_reason());
  out["frames"] = displayMetrics.frames;
  out["completed_visits"] = displayMetrics.completed;
  out["timed_visits"] = displayMetrics.timed;
  out["late_visits"] = displayMetrics.late;
  out["late_threshold_us"] = 100000;
  out["dwell_max_us"] = displayMetrics.dwellMaxUs;
  out["dwell_mean_us"] = displayMetrics.timed ? displayMetrics.dwellTotalUs / displayMetrics.timed : 0;
  out["render_last_us"] = displayMetrics.renderLastUs;
  out["render_max_us"] = displayMetrics.renderMaxUs;
  out["render_mean_us"] = displayMetrics.frames ? displayMetrics.renderTotalUs / displayMetrics.frames : 0;
  out["loop_gap_max_us"] = displayMetrics.loopMaxUs;
  out["capture_available"] = matrix->mirror.ready();
  out["panel_refresh_hz"] = matrix->calculated_refresh_rate;
  out["heap_free"] = ESP.getFreeHeap();
  out["heap_min"] = ESP.getMinFreeHeap();
  out["heap_largest"] = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  out["psram_free"] = ESP.getFreePsram();
  out["wifi_rssi"] = WiFi.RSSI();
  JsonObject network = out["network"].to<JsonObject>();
  network["device_credentials_ready"] = deviceCredentials.ready();
  network["wifi_connected"] = WiFi.status() == WL_CONNECTED;
  network["ticker_id"] = tickerId;
  network["registration_status"] = lastRegistrationStatus;
  network["error_stage"] = lastNetworkError;
  network["resolved_address"] = lastResolvedAddress;
  network["dns_server"] = "1.1.1.1";
  network["dns_method"] = "https";
  network["dhcp_dns_server"] = WiFi.dnsIP().toString();
  network["local_address"] = WiFi.localIP().toString();
  network["epoch"] = static_cast<long long>(time(nullptr));
  network["reconnects"] = networkReconnects;
  network["http_status"] = lastDataStatus;
  network["expected_bytes"] = lastDataExpectedBytes;
  network["received_bytes"] = lastDataBytes;
  network["transfer_bytes"] = lastDataTransferBytes;
  network["content_type"] = lastDataContentType;
  network["content_encoding"] = lastDataEncoding;
  network["json_error"] = lastDataJsonError;
  network["json_offset"] = lastDataJsonOffset;
  network["json_failures"] = dataJsonFailures;
  wifiStation.describe(network, millis());
  network["wifi_setup_active"] = wifiPairingMode;
  network["saved_network_confirmed"] = wifiKnownWorking;
  network["ble_setup_active"] = blePairingStarted;
  if (lastDataSuccessAt) network["data_age_ms"] = millis() - lastDataSuccessAt;
  else network["data_age_ms"] = nullptr;
  network["reused_connections"] = reusedDataConnections;
  network["fresh_connections"] = freshDataConnections;
  network["deadline_timeouts"] = dataDeadlineTimeouts;
  network["last_request_timed_out"] = lastDataExpired;
  network["heartbeat_status"] = lastHeartbeatStatus;
  network["heartbeat_failures"] = heartbeatFailures;
  if (heartbeatSucceeded) network["heartbeat_age_ms"] = millis() - lastHeartbeatSuccessAt;
  else network["heartbeat_age_ms"] = nullptr;
  network["request_ms"] = lastDataDurationMs;
  network["gate_wait_ms"] = lastDataGateWaitMs;
  network["headers_ms"] = lastDataHeadersMs;
  network["body_ms"] = lastDataBodyMs;
  uint8_t updateState = 0;
  uint32_t updateComplete = 0, updateTotal = 0;
  char updateDetail[24] = {};
  firmwareUpdater.displaySnapshot(updateState, updateComplete, updateTotal, updateDetail, sizeof(updateDetail));
  JsonObject update = out["update"].to<JsonObject>();
  update["state"] = updateState;
  update["complete_bytes"] = updateComplete;
  update["total_bytes"] = updateTotal;
  update["detail"] = updateDetail;
  update["boot_validated"] = firmwareUpdater.bootValidated();
  update["boot_state"] = firmwareUpdater.bootState();
  update["boot_state_error"] = firmwareUpdater.bootStateError();
  JsonObject assets = out["assets"].to<JsonObject>();
  assets["ram_slots"] = spriteAssets.slotCount();
  uint16_t resident = 0;
  if (logoWorkMutex != nullptr && spriteAssets.ready()) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
    assets["planned"] = logoWorkCount;
    assets["generation"] = logoPlanGeneration;
    assets["worker_busy"] = logoWorkerBusy || logoWorkerPending;
    resident = spriteAssets.residentCount();
    xSemaphoreGive(logoWorkMutex);
  }
  assets["resident"] = resident;
  assets["foreground_ready"] = foregroundLogoReadyCount();
  assets["flash_hits"] = spriteAssets.metrics().flashHits;
  assets["downloads"] = spriteAssets.metrics().downloads;
  assets["invalid_files"] = spriteAssets.metrics().invalidFiles;
  JsonObjectConst currentGame;
  assets["current_ready"] = selectedGame(currentGame) && sportsGameAssetsCached(currentGame);
  describePane(out["pane"].to<JsonObject>(), displayMetrics.current);
  out["pane"]["shown_us"] = displayMetrics.frames ? now - displayMetrics.startedUs : 0;
  if (history) {
    JsonArray visits = out["visits"].to<JsonArray>();
    const uint32_t first = displayMetrics.completed > mini_display::Metrics::HISTORY ?
                           displayMetrics.completed - mini_display::Metrics::HISTORY : 0;
    for (uint32_t index = first; index < displayMetrics.completed; ++index) {
      const auto& visit = displayMetrics.history[index % mini_display::Metrics::HISTORY];
      JsonObject row = visits.add<JsonObject>();
      describePane(row, visit.pane);
      row["visit"] = visit.number;
      row["started_us"] = visit.startedUs;
      row["ended_us"] = visit.endedUs;
      row["shown_us"] = visit.endedUs - visit.startedUs;
    }
  }
}

void writeDiagnosticJson(Stream& output, const char* prefix, const JsonDocument& document) {
  String payload;
  serializeJson(document, payload);
  const String line = String(prefix) + payload + "\n";
  output.print(line);
}

struct FrameCaptureTransfer {
  Stream* output = nullptr;
  uint8_t* pixels = nullptr;
  uint32_t id = 0;
  uint32_t hash = 0;
  size_t offset = 0;
  uint64_t startedUs = 0;
} frameCapture;

void startFrameCapture(Stream& output) {
  if (frameCapture.output != nullptr) { output.println("MINI_ERROR:capture_busy"); return; }
  if (!matrix->mirror.ready() || !displayMetrics.frames) { output.println("MINI_ERROR:capture_unavailable"); return; }
  if (frameCapture.pixels == nullptr) {
    frameCapture.pixels = static_cast<uint8_t*>(heap_caps_malloc(mini_display::FRAME_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  }
  if (frameCapture.pixels == nullptr) { output.println("MINI_ERROR:capture_memory"); return; }
  const uint64_t started = esp_timer_get_time();
  memcpy(frameCapture.pixels, matrix->mirror.front(), mini_display::FRAME_BYTES);
  frameCapture.hash = mini_display::checksum(frameCapture.pixels, mini_display::FRAME_BYTES);
  frameCapture.output = &output;
  frameCapture.offset = 0;
  frameCapture.startedUs = started;
  ++frameCapture.id;
  JsonDocument header;
  header["v"] = 1;
  header["firmware"] = MINI_FIRMWARE_VERSION;
  header["id"] = frameCapture.id;
  header["frame"] = displayMetrics.frames;
  header["uptime_us"] = started;
  header["width"] = 64;
  header["height"] = 32;
  header["format"] = "rgb888";
  header["stage"] = "before_gamma_and_brightness";
  header["bytes"] = mini_display::FRAME_BYTES;
  header["fnv1a32"] = frameCapture.hash;
  header["brightness"] = matrix->brightness;
  header["snapshot_us"] = uint64_t(esp_timer_get_time()) - started;
  header["render_us"] = displayMetrics.renderLastUs;
  describePane(header["pane"].to<JsonObject>(), displayMetrics.current);
  header["pane"]["shown_us"] = started - displayMetrics.startedUs;
  writeDiagnosticJson(output, "MINI_FRAME_BEGIN:", header);
}

void pumpFrameCapture() {
  if (frameCapture.output == nullptr) return;
  if (uint64_t(esp_timer_get_time()) - frameCapture.startedUs > 30000000) {
    frameCapture.output = nullptr;
    return;
  }
  char line[128];
  int length;
  if (frameCapture.offset == mini_display::FRAME_BYTES) {
    length = snprintf(line, sizeof(line), "MINI_FRAME_END:%08lx:%08lx\n",
                      static_cast<unsigned long>(frameCapture.id), static_cast<unsigned long>(frameCapture.hash));
  } else {
    length = snprintf(line, sizeof(line), "MINI_PIX:%08lx:%04x:", static_cast<unsigned long>(frameCapture.id),
                      static_cast<unsigned>(frameCapture.offset));
    for (size_t index = 0; index < 16; ++index) {
      length += snprintf(line + length, sizeof(line) - length, "%02x", frameCapture.pixels[frameCapture.offset + index]);
    }
    line[length++] = '\n';
  }
  if (frameCapture.output->availableForWrite() < length) return;
  if (frameCapture.output->write(reinterpret_cast<const uint8_t*>(line), length) != static_cast<size_t>(length)) {
    frameCapture.output = nullptr;
    return;
  }
  if (frameCapture.offset == mini_display::FRAME_BYTES) frameCapture.output = nullptr;
  else frameCapture.offset += 16;
}
