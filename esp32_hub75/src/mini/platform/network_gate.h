#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

// Serialize TLS clients and Wi-Fi renewal across background tasks.
class NetworkGate {
 public:
  bool begin();
  bool ready() const { return mutex_ != nullptr; }
  bool acquire(uint32_t timeoutMs);
  void release();
  NetworkGate() = default;
  NetworkGate(const NetworkGate&) = delete;
  NetworkGate& operator=(const NetworkGate&) = delete;

 private:
  SemaphoreHandle_t mutex_ = nullptr;
};
