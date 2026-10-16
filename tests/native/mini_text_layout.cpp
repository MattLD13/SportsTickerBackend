#include "text_layout.h"

#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>

struct Surface {
  std::array<uint16_t, 64 * 32> pixels{};
  void fillRect(int x, int y, int width, int height, uint16_t ink) {
    for (int row = y; row < y + height; ++row) {
      for (int column = x; column < x + width; ++column) {
        if (column >= 0 && column < 64 && row >= 0 && row < 32) pixels[row * 64 + column] = ink;
      }
    }
  }
};

static void referenceBeforeModule(Surface& surface, const char* text, int x, int y, uint8_t scale) {
  int cursor = x + 1;
  for (size_t character = 0; character < std::strlen(text); ++character) {
    char bits[16]{};
    const uint8_t* glyph = ticker_ui::pane[ticker_ui::glyphIndex(text[character])];
    for (uint8_t row = 0; row < 5; ++row) {
      for (uint8_t column = 0; column < 3; ++column) bits[row * 3 + column] = glyph[row] & (1 << (2 - column)) ? '1' : '0';
    }
    for (uint8_t row = 0; row < 5; ++row) {
      for (uint8_t column = 0; column < 3; ++column) {
        if (bits[row * 3 + column] == '1') surface.fillRect(cursor + column * scale, y + row * scale, scale, scale, 0xAFE1);
      }
    }
    cursor += 4 * scale;
  }
}

static void compare(const char* text, int x, int y, uint8_t scale) {
  Surface before, after;
  referenceBeforeModule(before, text, x, y, scale);
  mini_text::drawPaneText(after, text, std::strlen(text), x, y, 0xAFE1, scale);
  assert(before.pixels == after.pixels);
}

int main() {
  unsigned checks = 0;
  for (int value = 32; value < 127; ++value) {
    const char text[] = {static_cast<char>(value), '\0'};
    for (const int x : {-2, 0, 13, 60}) for (const int y : {-1, 1, 24, 30}) for (const uint8_t scale : {1, 2}) {
      compare(text, x, y, scale);
      ++checks;
    }
  }
  for (const char* text : {"BETHLEHEM", "BLINDING LIGHTS", "EWR>LAX", "#88 0:45", "12:34", "", "a?z"}) {
    compare(text, 2, 10, 1);
    compare(text, 16, 10, 2);
    checks += 2;
  }
  std::printf("Mini text module matches %u original drawing cases\n", checks);
}
