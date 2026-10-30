// Draw the device states: startup, connection, errors, updates, the empty and offline screens, and pairing.
// A state that can follow content draws as a small overlay over the last content frame.
#pragma once

#include "text.h"

namespace mini_ui {

enum class SystemKind { Startup, Connecting, Registering, Offline, Error, Empty, Assets,
                        Checking, Downloading, Installing, UpdateFailed, TimeSync, DeviceKey };

struct SystemPane {
  SystemKind kind = SystemKind::Startup;
  std::string title, detail, footer, clock, date;
  uint32_t elapsedMs = 0, ageSeconds = 0;
  int percent = -1;
};

enum class PairingStage { WiFiSetup, AppPairing };

struct PairingPane {
  PairingStage stage = PairingStage::WiFiSetup;
  std::string code;
  uint32_t elapsedMs = 0;
};

inline bool systemKind(const std::string& name, SystemKind& kind) {
  static const char* const names[] = {"startup", "connecting", "registering", "offline", "error", "empty", "assets",
                                      "checking", "downloading", "installing", "update_failed", "time_sync", "device_key"};
  for (int index = 0; index < 13; ++index) {
    if (name == names[index]) { kind = static_cast<SystemKind>(index); return true; }
  }
  return false;
}

// Return the lines of one state. Progress states show a percent when the total is known.
inline SystemPane systemPane(SystemKind kind, const std::string& detail, uint32_t complete = 0, uint32_t total = 0, uint32_t elapsedMs = 0) {
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
  if (kind == SystemKind::Downloading || kind == SystemKind::Assets || kind == SystemKind::Installing) {
    if (total) view.percent = static_cast<int>(std::min<uint64_t>(100, static_cast<uint64_t>(complete) * 100 / total));
    view.footer = kind == SystemKind::Assets ? std::to_string(complete) + "/" + std::to_string(total) : "PLEASE WAIT";
  }
  return view;
}

inline bool systemOverlay(SystemKind kind) {
  return kind == SystemKind::Offline || kind == SystemKind::Error || kind == SystemKind::Checking ||
         kind == SystemKind::Downloading || kind == SystemKind::Installing || kind == SystemKind::UpdateFailed;
}

inline PairingPane pairingPane(bool wifiSetup, const std::string& wifiPin, const std::string& appCode, uint32_t elapsedMs = 0) {
  return {wifiSetup ? PairingStage::WiFiSetup : PairingStage::AppPairing, wifiSetup ? wifiPin : appCode, elapsedMs};
}

namespace device {

static constexpr Motion lineMotion{1200, 1, 110, 7};
static constexpr Rgb cyan{0, 200, 230}, green{0, 200, 100}, amber{255, 170, 0}, red{255, 75, 75};
static constexpr Rgb white{220, 220, 230}, grey{125, 135, 150}, railInk{24, 33, 40};

inline std::string age(uint32_t seconds) {
  return seconds < 60 ? std::to_string(seconds) + "S" : seconds < 3600 ? std::to_string(seconds / 60) + "M" : std::to_string(seconds / 3600) + "H";
}

// The empty screen shows the date, the title, the time, and the footer.
// The offline screen shows the date, the time, "NO LINK" with the age of the last data, and the detail.
template<class Canvas>
void clockScreen(Canvas& canvas, const SystemPane& view) {
  const bool offline = view.kind == SystemKind::Offline;
  const std::string time = view.clock.empty() ? "--:--" : view.clock;
  center(canvas, view.date, 0, PANE_WIDTH, 1, grey);
  if (offline) {
    center(canvas, time, 0, 43, 11, white, {4, 10});
    center(canvas, "NO", 43, 21, 9, amber);
    center(canvas, "LINK", 43, 21, 16, amber);
    center(canvas, age(view.ageSeconds), 43, 21, 24, {150, 110, 0});
    marquee(canvas, view.detail.empty() ? "RETRY" : view.detail, 1, 42, 25, grey, view.elapsedMs, lineMotion, true);
  } else {
    center(canvas, view.title, 0, PANE_WIDTH, 8, white);
    center(canvas, time, 0, PANE_WIDTH, 15, white, {4, 9});
    center(canvas, view.footer, 0, PANE_WIDTH, 26, grey);
  }
  canvas.rect(0, 31, PANE_WIDTH, 1, offline ? Rgb{90, 60, 0} : railInk);
}

// A failure shows a warning triangle. Other states show a spinner of eight fading dots.
template<class Canvas>
void mark(Canvas& canvas, bool failure, Rgb accent, uint32_t ms) {
  if (failure) {
    for (int row = 0; row < 7; ++row) canvas.rect(7 - row / 2, 13 + row, 1 + row, 1, accent);
    canvas.rect(7, 15, 1, 2, BACKGROUND);
    canvas.pixel(7, 18, BACKGROUND);
    return;
  }
  static constexpr int xs[] = {7, 10, 12, 10, 7, 4, 2, 4}, ys[] = {11, 13, 16, 19, 21, 19, 16, 13};
  const int phase = (ms / 100) % 8;
  for (int index = 0; index < 8; ++index) {
    const int intensity = 255 - ((index + 8 - phase) % 8) * 26;
    canvas.pixel(xs[index], ys[index], {0, static_cast<uint8_t>(intensity * 180 / 255), static_cast<uint8_t>(intensity)});
  }
  canvas.rect(6, 15, 3, 3, {0, 150, 170});
}

// Draw a green fill for a known percent, or else a green pulse that moves along the rail.
template<class Canvas>
void rail(Canvas& canvas, const SystemPane& view, bool failure, Rgb accent) {
  canvas.rect(0, 0, PANE_WIDTH, 1, railInk);
  const int sweep = (view.elapsedMs / 40) % 76;
  for (int x = std::max(0, sweep); x < std::min(PANE_WIDTH, sweep + 12); ++x) canvas.pixel(x, 0, accent);
  canvas.rect(0, 31, PANE_WIDTH, 1, railInk);
  if (view.percent >= 0) {
    const int fill = std::min(100, view.percent) * PANE_WIDTH / 100;
    if (fill) canvas.rect(0, 31, fill, 1, green);
  } else if (!failure) {
    const int start = (view.elapsedMs / 50) % 80;
    for (int x = std::max(0, start); x < std::min(PANE_WIDTH, start + 16); ++x) canvas.pixel(x, 31, green);
  }
}

}  // namespace device

template<class Canvas>
void draw(Canvas& canvas, const SystemPane& view) {
  using namespace device;
  const bool failure = view.kind == SystemKind::Error || view.kind == SystemKind::UpdateFailed || view.kind == SystemKind::DeviceKey;
  const bool offline = view.kind == SystemKind::Offline;
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  if (offline || view.kind == SystemKind::Empty) {
    clockScreen(canvas, view);
    return;
  }
  const Rgb accent = failure ? red : cyan;
  marquee(canvas, view.title, 1, 63, 3, failure ? red : white, view.elapsedMs, lineMotion, true);
  marquee(canvas, view.detail, 15, 63, 14, grey, view.elapsedMs, lineMotion, true);
  marquee(canvas, view.footer, 15, 63, 25, failure ? grey : cyan, view.elapsedMs, lineMotion, true);
  mark(canvas, failure, accent, view.elapsedMs);
  rail(canvas, view, failure, accent);
}

// Over content, a lost link shows a crossed-out panel icon in the top corner.
// An update shows a small box in the low corner with its progress bar.
template<class Canvas>
void drawOverlay(Canvas& canvas, const SystemPane& view) {
  const Rgb cyan{100, 220, 255}, red{255, 75, 75}, frame{210, 215, 225};
  if (view.kind == SystemKind::Offline || view.kind == SystemKind::Error) {
    canvas.rect(56, 0, 8, 7, {0, 0, 0});
    for (int x = 57; x <= 61; ++x) { canvas.pixel(x, 1, frame); canvas.pixel(x, 5, frame); }
    for (int y = 1; y <= 5; ++y) { canvas.pixel(57, y, frame); canvas.pixel(61, y, frame); }
    canvas.rect(58, 3, 3, 1, {100, 110, 125});
    for (int index = 0; index < 8; ++index) canvas.pixel(56 + index, 6 - (index * 6 + 3) / 7, {255, 70, 70});
    return;
  }
  const bool failure = view.kind == SystemKind::UpdateFailed;
  canvas.rect(30, 19, 34, 13, {2, 6, 10});
  canvas.rect(30, 19, 34, 1, {25, 50, 60});
  center(canvas, failure ? "FAILED" : "UPDATE", 32, 30, 20, failure ? red : cyan);
  canvas.rect(33, 27, 28, 3, failure ? Rgb{75, 20, 20} : Rgb{25, 50, 60});
  if (failure) return;
  if (view.percent >= 0) {
    const int fill = std::min(100, view.percent) * 28 / 100;
    if (fill) canvas.rect(33, 27, fill, 3, {0, 200, 120});
    return;
  }
  const int start = (view.elapsedMs / 100) % 36 - 8;
  for (int x = std::max(0, start); x < std::min(28, start + 8); ++x) canvas.rect(33 + x, 27, 1, 3, cyan);
}

template<class Canvas>
void draw(Canvas& canvas, const PairingPane& view) {
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  const bool wifi = view.stage == PairingStage::WiFiSetup;
  canvas.rect(0, 31, PANE_WIDTH, 1, {35, 45, 55});
  center(canvas, wifi ? "WIFI PIN" : "PAIR CODE", 0, PANE_WIDTH, 1, {255, 200, 0});
  // A dot in the corner blinks twice each second while the ticker waits.
  if ((view.elapsedMs / 500) % 2 == 0) canvas.rect(60, 1, 2, 2, {0, 200, 255});
  center(canvas, view.code.empty() ? "WAIT" : view.code, 0, PANE_WIDTH, 11, SCORE_TEXT, {5, 9, 1});
  center(canvas, wifi ? "OPEN APP" : "ADD TICKER", 0, PANE_WIDTH, 26, {125, 165, 190});
}

}  // namespace mini_ui
