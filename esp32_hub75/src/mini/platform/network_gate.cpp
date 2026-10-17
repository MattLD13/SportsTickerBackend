#include "network_gate.h"
#include <freertos/task.h>

bool NetworkGate::begin() {
  if (!mutex_) mutex_ = xSemaphoreCreateMutex();
  return ready();
}

bool NetworkGate::acquire(uint32_t timeoutMs, NetworkAccess access) {
  if (!mutex_ || xSemaphoreTake(mutex_, pdMS_TO_TICKS(timeoutMs)) != pdTRUE) return false;
  if (access == NetworkAccess::Exclusive && cleanup_) cleanup_(transportOwner_);
  return true;
}

void NetworkGate::setIdleCleanup(void (*cleanup)(void*), void* owner) {
  configASSERT(ready());
  while (!acquire(1000, NetworkAccess::DeviceRequests)) taskYIELD();
  cleanup_ = cleanup;
  transportOwner_ = owner;
  release();
}

void NetworkGate::release() {
  if (mutex_) xSemaphoreGive(mutex_);
}
