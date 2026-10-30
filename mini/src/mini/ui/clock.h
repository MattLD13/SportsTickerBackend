// Draw the date, the large time, and the seconds rail. Before the clock is set, show the clock sync state.
#pragma once

#include "system.h"

namespace mini_ui {

struct ClockPane {
  std::string date, time;
  uint32_t elapsedMs = 0;
  int seconds = 0;
  bool ready = false;
};

template<class Canvas>
void draw(Canvas& canvas, const ClockPane& view) {
  if (!view.ready) {
    draw(canvas, systemPane(SystemKind::TimeSync, "SETTING TIME", 0, 0, view.elapsedMs));
    return;
  }
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  center(canvas, view.date, 0, PANE_WIDTH, 0, CLOCK_DATE);
  center(canvas, view.time, 0, PANE_WIDTH, 9, SCORE_TEXT, {5, 18, 1});
  canvas.rect(0, 31, PANE_WIDTH, 1, CLOCK_RAIL);
  canvas.rect(0, 31, std::max(0, std::min(59, view.seconds)) * PANE_WIDTH / 60, 1, CLOCK_PROGRESS);
}

}  // namespace mini_ui
