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
  else if (job->kind == NetworkKind::Data) applyDataResponse(*job);
  else if (job->kind == NetworkKind::FirmwareAck) firmwareUpdater.applyAckResponse(*job);
  delete job;
}
