#pragma once

#include <stddef.h>
#include <stdint.h>
#include "glyphs.h"

namespace mini_text {

static constexpr int16_t CONTENT_X_OFFSET = 1;

template <class Surface>
void drawPaneText(Surface& surface, const char* text, size_t length, int16_t x, int16_t y,
                  uint16_t foreground, uint8_t scale) {
  int16_t cursor = x + CONTENT_X_OFFSET;
  for (size_t character = 0; character < length; ++character) {
    const uint8_t* rows = ticker_ui::pane[ticker_ui::glyphIndex(text[character])];
    for (uint8_t row = 0; row < 5; ++row) {
      for (uint8_t column = 0; column < 3; ++column) {
        if (rows[row] & (1 << (2 - column))) {
          surface.fillRect(cursor + column * scale, y + row * scale, scale, scale, foreground);
        }
      }
    }
    cursor += 4 * scale;
  }
}

}  // namespace mini_text
