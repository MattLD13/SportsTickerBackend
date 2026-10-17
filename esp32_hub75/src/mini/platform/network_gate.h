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

// Declare the lease before clients so their destructors run before unlock.
class NetworkLease {
 public:
  NetworkLease(NetworkGate& gate, uint32_t timeoutMs) : gate_(gate), held_(gate.acquire(timeoutMs)) {}
  ~NetworkLease() { if (held_) gate_.release(); }
  explicit operator bool() const { return held_; }
  NetworkLease(const NetworkLease&) = delete;
  NetworkLease& operator=(const NetworkLease&) = delete;

 private:
  NetworkGate& gate_;
  bool held_;
};
