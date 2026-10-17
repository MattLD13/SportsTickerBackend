void pollNetworkResults() {
  NetworkJob* job = networkWorker.takeResult();
  if (!job) return;
  lastNetworkError = job->errorStage;
  lastResolvedAddress = job->resolvedAddress;
  if (job->kind == NetworkKind::Registration) lastRegistrationStatus = job->status;
  const uint8_t failuresBeforeRenewal = job->kind == NetworkKind::Registration ? 1 : 3;
  const bool linkFailed = job->errorStage == "dns" || job->errorStage == "connect";
  if (networkRecovery.observe(linkFailed, job->status > 0, millis(), failuresBeforeRenewal))
    networkReconnectRequested = true;
  if (job->kind == NetworkKind::Registration) applyRegistrationResponse(*job);
  else if (job->kind == NetworkKind::DevicePoll) applyDataResponse(*job);
  else if (job->kind == NetworkKind::AuthCheck) {
    JsonDocument result;
    result["status"] = job->status;
    result["cold"] = job->requireFreshConnection;
    result["reused"] = job->reusedConnection;
    result["request_ms"] = job->durationMs;
    result["headers_ms"] = job->headersMs;
    result["body_ms"] = job->bodyMs;
    result["bytes"] = job->response.body.size();
    Serial.print("MINI_AUTH_CHECK:");
    serializeJson(result, Serial);
    Serial.println();
  }
  else if (job->kind == NetworkKind::FirmwareResult) firmwareUpdater.applyResultResponse(*job);
  delete job;
}
