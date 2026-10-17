#include "network.h"
#include "http_session.h"
#include <WiFi.h>
#include <freertos/task.h>

void NetworkWorker::taskEntry(void* context) {
  static_cast<NetworkWorker*>(context)->run();
}

void NetworkWorker::run() {
  BackendHttpSession session(gate_);
  for (;;) {
    NetworkJob* job = nullptr;
    if (xQueueReceive(requests_, &job, portMAX_DELAY) != pdTRUE) continue;
    const uint32_t started = millis();
    execute(*job, session);
    job->durationMs = millis() - started;
    if (job->completion) xSemaphoreGive(job->completion);
    else xQueueSend(results_, &job, portMAX_DELAY);
  }
}

bool NetworkWorker::begin() {
  if (requests_) return true;
  if (deviceToken_.length() != 64) return false;
  if (!gate_.ready()) { Serial.println("Network synchronization setup failed"); return false; }
  requests_ = xQueueCreate(2, sizeof(NetworkJob*));
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
  job->deviceToken = deviceToken_;
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

bool NetworkWorker::fetchAsset(const String& url, uint8_t* bytes, size_t expectedBytes, AssetTransfer& transfer) {
  if (!requests_) return false;
  NetworkJob job(NetworkKind::AssetGet);
  job.url = url;
  job.completion = xSemaphoreCreateBinary();
  if (!job.completion) return false;
  NetworkJob* queued = &job;
  if (xQueueSend(requests_, &queued, pdMS_TO_TICKS(1000)) != pdTRUE) {
    vSemaphoreDelete(job.completion);
    return false;
  }
  xSemaphoreTake(job.completion, portMAX_DELAY);
  vSemaphoreDelete(job.completion);
  transfer.status = job.status;
  transfer.durationMs = job.durationMs;
  transfer.heapBefore = job.heapBefore;
  transfer.heapDuring = job.heapDuring;
  transfer.largestDuring = job.largestDuring;
  transfer.reused = job.reusedConnection;
  if (job.status != HTTP_CODE_OK || !job.complete() || job.response.body.size() != expectedBytes) return false;
  memcpy(bytes, job.response.body.data(), expectedBytes);
  return true;
}

void NetworkWorker::execute(NetworkJob& job, BackendHttpSession& session) {
  if (WiFi.status() != WL_CONNECTED) return;
  const uint32_t started = millis();
  NetworkLease lease(gate_, 10000, NetworkAccess::DeviceRequests);
  if (!lease) return;
  job.gateWaitMs = millis() - started;
  session.execute(job);
}
