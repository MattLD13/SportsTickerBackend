#pragma once

#include <Arduino.h>

class Adafruit_GFX;

namespace mini_text {

void drawText(Adafruit_GFX& surface, const String& value, int16_t x, int16_t y, uint16_t foreground);
void drawTextFit(Adafruit_GFX& surface, const String& value, int16_t x, int16_t y, uint16_t foreground, int16_t width);
void drawTextRight(Adafruit_GFX& surface, const String& value, int16_t right, int16_t y, uint16_t foreground, int16_t left);
void drawPixelText(Adafruit_GFX& surface, const String& value, int16_t x, int16_t y, uint16_t foreground, uint8_t scale = 1);
void drawPixelTextFit(Adafruit_GFX& surface, const String& value, int16_t x, int16_t y, uint16_t foreground, uint8_t scale, int16_t width);

}  // namespace mini_text
