#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>

namespace mini_display {
constexpr int WIDTH = 64;
constexpr int HEIGHT = 32;
constexpr int FRAME_BYTES = WIDTH * HEIGHT * 3;

inline uint32_t checksum(const uint8_t* bytes, size_t size) {
  uint32_t result = 2166136261u;
  for (size_t index = 0; index < size; ++index) result = (result ^ bytes[index]) * 16777619u;
  return result;
}

class FrameMirror {
 public:
  void attach(uint8_t* storage) { buffers_ = storage; }
  bool ready() const { return buffers_ != nullptr; }
  void pixel(int x, int y, uint8_t r, uint8_t g, uint8_t b) {
    if (!ready() || x < 0 || y < 0 || x >= WIDTH || y >= HEIGHT) return;
    uint8_t* pixel = buffers_ + back_ * FRAME_BYTES + (y * WIDTH + x) * 3;
    pixel[0] = r; pixel[1] = g; pixel[2] = b;
  }
  void rect(int x, int y, int width, int height, uint8_t r, uint8_t g, uint8_t b) {
    const int right = std::min(WIDTH, x + width);
    const int bottom = std::min(HEIGHT, y + height);
    for (int row = std::max(0, y); row < bottom; ++row)
      for (int column = std::max(0, x); column < right; ++column) pixel(column, row, r, g, b);
  }
  void present() { front_ = back_; back_ ^= 1; }
  const uint8_t* front() const { return ready() ? buffers_ + front_ * FRAME_BYTES : nullptr; }
 private:
  uint8_t* buffers_ = nullptr;
  unsigned front_ = 1;
  unsigned back_ = 0;
};

struct Pane {
  char kind[24] = "startup";
  char item[96] = {};
  uint16_t index = 0;
  uint16_t count = 0;
  uint32_t targetMs = 0;
  bool same(const Pane& other) const {
    return std::strcmp(kind, other.kind) == 0 && std::strcmp(item, other.item) == 0;
  }
};

struct Visit {
  Pane pane;
  uint64_t startedUs = 0;
  uint64_t endedUs = 0;
  uint32_t number = 0;
};

class Metrics {
 public:
  static constexpr size_t HISTORY = 16;
  Pane current;
  uint64_t startedUs = 0;
  uint64_t frames = 0;
  uint64_t renderTotalUs = 0;
  uint64_t renderLastUs = 0;
  uint64_t renderMaxUs = 0;
  uint64_t loopMaxUs = 0;
  uint64_t dwellTotalUs = 0;
  uint64_t dwellMaxUs = 0;
  uint32_t completed = 0;
  uint32_t timed = 0;
  uint32_t late = 0;
  std::array<Visit, HISTORY> history{};
  void loop(uint64_t now) {
    if (hasLoop_) loopMaxUs = std::max(loopMaxUs, now - lastLoopUs_);
    lastLoopUs_ = now; hasLoop_ = true;
  }
  void present(const Pane& pane, uint64_t now, uint64_t renderUs) {
    if (frames && !current.same(pane)) {
      const uint64_t dwell = now - startedUs;
      Visit& visit = history[completed % HISTORY];
      visit.pane = current;
      visit.startedUs = startedUs;
      visit.endedUs = now;
      visit.number = completed + 1;
      ++completed;
      if (current.targetMs > 0) {
        ++timed;
        dwellTotalUs += dwell;
        dwellMaxUs = std::max(dwellMaxUs, dwell);
        if (dwell > uint64_t(current.targetMs) * 1000 + 100000) ++late;
      }
      startedUs = now;
    } else if (!frames) startedUs = now;
    current = pane;
    ++frames;
    renderLastUs = renderUs;
    renderTotalUs += renderUs;
    renderMaxUs = std::max(renderMaxUs, renderUs);
  }
 private:
  uint64_t lastLoopUs_ = 0;
  bool hasLoop_ = false;
};
}
