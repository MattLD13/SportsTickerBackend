// Draw one racing card: the race, the class and the session state, the flag signal, and the first three positions.
#pragma once

#include <array>
#include "text.h"

namespace mini_ui {

struct RacingRow {
  std::string car, name, gap;
  int position = 0;
  Rgb positionColor{235, 235, 235}, metricColor{180, 210, 255};
  Rgb numberColor{115, 180, 255}, numberOutline{0, 0, 0};
  bool outlined = false;
};

struct RacingPane {
  struct Signal {
    std::array<uint16_t, 25> pixels{};
    std::string label;
    bool showLabel = false, flashing = false;
  };
  std::string race, group, status;
  Signal signal;
  bool signalPresent = false, upcoming = false;
  std::array<RacingRow, 3> rows;
  int count = 0;
  unsigned elapsedMs = 0, signalPhaseMs = 0;
};

namespace racing {

static constexpr Motion raceMotion{1500, 1, 90, 14};
static constexpr Rgb blue{115, 180, 255};

// The outline of a car number stays inside the number column.
template<class Canvas> struct NumberColumn {
  Canvas& canvas;
  void pixel(int x, int y, Rgb ink) {
    if (x >= 5 && x < 18 && y >= 12 && y < 32) canvas.pixel(x, y, ink);
  }
};

// The 5x5 flag pattern dims to a third on every other 350 ms when it flashes.
template<class Canvas>
void signal(Canvas& canvas, const RacingPane& view) {
  const int light = view.signal.flashing && (view.signalPhaseMs / 350) % 2 ? 1 : 3;
  for (int index = 0; index < 25; ++index) {
    const uint16_t rgb = view.signal.pixels[index];
    canvas.pixel(59 + index % 5, 6 + index / 5, {static_cast<uint8_t>(((rgb >> 11) & 31) * 255 / 31 * light / 3),
        static_cast<uint8_t>(((rgb >> 5) & 63) * 255 / 63 * light / 3), static_cast<uint8_t>((rgb & 31) * 255 / 31 * light / 3)});
  }
}

template<class Canvas>
void row(Canvas& canvas, const RacingRow& value, int y) {
  drawText(canvas, std::to_string(value.position), 0, y, value.positionColor, {}, {0, 4});
  if (value.outlined) {
    NumberColumn<Canvas> column{canvas};
    for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
      if (dx || dy) drawText(column, value.car, 6 + dx, y + dy, value.numberOutline, {}, {5, 18});
    }
  }
  drawText(canvas, value.car, 6, y, value.numberColor, {}, {6, 18});
  drawText(canvas, value.name, 19, y, SCORE_TEXT, {}, {19, 32});
  drawText(canvas, value.gap, 64 - measure(value.gap), y, value.metricColor, {}, {33, 64});
}

}  // namespace racing

template<class Canvas>
void draw(Canvas& canvas, const RacingPane& view) {
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  canvas.rect(0, 0, PANE_WIDTH, 6, {5, 12, 24});
  marquee(canvas, view.race, 1, 63, 0, STATUS_TEXT, view.elapsedMs, racing::raceMotion, false);
  drawText(canvas, view.group, 1, 6, racing::blue, {}, {1, 31});
  const std::string status = view.signal.showLabel ? view.signal.label : view.status;
  drawText(canvas, status, 56 - measure(status), 6, MUTED_TEXT, {}, {31, 56});
  racing::signal(canvas, view);
  canvas.rect(0, 11, PANE_WIDTH, 1, HEADER_RULE);
  if (!view.count) {
    center(canvas, view.upcoming ? "STARTS" : "NO TIMES", 0, PANE_WIDTH, 16, MUTED_TEXT);
    center(canvas, view.status, 0, PANE_WIDTH, 25, racing::blue);
    return;
  }
  for (int index = 0; index < view.count && index < 3; ++index) racing::row(canvas, view.rows[index], 13 + index * 7);
}

}  // namespace mini_ui
