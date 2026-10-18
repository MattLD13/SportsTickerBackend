#include <array>
#include <cassert>
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

int main() {
  for (char ch : std::string("%")) {
    Canvas glyph;
    ticker_ui::text(glyph, std::string(1, ch), 0, 0, ticker_ui::SCORE_TEXT);
    bool visible = false;
    for (auto value : glyph.pixels) visible |= value != 0;
    assert(visible);
  }
  const char* cases[][4] = {
    {"AAPL", "212.48", "+1.25%", "+2.62"}, {"TSLA", "219.80", "-3.42%", "-7.78"},
    {"BRK.B", "485.19", "+0.00%", "+0.00"}, {"BTC-USD", "108521.35", "+12.45%", "+12000.50"},
    {"LONGSYMBOL", "12345678.90", "+1234.56%", "+123456.78"}, {"UNK", "--", "--", "--"}
  };
  for (const auto& row : cases) {
    JsonDocument data;
    data["symbol"] = row[0]; data["home_score"] = row[1]; data["away_score"] = row[2]; data["situation"]["change"] = row[3];
    const auto view = ticker_ui::stockPane(data.as<JsonObjectConst>());
    if (std::string(row[3]) != "--") assert(view.change.find('$') != std::string::npos);
    Canvas canvas;
    ticker_ui::renderStock(canvas, view);
    bool present = false;
    for (auto value : canvas.pixels) present |= value != 0;
    assert(present);
  }
  std::cout << "Stock quote formatting, gains, losses, long values, and frame bounds pass\n";
}
