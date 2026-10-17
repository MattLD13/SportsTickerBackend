#include "http_session.h"
#include "../platform/http_diagnostics.h"

BackendHttpSession::BackendHttpSession(NetworkGate& gate) {
  configureTls(client_);
  client_.setTimeout(8);
  client_.setHandshakeTimeout(8);
  http_.useHTTP10(false);
  http_.setReuse(true);
  http_.setConnectTimeout(4000);
  http_.setTimeout(4000);
  gate.setIdleCleanup(releaseIdle, this);
}

void BackendHttpSession::releaseIdle(void* owner) {
  static_cast<BackendHttpSession*>(owner)->close();
}

void BackendHttpSession::close() {
  http_.setReuse(false);
  http_.end();
  client_.stop();
  http_.setReuse(true);
}

void BackendHttpSession::execute(NetworkJob& job) {
  if (job.requireFreshConnection) close();
  client_.setTransferBudget(job.budgetMs);
  const uint32_t attempts = client_.connectionAttempts();
  const uint32_t started = millis();
  job.heapBefore = ESP.getFreeHeap();
  if (http_.begin(client_, job.url)) {
    const char* headers[] = {"Content-Type", "Content-Encoding"};
    http_.collectHeaders(headers, 2);
    http_.addHeader("Content-Type", "application/json");
    if (job.kind != NetworkKind::AssetGet) http_.addHeader("X-Device-Token", job.deviceToken);
    job.status = job.kind == NetworkKind::AssetGet ? http_.GET() : http_.POST(job.request);
    job.heapDuring = ESP.getFreeHeap();
    job.largestDuring = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    job.headersMs = millis() - started;
    job.expectedBytes = http_.getSize();
    job.contentType = http_.header("Content-Type");
    job.contentEncoding = http_.header("Content-Encoding");
    const uint32_t bodyStarted = millis();
    if (job.status == HTTP_CODE_OK || job.status == HTTP_CODE_CREATED)
      job.transferredBytes = http_.writeToStream(&job.response);
    job.bodyMs = millis() - bodyStarted;
    logSecureHttpError("Network", job.status, client_);
    job.resolvedAddress = client_.resolvedAddress();
    if (job.status < 0) {
      char detail[96] = {};
      job.errorStage = !client_.nameResolved() ? "dns" : client_.lastError(detail, sizeof(detail)) < -1 ? "tls" : "connect";
    }
    http_.end();
  }
  job.expired = client_.deadlineExpired();
  job.reusedConnection = job.status > 0 && attempts == client_.connectionAttempts();
  if (job.expired) job.errorStage = "timeout";
  if (job.expired || !job.complete() || (job.status != HTTP_CODE_OK && job.status != HTTP_CODE_CREATED)) close();
}
