#pragma once

#include <cstdint>

class NetworkRecovery {
 public:
  bool observe(bool failed, bool reachedServer, uint32_t now, uint8_t failuresBeforeRenewal = 3) {
    if (reachedServer) { failures_ = 0; return false; }
    if (!failed) return false;
    if (failures_ < failuresBeforeRenewal) ++failures_;
    if (failures_ < failuresBeforeRenewal || (attempted_ && now - lastAttempt_ < 30000)) return false;
    failures_ = 0;
    attempted_ = true;
    lastAttempt_ = now;
    return true;
  }
 private:
  uint8_t failures_ = 0;
  uint32_t lastAttempt_ = 0;
  bool attempted_ = false;
};
