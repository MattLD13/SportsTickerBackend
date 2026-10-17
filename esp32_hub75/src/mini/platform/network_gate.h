#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

enum class NetworkAccess { Exclusive, DeviceRequests };

// Serialize TLS clients and close retained transport before exclusive work.
class NetworkGate {
 public:
  bool begin();
  bool ready() const { return mutex_ != nullptr; }
  bool acquire(uint32_t timeoutMs, NetworkAccess access = NetworkAccess::Exclusive);
  void release();
  void setIdleCleanup(void (*cleanup)(void*), void* owner);
  NetworkGate() = default;
  NetworkGate(const NetworkGate&) = delete;
  NetworkGate& operator=(const NetworkGate&) = delete;

 private:
  SemaphoreHandle_t mutex_ = nullptr;
  void (*cleanup_)(void*) = nullptr;
  void* transportOwner_ = nullptr;
};

// Declare the lease before clients so their destructors run before unlock.
class NetworkLease {
 public:
  NetworkLease(NetworkGate& gate, uint32_t timeoutMs, NetworkAccess access = NetworkAccess::Exclusive)
      : gate_(gate), held_(gate.acquire(timeoutMs, access)) {}
  ~NetworkLease() { if (held_) gate_.release(); }
  explicit operator bool() const { return held_; }
  NetworkLease(const NetworkLease&) = delete;
  NetworkLease& operator=(const NetworkLease&) = delete;

 private:
  NetworkGate& gate_;
  bool held_;
};
