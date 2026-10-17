#include "network.h"
#include "../platform/tls.h"
#include "../platform/http_diagnostics.h"
#include <WiFi.h>
#include <freertos/task.h>

void NetworkWorker::taskEntry(void* context) {
  static_cast<NetworkWorker*>(context)->run();
}

void NetworkWorker::run() {
  for (;;) {
    NetworkJob* job = nullptr;
    if (xQueueReceive(requests_, &job, portMAX_DELAY) != pdTRUE) continue;
    const uint32_t started = millis();
    execute(*job);
    job->durationMs = millis() - started;
    xQueueSend(results_, &job, portMAX_DELAY);
  }
}

bool NetworkWorker::begin() {
  if (requests_) return true;
  if (!gate_.ready()) { Serial.println("Network synchronization setup failed"); return false; }
  requests_ = xQueueCreate(1, sizeof(NetworkJob*));
  results_ = xQueueCreate(1, sizeof(NetworkJob*));
  TaskHandle_t worker = nullptr;
  if (requests_ && results_ &&
      xTaskCreatePinnedToCore(taskEntry, "data-worker", 8192, this, 1, &worker, 0) == pdPASS) return true;
  if (requests_) vQueueDelete(requests_);
  if (results_) vQueueDelete(results_);
  requests_ = results_ = nullptr;
  Serial.println("Network worker setup failed");
  return false;
}

bool NetworkWorker::available() const { return requests_ && !pending_; }

bool NetworkWorker::enqueue(NetworkJob* job) {
  if (!job) return false;
  if (pending_ || !requests_ || xQueueSend(requests_, &job, 0) != pdTRUE) {
    delete job;
    return false;
  }
  pending_ = true;
  return true;
}

NetworkJob* NetworkWorker::takeResult() {
  NetworkJob* job = nullptr;
  if (!results_ || xQueueReceive(results_, &job, 0) != pdTRUE) return nullptr;
  pending_ = false;
  return job;
}

void NetworkWorker::execute(NetworkJob& job) {
  if (WiFi.status() != WL_CONNECTED) return;
  const uint32_t started = millis();
  NetworkLease lease(gate_, 10000);
  if (!lease) return;
  job.gateWaitMs = millis() - started;
  const uint32_t headersStarted = millis();
  BackendTlsClient client;
  client.setTransferBudget(job.budgetMs);
  configureTls(client);
  client.setTimeout(8);
  client.setHandshakeTimeout(8);
  HTTPClient http;
  http.useHTTP10(true);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (http.begin(client, job.url)) {
    const char* headers[] = {"Content-Type", "Content-Encoding"};
    http.collectHeaders(headers, 2);
    http.addHeader("Content-Type", "application/json");
    job.status = http.POST(job.request);
    job.headersMs = millis() - headersStarted;
    job.expectedBytes = http.getSize();
    job.contentType = http.header("Content-Type");
    job.contentEncoding = http.header("Content-Encoding");
    const uint32_t bodyStarted = millis();
    if (job.status == HTTP_CODE_OK || job.status == HTTP_CODE_CREATED)
      job.transferredBytes = http.writeToStream(&job.response);
    job.bodyMs = millis() - bodyStarted;
    logSecureHttpError("Network", job.status, client);
    job.resolvedAddress = client.resolvedAddress();
    if (job.status < 0) {
      char detail[96] = {};
      job.errorStage = !client.nameResolved() ? "dns" : client.lastError(detail, sizeof(detail)) < -1 ? "tls" : "connect";
    }
    http.end();
  }
  job.expired = client.deadlineExpired();
  if (job.expired) job.errorStage = "timeout";
}
