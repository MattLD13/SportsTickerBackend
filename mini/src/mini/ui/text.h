// Draw the shared ticker glyphs at any size on a Mini canvas.
//
// A canvas is any type with these members:
//   void pixel(int x, int y, Rgb ink);
//   void rect(int x, int y, int width, int height, Rgb ink);
//   bool logo(Side side, int x, int y);   // sports and stock panes: draw a prepared logo, or return false
//   bool artwork();                       // music pane: draw the prepared cover, or return false
// Drawing does no I/O. The panel is 64x32 pixels.
#pragma once

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <string>
#include <utility>
#include "generated.h"

namespace mini_ui {

static constexpr int PANE_WIDTH = 64, PANE_HEIGHT = 32;

// One size of type. A pane glyph has 1 to 8 source columns and 5 rows. A hybrid glyph has 4 columns and 6 rows.
// Each glyph samples its source bits at the drawn size.
struct Type {
  int width = 3, height = 5, gap = 1;
  bool hybrid = false;
  int wordSpace = 1;
};

// The horizontal limits of a text run. Pixels outside [left, right) do not draw.
struct Clip {
  int left = 0, right = PANE_WIDTH;
};

inline int glyph(char ch) {
  const int upper = std::toupper(static_cast<unsigned char>(ch));
  return upper >= 32 && upper <= 126 ? upper - 32 : 0;
}

inline int glyphWidth(char ch, const Type& type) {
  if (type.hybrid) return type.width;
  if (ch == ' ') return type.wordSpace * std::max(1, type.width / 3);
  return (paneWidths[glyph(ch)] * type.width + 1) / 3;
}

inline int measure(const std::string& value, const Type& type = {}) {
  int size = 0;
  for (char ch : value) size += glyphWidth(ch, type) + type.gap;
  return value.empty() ? 0 : size - type.gap;
}

template<class Canvas>
void drawText(Canvas& canvas, const std::string& value, int x, int y, Rgb ink, const Type& type = {}, Clip clip = {}) {
  const int rows = type.hybrid ? 6 : 5;
  for (char ch : value) {
    const int index = glyph(ch);
    const int columns = type.hybrid ? 4 : paneWidths[index];
    const int drawn = glyphWidth(ch, type);
    for (int dy = 0; dy < type.height; ++dy) {
      const int row = ((2 * dy + 1) * rows) / (2 * type.height);
      const uint8_t bits = type.hybrid ? hybrid[index][row] : pane[index][row];
      for (int dx = 0; dx < drawn; ++dx) {
        const int column = ((2 * dx + 1) * columns) / (2 * drawn);
        if (x + dx >= clip.left && x + dx < clip.right && (bits & (1 << (columns - 1 - column)))) canvas.pixel(x + dx, y + dy, ink);
      }
    }
    x += drawn + type.gap;
  }
}

// Center the text in [left, left + span) and clip it to that span.
template<class Canvas>
void center(Canvas& canvas, const std::string& value, int left, int span, int y, Rgb ink, const Type& type = {}) {
  drawText(canvas, value, left + (span - measure(value, type) + 1) / 2, y, ink, type, {left, left + span});
}

// Return the first and the count of the columns with ink in one 3x5 pane glyph.
inline int inkColumns(char ch, int& first) {
  const int index = glyph(ch), columns = paneWidths[index];
  uint8_t bits = 0;
  for (int row = 0; row < 5; ++row) bits |= pane[index][row];
  first = 0;
  if (!bits) return 1;
  int last = columns - 1;
  while (!(bits & (1 << (columns - 1 - first)))) ++first;
  while (!(bits & (1 << (columns - 1 - last)))) --last;
  return last - first + 1;
}

inline int measureInk(const std::string& value, int gap) {
  int size = 0, first = 0;
  for (char ch : value) size += inkColumns(ch, first) + gap;
  return value.empty() ? 0 : size - gap;
}

// Draw 3x5 pane glyphs without their empty side columns, so a dense label fits.
template<class Canvas>
int drawInk(Canvas& canvas, const std::string& value, int x, int y, Rgb ink, int gap) {
  for (char ch : value) {
    const int index = glyph(ch), columns = paneWidths[index];
    int first = 0;
    const int width = inkColumns(ch, first);
    for (int row = 0; row < 5; ++row) for (int column = 0; column < width; ++column) {
      if (pane[index][row] & (1 << (columns - 1 - first - column))) canvas.pixel(x + column, y + row, ink);
    }
    x += width + gap;
  }
  return x;
}

// The motion of a text that is wider than its span. It holds still for `delayMs`, then moves
// `pixels / perMs` pixels for each millisecond. A second copy follows `spacing` pixels after the text ends.
struct Motion {
  uint32_t delayMs, pixels, perMs;
  int spacing;
};

// Draw a text that fits in [left, right) as given, or scroll it in a loop when it does not fit.
template<class Canvas>
void marquee(Canvas& canvas, const std::string& value, int left, int right, int y, Rgb ink, uint32_t ms,
             const Motion& motion, bool centerFit) {
  const int width = measure(value);
  if (width <= right - left) {
    if (centerFit) center(canvas, value, left, right - left, y, ink);
    else drawText(canvas, value, left, y, ink, {}, {left, right});
    return;
  }
  const int period = width + motion.spacing;
  const int offset = ms < motion.delayMs ? 0 :
      static_cast<int>(static_cast<uint64_t>(ms - motion.delayMs) * motion.pixels / motion.perMs % period);
  drawText(canvas, value, left - offset, y, ink, {}, {left, right});
  drawText(canvas, value, left - offset + period, y, ink, {}, {left, right});
}

}  // namespace mini_ui
