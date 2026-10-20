#include "display_metrics.h"
#include "display_orientation.h"
#include "network_recovery.h"
#include <cassert>
#include <cstdio>
#include <vector>

int main() {
  NetworkRecovery recovery;
  NetworkRecovery startup;
  assert(startup.observe(true, false, 1000, 1));
  assert(!startup.observe(true, false, 2000, 1));
  assert(!startup.observe(false, true, 3000, 1));
  assert(startup.observe(true, false, 32000, 1));
  assert(!recovery.observe(true, false, 100));
  assert(!recovery.observe(true, false, 200));
  assert(recovery.observe(true, false, 300));
  assert(!recovery.observe(true, false, 400));
  assert(!recovery.observe(true, false, 500));
  assert(!recovery.observe(true, false, 600));
  assert(!recovery.observe(false, true, 1000));
  assert(!recovery.observe(true, false, 31000));
  assert(!recovery.observe(true, false, 32000));
  assert(recovery.observe(true, false, 33000));
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

  mirror.rect(0, 0, WIDTH, HEIGHT, 0, 0, 0);
  mirror.rect(-1, -1, 3, 3, 40, 50, 60, 2);
  mirror.pixel(63, 31, 1, 2, 3, 2);
  mirror.pixel(-1, 0, 255, 255, 255, 2);
  mirror.present();
  assert(mirror.front()[0] == 1 && mirror.front()[2] == 3);
  assert(mirror.front()[FRAME_BYTES - 1] == 60);
  assert(mirror.front()[FRAME_BYTES - 7] == 0);
  std::vector<uint8_t> retained(mirror.front(), mirror.front() + FRAME_BYTES);
  const auto retainedHash = checksum(retained.data(), FRAME_BYTES);
  rotateFrame180(retained.data());
  assert(retained[0] == 40 && retained[2] == 60);
  assert(retained[FRAME_BYTES - 3] == 1 && retained[FRAME_BYTES - 1] == 3);
  rotateFrame180(retained.data());
  assert(checksum(retained.data(), FRAME_BYTES) == retainedHash);

  Orientation orientation;
  assert(!orientation.observe(0, 1, 0, 0));
  assert(!orientation.observe(0, -1, 0, 100));
  assert(!orientation.observe(0, -1, 0, 899));
  assert(orientation.observe(0, -1, 0, 900));
  assert(orientation.rotation() == 2);
  assert(!orientation.observe(1, 0, 0, 1000));
  assert(!orientation.observe(0, 0, 1, 2000));
  assert(!orientation.observe(0, 1, 0, 3000));
  assert(!orientation.observe(0, 2, 0, 3900));
  assert(!orientation.observe(0, 1, 0, 4000));
  assert(!orientation.observe(NAN, 1, 0, 4500));
  assert(!orientation.observe(0, 1, 0, 4600));
  orientation.unavailable();
  assert(!orientation.observe(0, 1, 0, 5400));
  assert(orientation.observe(0, 1, 0, 6200));
  assert(orientation.rotation() == 0);
  assert(!orientation.observe(0, -1, 0, UINT32_MAX - 400));
  assert(orientation.observe(0, -1, 0, 399));

  Metrics metrics;
  Pane firstPane;
  std::strcpy(firstPane.kind, "sports");
  std::strcpy(firstPane.item, "game-one");
  firstPane.targetMs = 3000; firstPane.count = 15;
  const uint64_t start = 5000000000ULL;
  metrics.present(firstPane, start, 100);
  metrics.present(firstPane, start + 2000000, 200);
  assert(metrics.completed == 0 && metrics.startedUs == start);
  assert(!metrics.rotationDue(start + 2999999));
  assert(metrics.rotationDue(start + 3000000));
  assert(!metrics.prefetchDue(start + 1999999, 1000));
  assert(metrics.prefetchDue(start + 2000000, 1000));
  assert(!metrics.prefetchDue(start + 3000000, 1000));
  // A refreshed score and list position retain the visible page deadline.
  Pane reordered = firstPane;
  reordered.index = 7;
  reordered.count = 19;
  metrics.present(reordered, start + 2500000, 100);
  assert(metrics.rotationDue(start + 3000000));
  Pane pinned = reordered;
  pinned.count = 1;
  metrics.present(pinned, start + 2600000, 100);
  assert(!metrics.rotationDue(start + 9000000));
  assert(!metrics.prefetchDue(start + 2800000, 1000));
  metrics.present(reordered, start + 2700000, 100);
  Pane secondPane = firstPane;
  std::strcpy(secondPane.item, "game-two"); secondPane.index = 1;
  metrics.present(secondPane, start + 3500000, 150);
  assert(metrics.completed == 1 && metrics.late == 1 && metrics.timed == 1);
  assert(metrics.history[0].endedUs - metrics.history[0].startedUs == 3500000);
  assert(metrics.renderMaxUs == 200 && metrics.renderTotalUs == 750);
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
