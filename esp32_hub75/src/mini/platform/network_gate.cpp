#include "network_gate.h"

bool NetworkGate::begin() {
  if (!mutex_) mutex_ = xSemaphoreCreateMutex();
  return ready();
}

bool NetworkGate::acquire(uint32_t timeoutMs) {
  return mutex_ && xSemaphoreTake(mutex_, pdMS_TO_TICKS(timeoutMs)) == pdTRUE;
}

void NetworkGate::release() {
  if (mutex_) xSemaphoreGive(mutex_);
}
