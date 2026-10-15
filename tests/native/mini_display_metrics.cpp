#include "display_metrics.h"
#include <cassert>
#include <cstdio>
#include <vector>

int main() {
  using namespace mini_display;
  std::vector<uint8_t> bytes(FRAME_BYTES * 2, 0);
  FrameMirror mirror;
  assert(!mirror.ready());
  mirror.attach(bytes.data());
  mirror.rect(0, 0, 64, 32, 10, 20, 30);
  mirror.pixel(63, 31, 1, 2, 3);
  assert(mirror.front()[0] == 0);
  mirror.present();
  assert(mirror.front()[0] == 10);
  assert(mirror.front()[FRAME_BYTES - 1] == 3);
  const uint32_t first = checksum(mirror.front(), FRAME_BYTES);
  mirror.rect(-4, -2, 6, 4, 99, 100, 101);
  mirror.pixel(-1, 0, 0, 0, 0);
  mirror.pixel(64, 32, 0, 0, 0);
  assert(checksum(mirror.front(), FRAME_BYTES) == first);
  mirror.present();
  assert(mirror.front()[0] == 99 && mirror.front()[3] == 99);
  assert(mirror.front()[6] == 0 && mirror.front()[2 * WIDTH * 3] == 0);
  mirror.present();
  assert(checksum(mirror.front(), FRAME_BYTES) == first);

  Metrics metrics;
  Pane firstPane;
  std::strcpy(firstPane.kind, "sports");
  std::strcpy(firstPane.item, "game-one");
  firstPane.targetMs = 3000; firstPane.count = 15;
  const uint64_t start = 5000000000ULL;
  metrics.present(firstPane, start, 100);
  metrics.present(firstPane, start + 2000000, 200);
  assert(metrics.completed == 0 && metrics.startedUs == start);
  Pane secondPane = firstPane;
  std::strcpy(secondPane.item, "game-two"); secondPane.index = 1;
  metrics.present(secondPane, start + 3500000, 150);
  assert(metrics.completed == 1 && metrics.late == 1 && metrics.timed == 1);
  assert(metrics.history[0].endedUs - metrics.history[0].startedUs == 3500000);
  assert(metrics.renderMaxUs == 200 && metrics.renderTotalUs == 450);
  metrics.loop(start); metrics.loop(start + 2000000);
  assert(metrics.loopMaxUs == 2000000);
  Pane overlay;
  std::strcpy(overlay.kind, "firmware_update");
  metrics.present(overlay, start + 4000000, 100);
  metrics.present(firstPane, start + 14000000, 100);
  assert(metrics.timed == 2 && metrics.dwellMaxUs == 3500000);
  for (unsigned index = 0; index < 40; ++index) {
    Pane next = firstPane;
    std::snprintf(next.item, sizeof(next.item), "game-%u", index);
    metrics.present(next, start + 15000000 + index * 3000000ULL, 100);
  }
  assert(metrics.history[(metrics.completed - 1) % Metrics::HISTORY].number == metrics.completed);
  std::puts("Mini frame mirror, clipping, visit timing, overlays, and bounded history passed");
}
