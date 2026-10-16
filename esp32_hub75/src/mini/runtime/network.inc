QueueHandle_t networkRequests = nullptr;
QueueHandle_t networkResults = nullptr;
bool networkJobPending = false;

void networkWorkerTask(void*) {
  for (;;) {
    NetworkJob* job = nullptr;
    if (xQueueReceive(networkRequests, &job, portMAX_DELAY) != pdTRUE) continue;
    const uint32_t started = millis();
    if (WiFi.status() == WL_CONNECTED && acquireNetwork(10000)) {
      BackendTlsClient client;
      configureTls(client);
      client.setTimeout(8);
      client.setHandshakeTimeout(8);
      HTTPClient http;
      http.useHTTP10(true);
      http.setReuse(false);
      http.setConnectTimeout(4000);
      http.setTimeout(4000);
      if (http.begin(client, job->url)) {
        const char* headers[] = {"Content-Type", "Content-Encoding"};
        http.collectHeaders(headers, 2);
        if (job->kind == NetworkKind::Data) job->status = http.GET();
        else {
          http.addHeader("Content-Type", "application/json");
          job->status = http.POST(job->request);
        }
        job->expectedBytes = http.getSize();
        job->contentType = http.header("Content-Type");
        job->contentEncoding = http.header("Content-Encoding");
        if (job->status == HTTP_CODE_OK || job->status == HTTP_CODE_CREATED)
          job->transferredBytes = http.writeToStream(&job->response);
        logSecureHttpError("Network", job->status, client);
        job->resolvedAddress = client.resolvedAddress();
        if (job->status < 0) {
          char detail[96] = {};
          job->errorStage = !client.nameResolved() ? "dns" : client.lastError(detail, sizeof(detail)) < -1 ? "tls" : "connect";
        }
        http.end();
      }
      releaseNetwork();
    }
    job->durationMs = millis() - started;
    xQueueSend(networkResults, &job, portMAX_DELAY);
  }
}

void setupNetworkWorker() {
  if (!networkMutex) { Serial.println("Network synchronization setup failed"); return; }
  networkRequests = xQueueCreate(1, sizeof(NetworkJob*));
  networkResults = xQueueCreate(1, sizeof(NetworkJob*));
  TaskHandle_t worker = nullptr;
  if (networkRequests && networkResults &&
      xTaskCreatePinnedToCore(networkWorkerTask, "data-worker", 8192, nullptr, 1, &worker, 0) == pdPASS) return;
  if (networkRequests) vQueueDelete(networkRequests);
  if (networkResults) vQueueDelete(networkResults);
  networkRequests = networkResults = nullptr;
  Serial.println("Network worker setup failed");
}

bool networkAvailable() { return networkRequests && !networkJobPending; }

bool queueNetworkJob(NetworkJob* job) {
  if (!job) return false;
  if (networkJobPending || !networkRequests || xQueueSend(networkRequests, &job, 0) != pdTRUE) {
    delete job;
    return false;
  }
  networkJobPending = true;
  return true;
}

void pollNetworkResults() {
  NetworkJob* job = nullptr;
  if (!networkResults || xQueueReceive(networkResults, &job, 0) != pdTRUE) return;
  networkJobPending = false;
  lastNetworkError = job->errorStage;
  lastResolvedAddress = job->resolvedAddress;
  if (job->kind == NetworkKind::Registration) lastRegistrationStatus = job->status;
  const uint8_t failuresBeforeRenewal = job->kind == NetworkKind::Registration ? 1 : 3;
  const bool linkFailed = job->errorStage == "dns" || job->errorStage == "connect";
  if (networkRecovery.observe(linkFailed, job->status > 0, millis(), failuresBeforeRenewal))
    networkReconnectRequested = true;
  if (job->kind == NetworkKind::Registration) applyRegistrationResponse(*job);
  else if (job->kind == NetworkKind::Data) applyDataResponse(*job);
  else if (job->kind == NetworkKind::FirmwareAck) applyFirmwareAckResponse(*job);
  delete job;
}
