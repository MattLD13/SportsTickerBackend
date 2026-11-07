// Render the compact V2 racing card without I/O.
#pragma once
#include <array>
#include <string>
#include "sports_pane.h"

namespace ticker_ui {
using ticker_ui::Rgb;
struct RacingRow {
  std::string car, name, gap;
  int position = 0;
  Rgb positionColor{235, 235, 235}, metricColor{180, 210, 255};
  Rgb numberColor{115, 180, 255}, numberOutline{0, 0, 0};
  bool outlined = false;
};
struct RacingPane {
  struct Signal {
    std::array<uint16_t, 66> pixels{}, alternatePixels{}, alternateBoardOffPixels{};
    int width = 11;
    unsigned alternateMs = 0;
    bool alternateBoardFlashes = false;
  };
  std::string race, group, session, status, metricType;
  Rgb groupColor{115, 180, 255};
  Signal signal;
  bool signalPresent = false;
  bool upcoming = false;
  std::array<RacingRow, 3> rows;
  int count = 0;
  unsigned elapsedMs = 0;
  unsigned signalPhaseMs = 0;
};

template<class Canvas> struct NumberClip {
  Canvas& canvas;
  void pixel(int x, int y, Rgb ink) {
    if (x >= 5 && x < 18 && y >= 12 && y < 32) canvas.pixel(x, y, ink);
  }
};

template<class Canvas>
void renderRacing(Canvas& canvas, const RacingPane& view) {
  using namespace ticker_ui;
  const Rgb blue{115, 180, 255};
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  canvas.rect(0, 0, 64, 6, {5, 12, 24});
  const int width = textWidth(view.race);
  int offset = 0;
  if (width > 62 && view.elapsedMs > 1500)
    offset = static_cast<int>((view.elapsedMs - 1500) / 90) % (width + 14);
  text(canvas, view.race, 1 - offset, 0, STATUS_TEXT, 3, 5, 1, false, 1, 63);
  if (width > 62)
    text(canvas, view.race, 1 - offset + width + 14, 0, STATUS_TEXT, 3, 5, 1, false, 1, 63);
  const int groupWidth = textWidth(view.group);
  const int groupRight = std::min(27, groupWidth + 1);
  int groupOffset = 0;
  if (groupWidth > groupRight - 1 && view.elapsedMs > 1500)
    groupOffset = static_cast<int>((view.elapsedMs - 1500) / 90) % (groupWidth + 8);
  text(canvas, view.group, 1 - groupOffset, 6, view.groupColor, 3, 5, 1, false, 1, groupRight);
  if (groupWidth > groupRight - 1)
    text(canvas, view.group, 1 - groupOffset + groupWidth + 8, 6, view.groupColor, 3, 5, 1, false, 1, groupRight);
  const auto& signal = view.signal;
  const bool showMetric = (view.metricType == "MPH" || view.metricType == "LAP_TIME") &&
      (view.status.empty() || view.status == "LIVE" || (view.elapsedMs / 3000) % 2);
  const std::string status = showMetric ? (view.metricType == "MPH" ? "MPH" : "TIME") : view.status;
  const int flagLeft = 64 - signal.width;
  const int statusRight = flagLeft - 3;
  const int detailLeft = groupRight + 2;
  const bool fitsTogether = textWidth(view.session) + (view.session.empty() || status.empty() ? 0 : 3) + textWidth(status) <= statusRight - detailLeft;
  const bool showSession = !view.session.empty() && (status.empty() || (!fitsTogether && (view.elapsedMs / 3000) % 2 == 0));
  const std::string detail = fitsTogether && !view.session.empty() && !status.empty()
      ? view.session + " " + status : showSession ? view.session : status;
  const int statusWidth = textWidth(detail), availableStatus = statusRight - detailLeft;
  int statusOffset = 0;
  if (statusWidth > availableStatus && view.elapsedMs > 1500)
    statusOffset = static_cast<int>((view.elapsedMs - 1500) / 90) % (statusWidth + 8);
  const int statusLeft = statusWidth <= availableStatus ? statusRight - statusWidth : detailLeft - statusOffset;
  text(canvas, detail, statusLeft, 6, MUTED_TEXT, 3, 5, 1, false, detailLeft, statusRight);
  if (statusWidth > availableStatus)
    text(canvas, detail, statusLeft + statusWidth + 8, 6, MUTED_TEXT, 3, 5, 1, false, detailLeft, statusRight);
  for (int index = 0; index < signal.width * 6; ++index) {
    const bool alternate = signal.alternateMs && (view.signalPhaseMs / signal.alternateMs) % 2;
    const bool boardOff = alternate && signal.alternateBoardFlashes && (view.signalPhaseMs / 500) % 2;
    const uint16_t rgb = boardOff ? signal.alternateBoardOffPixels[index] : alternate ? signal.alternatePixels[index] : signal.pixels[index];
    canvas.pixel(flagLeft + index % signal.width, 6 + index / signal.width, {
      static_cast<uint8_t>(((rgb >> 11) & 31) * 255 / 31),
      static_cast<uint8_t>(((rgb >> 5) & 63) * 255 / 63),
      static_cast<uint8_t>((rgb & 31) * 255 / 31)});
  }
  canvas.rect(0, 12, 64, 1, HEADER_RULE);
  if (!view.count) {
    centered(canvas, view.upcoming ? "STARTS" : "NO TIMES", 0, 64, 16, MUTED_TEXT);
    centered(canvas, view.status, 0, 64, 25, blue);
    return;
  }
  for (int index = 0; index < view.count && index < 3; ++index) {
    const auto& row = view.rows[index];
    const int y = 13 + index * 7;
    text(canvas, std::to_string(row.position), 0, y, row.positionColor, 3, 5, 1, false, 0, 4);
    if (row.outlined) {
      NumberClip<Canvas> clipped{canvas};
      for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
        if (dx == 0 && dy == 0) continue;
        text(clipped, row.car, 6 + dx, y + dy, row.numberOutline, 3, 5, 1, false, 5, 18);
      }
    }
    text(canvas, row.car, 6, y, row.numberColor, 3, 5, 1, false, 6, 18);
    text(canvas, row.name, 19, y, SCORE_TEXT, 3, 5, 1, false, 19, 32);
    std::string metric = row.gap;
    const auto decimal = metric.find('.');
    while (textWidth(metric) > 31 && decimal != std::string::npos && metric.size() > decimal + 2 &&
           metric.back() >= '0' && metric.back() <= '9')
      metric.pop_back();
    const int metricWidth = textWidth(metric);
    int metricOffset = 0;
    if (metricWidth > 31 && view.elapsedMs > 1500)
      metricOffset = static_cast<int>((view.elapsedMs - 1500) / 90) % (metricWidth + 8);
    const int metricLeft = metricWidth <= 31 ? 64 - metricWidth : 33 - metricOffset;
    text(canvas, metric, metricLeft, y, row.metricColor, 3, 5, 1, false, 33, 64);
    if (metricWidth > 31)
      text(canvas, metric, metricLeft + metricWidth + 8, y, row.metricColor, 3, 5, 1, false, 33, 64);
  }
}
}  // namespace ticker_ui
