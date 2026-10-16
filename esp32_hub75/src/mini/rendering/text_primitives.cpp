#include "text_primitives.h"

#include <Adafruit_GFX.h>
#include "text_layout.h"

namespace mini_text {

void drawText(Adafruit_GFX& surface, const String& value, int16_t x, int16_t y, uint16_t foreground) {
  surface.setTextColor(foreground);
  surface.setCursor(x, y);
  surface.print(value);
}

void drawTextFit(Adafruit_GFX& surface, const String& value, int16_t x, int16_t y, uint16_t foreground, int16_t width) {
  String clipped = value;
  const size_t maximum = width > 0 ? static_cast<size_t>(width / 6) : 0;
  if (clipped.length() > maximum) clipped.remove(maximum);
  drawText(surface, clipped, x, y, foreground);
}

void drawTextRight(Adafruit_GFX& surface, const String& value, int16_t right, int16_t y, uint16_t foreground, int16_t left) {
  String clipped = value;
  const int16_t width = right - left;
  const size_t maximum = width > 0 ? static_cast<size_t>(width / 6) : 0;
  if (clipped.length() > maximum) clipped.remove(maximum);
  drawText(surface, clipped, right - static_cast<int16_t>(clipped.length() * 6), y, foreground);
}

void drawPixelText(Adafruit_GFX& surface, const String& value, int16_t x, int16_t y, uint16_t foreground, uint8_t scale) {
  drawPaneText(surface, value.c_str(), value.length(), x, y, foreground, scale);
}

void drawPixelTextFit(Adafruit_GFX& surface, const String& value, int16_t x, int16_t y, uint16_t foreground, uint8_t scale, int16_t width) {
  String clipped = value;
  const size_t maximum = width > 0 ? static_cast<size_t>(width / (4 * scale)) : 0;
  if (clipped.length() > maximum) clipped.remove(maximum);
  drawPixelText(surface, clipped, x, y, foreground, scale);
}

}  // namespace mini_text
