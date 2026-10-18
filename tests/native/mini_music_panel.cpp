#include <array>
#include <cassert>
#include <iostream>
#include <panels.h>

struct Canvas {
  std::array<uint8_t, 64 * 32 * 3> pixels{};
  bool ready = true;
  void pixel(int x, int y, ticker_ui::Rgb ink) {
    assert(x >= 0 && x < 64 && y >= 0 && y < 32);
    const int index = (y * 64 + x) * 3;
    pixels[index] = ink.r; pixels[index + 1] = ink.g; pixels[index + 2] = ink.b;
  }
  void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) {
    for (int dy = 0; dy < height; ++dy) for (int dx = 0; dx < width; ++dx) pixel(x + dx, y + dy, ink);
  }
  bool artwork() { if (ready) rect(0, 0, 32, 32, {40, 80, 120}); return ready; }
};

int main() {
  JsonDocument data;
  data["id"] = "track";
  data["name"] = "Everybody Wants To Rule The World";
  data["artist"] = "Tears For Fears";
  data["duration"] = 200.0;
  data["progress"] = 100.0;
  data["fetch_ts"] = 1800000000.0;
  data["is_playing"] = true;
  auto accent = data["cover_asset"]["accent_rgb"].to<JsonArray>();
  accent.add(220); accent.add(90); accent.add(40);
  auto view = ticker_ui::musicPane(data.as<JsonObjectConst>(), 1800000001.0, 0);
  assert(view.remaining == "-1:39" && view.fraction > .50 && view.fraction < .51);
  assert(view.accent.r == 220 && view.accent.g == 90 && view.accent.b == 40);
  Canvas first;
  ticker_ui::renderMusic(first, view);
  for (int x = 0; x < 32; ++x) assert(first.pixels[(31 * 64 + x) * 3] == 220);
  for (int x = 32; x < 64; ++x) assert(first.pixels[(31 * 64 + x) * 3] == 44);
  view.scrollMs = 4000;
  Canvas scrolled;
  ticker_ui::renderMusic(scrolled, view);
  assert(first.pixels != scrolled.pixels);
  for (int y = 0; y < 31; ++y) for (int x = 0; x < 32; ++x) {
    const int i = (y * 64 + x) * 3;
    assert(scrolled.pixels[i] == 40 && scrolled.pixels[i + 1] == 80 && scrolled.pixels[i + 2] == 120);
  }
  data["is_playing"] = false;
  auto paused = ticker_ui::musicPane(data.as<JsonObjectConst>(), 1800000100.0, 0);
  assert(paused.remaining == "-1:40" && paused.fraction == .5);
  assert(paused.accent.r == 220);
  data["progress"] = 250.0;
  assert(ticker_ui::musicPane(data.as<JsonObjectConst>(), 1800000000.0, 0).remaining == "-0:00");
  data["duration"] = 0;
  assert(ticker_ui::musicPane(data.as<JsonObjectConst>(), 1800000000.0, 0).remaining == "--:--");
  Canvas missing;
  missing.ready = false;
  ticker_ui::renderMusic(missing, paused);
  assert(missing.pixels != first.pixels);
  assert(missing.pixels[(12 * 64 + 12) * 3] == 170);
  data["status"] = "idle";
  data["duration"] = 0;
  const auto idle = ticker_ui::musicPane(data.as<JsonObjectConst>(), 1800000000.0, 0);
  assert(idle.idle && idle.title == "NO MUSIC" && idle.artist == "PLAY A SONG");
  Canvas idleFrame;
  ticker_ui::renderMusic(idleFrame, idle);
  assert(idleFrame.pixels[(12 * 64 + 12) * 3] == 170);
  for (int x = 0; x < 64; ++x) assert(idleFrame.pixels[(31 * 64 + x) * 3] == 44);
  std::cout << "Music cover clipping, scrolling, seconds, pause, completion, and unknown duration pass\n";
}
