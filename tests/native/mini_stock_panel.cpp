#include <array>
#include <cassert>
#include <iostream>
#include <panes.h>

struct Canvas {
  std::array<uint8_t, 64 * 32 * 3> pixels{};
  bool ready = false;
  bool logo(mini_ui::Side, int x, int y) {
    if (!ready) return false;
    rect(x, y, mini_ui::MINI_LOGO_SIZE, mini_ui::MINI_LOGO_SIZE, {40, 120, 220});
    return true;
  }
  void pixel(int x, int y, mini_ui::Rgb ink) {
    assert(x >= 0 && x < 64 && y >= 0 && y < 32);
    const int offset = (y * 64 + x) * 3;
    pixels[offset] = ink.r; pixels[offset + 1] = ink.g; pixels[offset + 2] = ink.b;
  }
  void rect(int x, int y, int width, int height, mini_ui::Rgb ink) {
    for (int dy = 0; dy < height; ++dy) for (int dx = 0; dx < width; ++dx) pixel(x + dx, y + dy, ink);
  }
};

int main() {
  for (char ch : std::string("%")) {
    Canvas glyph;
    mini_ui::drawText(glyph, std::string(1, ch), 0, 0, mini_ui::SCORE_TEXT);
    bool visible = false;
    for (auto value : glyph.pixels) visible |= value != 0;
    assert(visible);
  }
  const char* cases[][3] = {
    {"AAPL", "212.48", "+1.25%"}, {"TSLA", "219.80", "-3.42%"},
    {"BRK.B", "485.19", "+0.00%"}, {"BTC-USD", "108521.35", "+12.45%"},
    {"LONGSYMBOL", "12345678.90", "+1234.56%"}, {"UNK", "--", "--"}
  };
  for (const auto& row : cases) {
    JsonDocument data;
    data["symbol"] = row[0]; data["home_score"] = row[1]; data["away_score"] = row[2];
    const auto view = mini_ui::stockPane(data.as<JsonObjectConst>());
    assert(view.price == (std::string(row[1]) == "--" ? "--" : "$" + std::string(row[1])));
    Canvas canvas;
    mini_ui::draw(canvas, view);
    bool present = false;
    for (auto value : canvas.pixels) present |= value != 0;
    assert(present);
    Canvas branded;
    branded.ready = true;
    mini_ui::draw(branded, view);
    assert(branded.pixels != canvas.pixels);
    for (int y = 20; y < 32; ++y) for (int x = 0; x < 64; ++x) for (int c = 0; c < 3; ++c) {
      const int offset = (y * 64 + x) * 3 + c;
      assert(branded.pixels[offset] == canvas.pixels[offset]);
    }
  }
  std::cout << "Stock quote formatting, gains, losses, long values, and frame bounds pass\n";
}
