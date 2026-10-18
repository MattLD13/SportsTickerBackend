#pragma once
#include "sports_pane.h"

namespace ticker_ui {
enum class SystemKind { Startup, Connecting, Registering, Offline, Error, Empty, Assets,
                        Checking, Downloading, Installing, UpdateFailed, TimeSync, DeviceKey };

struct SystemPane {
  SystemKind kind = SystemKind::Startup;
  std::string title, detail, footer, clock, date;
  uint32_t elapsedMs = 0, ageSeconds = 0;
  int percent = -1;
};

inline bool systemKind(const std::string& name, SystemKind& kind) {
  const char* names[] = {"startup", "connecting", "registering", "offline", "error", "empty", "assets",
                         "checking", "downloading", "installing", "update_failed", "time_sync", "device_key"};
  for (int index = 0; index < 13; ++index) {
    if (name == names[index]) { kind = static_cast<SystemKind>(index); return true; }
  }
  return false;
}

inline SystemPane systemPane(SystemKind kind, const std::string& detail, uint32_t complete = 0,
                             uint32_t total = 0, uint32_t elapsedMs = 0) {
  SystemPane view;
  view.kind = kind;
  view.elapsedMs = elapsedMs;
  view.detail = detail;
  switch (kind) {
    case SystemKind::Startup: view.title = "STARTING"; view.detail = "MINI TICKER"; view.footer = detail.empty() ? "PLEASE WAIT" : detail; break;
    case SystemKind::Connecting: view.title = "WIFI CHECK"; view.footer = "CONNECTING"; break;
    case SystemKind::Registering: view.title = "CONNECTING"; view.footer = "TICKER SERVER"; break;
    case SystemKind::Offline: view.title = "NO LINK"; view.footer = "RECONNECTING"; break;
    case SystemKind::Error: view.title = "DATA ERROR"; view.footer = "RETRYING"; break;
    case SystemKind::Empty: view.title = detail; view.detail = ""; view.footer = "CHECK BACK"; break;
    case SystemKind::Assets: view.title = "LOADING"; view.detail = "TEAM LOGOS"; break;
    case SystemKind::Checking: view.title = "UPDATING"; view.detail = "CHECK RELEASE"; view.footer = detail; break;
    case SystemKind::Downloading: view.title = "UPDATING"; view.detail = "DOWNLOADING"; break;
    case SystemKind::Installing: view.title = "UPDATING"; view.detail = "INSTALLING"; view.footer = "RESTARTING"; break;
    case SystemKind::UpdateFailed: view.title = "UPDATE FAILED"; view.footer = "RETRY LATER"; break;
    case SystemKind::TimeSync: view.title = "CLOCK SYNC"; view.footer = "PLEASE WAIT"; break;
    case SystemKind::DeviceKey: view.title = "DEVICE KEY"; view.footer = "USB SETUP"; break;
  }
  if (kind == SystemKind::Downloading || kind == SystemKind::Assets) {
    if (total) view.percent = static_cast<int>(std::min<uint64_t>(100, static_cast<uint64_t>(complete) * 100 / total));
    view.footer = kind == SystemKind::Assets ? std::to_string(complete) + "/" + std::to_string(total) :
        (view.percent < 0 ? "PLEASE WAIT" : std::to_string(view.percent) + "%");
  }
  return view;
}

template<class Canvas>
void systemMarquee(Canvas& canvas, const std::string& value, int left, int right, int y, Rgb ink, uint32_t ms) {
  const int width = textWidth(value);
  if (width <= right - left) { centered(canvas, value, left, right - left, y, ink); return; }
  const std::string cycle = value + "   ";
  const int offset = ms < 1200 ? 0 : ((ms - 1200) / 110) % (textWidth(cycle) + 1);
  text(canvas, cycle + value, left - offset, y, ink, 3, 5, 1, false, left, right);
}

inline bool systemOverlay(SystemKind kind) {
  return kind == SystemKind::Offline || kind == SystemKind::Error || kind == SystemKind::Checking ||
         kind == SystemKind::Downloading || kind == SystemKind::Installing || kind == SystemKind::UpdateFailed;
}

template<class Canvas>
void renderSystemOverlay(Canvas& canvas, const SystemPane& view) {
  const Rgb cyan{100, 220, 255}, amber{255, 170, 0}, red{255, 75, 75};
  const bool failure = view.kind == SystemKind::Error || view.kind == SystemKind::UpdateFailed;
  const bool offline = view.kind == SystemKind::Offline;
  const Rgb accent = failure ? red : offline ? amber : cyan;
  canvas.rect(30, 19, 34, 13, {2, 6, 10});
  canvas.rect(30, 19, 34, 1, {25, 50, 60});
  const std::string title = offline ? "NO LINK" : view.kind == SystemKind::Error ? "ERROR" : "UPDATE";
  centered(canvas, title, 32, 30, 20, accent);
  std::string detail;
  if (offline) detail = "RETRY";
  else if (view.kind == SystemKind::Error) detail = view.detail;
  else if (view.kind == SystemKind::UpdateFailed) detail = "FAILED";
  else if (view.kind == SystemKind::Installing) detail = "INSTALL";
  else if (view.kind == SystemKind::Checking) detail = "CHECK";
  else detail = view.percent < 0 ? "WAIT" : std::to_string(view.percent) + "%";
  systemMarquee(canvas, detail, 32, 62, 26, accent, view.elapsedMs);
  canvas.rect(32, 31, 30, 1, {25, 50, 60});
  if (view.percent >= 0 && !failure) {
    const int fill = std::min(100, view.percent) * 30 / 100;
    if (fill) canvas.rect(32, 31, fill, 1, {0, 200, 120});
  }
}

template<class Canvas>
void renderSystem(Canvas& canvas, const SystemPane& view) {
  const Rgb cyan{0, 200, 230}, green{0, 200, 100}, amber{255, 170, 0}, red{255, 75, 75};
  const Rgb white{220, 220, 230}, grey{125, 135, 150}, rail{24, 33, 40};
  const bool failure = view.kind == SystemKind::Error || view.kind == SystemKind::UpdateFailed || view.kind == SystemKind::DeviceKey;
  const bool offline = view.kind == SystemKind::Offline;
  const bool empty = view.kind == SystemKind::Empty;
  const Rgb accent = failure ? red : offline ? amber : cyan;
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  if (offline || empty) {
    centered(canvas, view.date, 0, 64, 1, grey);
    if (empty) {
      centered(canvas, view.title, 0, 64, 8, white);
      centered(canvas, view.clock.empty() ? "--:--" : view.clock, 0, 64, 15, white, 4, 9);
      centered(canvas, view.footer, 0, 64, 26, grey);
    } else {
      centered(canvas, view.clock.empty() ? "--:--" : view.clock, 0, 43, 11, white, 4, 10);
      centered(canvas, "NO", 43, 21, 9, amber);
      centered(canvas, "LINK", 43, 21, 16, amber);
      const auto seconds = view.ageSeconds;
      const auto age = seconds < 60 ? std::to_string(seconds) + "S" : seconds < 3600 ?
          std::to_string(seconds / 60) + "M" : std::to_string(seconds / 3600) + "H";
      centered(canvas, age, 43, 21, 24, {150, 110, 0});
      systemMarquee(canvas, view.detail.empty() ? "RETRY" : view.detail, 1, 42, 25, grey, view.elapsedMs);
    }
    canvas.rect(0, 31, 64, 1, offline ? Rgb{90, 60, 0} : rail);
    return;
  }
  systemMarquee(canvas, view.title, 1, 63, 3, failure ? red : white, view.elapsedMs);
  systemMarquee(canvas, view.detail, 15, 63, 14, grey, view.elapsedMs);
  systemMarquee(canvas, view.footer, 15, 63, 25, failure ? grey : cyan, view.elapsedMs);
  if (failure) {
    for (int row = 0; row < 7; ++row) canvas.rect(7 - row / 2, 13 + row, 1 + row, 1, accent);
    canvas.rect(7, 15, 1, 2, BACKGROUND);
    canvas.pixel(7, 18, BACKGROUND);
  } else {
    const int xs[] = {7, 10, 12, 10, 7, 4, 2, 4};
    const int ys[] = {11, 13, 16, 19, 21, 19, 16, 13};
    const int phase = (view.elapsedMs / 100) % 8;
    for (int index = 0; index < 8; ++index) {
      const int intensity = 255 - ((index + 8 - phase) % 8) * 26;
      canvas.pixel(xs[index], ys[index], {0, static_cast<uint8_t>(intensity * 180 / 255), static_cast<uint8_t>(intensity)});
    }
    canvas.rect(6, 15, 3, 3, {0, 150, 170});
  }
  canvas.rect(0, 0, 64, 1, rail);
  const int sweep = (view.elapsedMs / 40) % 76;
  for (int x = std::max(0, sweep); x < std::min(64, sweep + 12); ++x) canvas.pixel(x, 0, accent);
  canvas.rect(0, 31, 64, 1, rail);
  if (view.percent >= 0) {
    const int fill = std::min(100, view.percent) * 64 / 100;
    if (fill) canvas.rect(0, 31, fill, 1, green);
  } else if (!failure) {
    const int start = (view.elapsedMs / 50) % 80;
    for (int x = std::max(0, start); x < std::min(64, start + 16); ++x) canvas.pixel(x, 31, green);
  }
}
}  // namespace ticker_ui
