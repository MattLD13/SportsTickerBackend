#pragma once

#include <cmath>
#include <cstdint>

namespace mini_display {
class Orientation {
 public:
  bool observe(float x, float y, float z, uint32_t now) {
    const float magnitude = x * x + y * y + z * z;
    if (!std::isfinite(magnitude) || magnitude < 0.64f || magnitude > 1.44f ||
        std::fabs(y) < 0.75f || std::fabs(x) > 0.45f || std::fabs(z) > 0.65f) {
      pending_ = false;
      return false;
    }
    const uint8_t next = y > 0 ? 0 : 2;
    if (next == rotation_) { pending_ = false; return false; }
    if (!pending_ || next != candidate_) {
      candidate_ = next;
      candidateSince_ = now;
      pending_ = true;
      return false;
    }
    if (uint32_t(now - candidateSince_) < 800) return false;
    rotation_ = next;
    pending_ = false;
    return true;
  }
  void unavailable() { pending_ = false; }
  uint8_t rotation() const { return rotation_; }
 private:
  uint32_t candidateSince_ = 0;
  uint8_t rotation_ = 0, candidate_ = 0;
  bool pending_ = false;
};
}
