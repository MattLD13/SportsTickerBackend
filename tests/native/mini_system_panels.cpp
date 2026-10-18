#include <array>
#include <cassert>
#include <fstream>
#include <iostream>
#include <panels.h>

struct Canvas {
  std::array<uint8_t, 64 * 32 * 3> pixels{};
  void pixel(int x, int y, ticker_ui::Rgb ink) {
    assert(x >= 0 && x < 64 && y >= 0 && y < 32);
    const int offset = (y * 64 + x) * 3;
    pixels[offset] = ink.r; pixels[offset + 1] = ink.g; pixels[offset + 2] = ink.b;
  }
  void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) {
    for (int dy = 0; dy < height; ++dy) for (int dx = 0; dx < width; ++dx) pixel(x + dx, y + dy, ink);
  }
};

int main(int argc, char** argv) {
  assert(argc == 2);
  std::ifstream input(argv[1]);
  JsonDocument document;
  assert(!deserializeJson(document, input));
  int statuses = 0;
  for (JsonObjectConst row : document["cases"].as<JsonArrayConst>()) {
    const std::string mode = row["mode"] | "";
    if (mode == "message") {
      for (uint32_t ms : {0, 100, 1700, 7900}) {
        ticker_ui::SystemPane view;
        assert(ticker_ui::systemPane(row["game"].as<JsonObjectConst>(), ms, view));
        Canvas canvas;
        ticker_ui::renderSystem(canvas, view);
      }
      ++statuses;
    } else if (mode == "pairing") {
      for (uint32_t ms : {0, 500}) {
        Canvas canvas;
        ticker_ui::renderPairing(canvas, ticker_ui::pairingPane(row["game"]["wifi_setup"] | false,
            row["game"]["wifi_pin"] | "", row["game"]["app_code"] | "", ms));
      }
    }
  }
  assert(statuses == 16);
  using ticker_ui::SystemKind;
  assert(ticker_ui::systemPane(SystemKind::Downloading, "", 0, 0).percent == -1);
  assert(ticker_ui::systemPane(SystemKind::Downloading, "", UINT32_MAX, 1).percent == 100);
  Canvas complete;
  ticker_ui::renderSystem(complete, ticker_ui::systemPane(SystemKind::Assets, "", 12, 12));
  for (int x = 0; x < 64; ++x) assert(complete.pixels[(31 * 64 + x) * 3 + 1] == 200);
  Canvas first, later;
  ticker_ui::renderSystem(first, ticker_ui::systemPane(SystemKind::Startup, "", 0, 0, 0));
  ticker_ui::renderSystem(later, ticker_ui::systemPane(SystemKind::Startup, "", 0, 0, 100));
  assert(first.pixels != later.pixels);
  for (auto kind : {SystemKind::Offline, SystemKind::Checking, SystemKind::Downloading, SystemKind::Installing, SystemKind::UpdateFailed, SystemKind::Error}) {
    Canvas overlay;
    overlay.rect(0, 0, 64, 32, {30, 60, 90});
    const auto original = overlay.pixels;
    ticker_ui::renderSystemOverlay(overlay, ticker_ui::systemPane(kind, "HTTP 503", 50, 100, 1700));
    for (int y = 0; y < 32; ++y) for (int x = 0; x < 64; ++x) {
      const bool connection = kind == SystemKind::Offline || kind == SystemKind::Error;
      if (connection ? x >= 56 && y < 7 : x >= 30 && y >= 19) continue;
      const int offset = (y * 64 + x) * 3;
      for (int channel = 0; channel < 3; ++channel) assert(overlay.pixels[offset + channel] == original[offset + channel]);
    }
    assert(overlay.pixels != original);
  }
  Canvas downloading;
  ticker_ui::renderSystemOverlay(downloading, ticker_ui::systemPane(SystemKind::Downloading, "", 50, 100));
  for (int x = 33; x < 47; ++x) assert(downloading.pixels[(27 * 64 + x) * 3 + 1] == 200);
  for (int x = 47; x < 61; ++x) assert(downloading.pixels[(27 * 64 + x) * 3 + 1] == 50);
  ticker_ui::SystemKind unknown;
  assert(!ticker_ui::systemKind("unknown", unknown));
  std::cout << "System lifecycle states, animation, progress bounds, pairing, and frame bounds pass\n";
}
