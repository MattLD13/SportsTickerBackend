#pragma once

#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include "display_metrics.h"

class MiniMatrix : public MatrixPanel_I2S_DMA {
 public:
  explicit MiniMatrix(const HUB75_I2S_CFG& config) : MatrixPanel_I2S_DMA(config) {}
  void drawPixel(int16_t x, int16_t y, uint16_t ink) override;
  void drawPixelRGB888(int16_t x, int16_t y, uint8_t r, uint8_t g, uint8_t b);
  void fillScreen(uint16_t ink) override;
  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t ink) override;
  void drawFastHLine(int16_t x, int16_t y, int16_t w, uint16_t ink) override;
  void drawFastVLine(int16_t x, int16_t y, int16_t h, uint16_t ink) override;
  void setBrightness8(const uint8_t value) { brightness = value; MatrixPanel_I2S_DMA::setBrightness8(value); }
  uint8_t brightness = 0;
  mini_display::FrameMirror mirror;
};

extern MiniMatrix* matrix;
extern mini_display::Metrics displayMetrics;

void setupMatrix();
uint16_t color(uint8_t red, uint8_t green, uint8_t blue);
void presentFrame();
void beginFrame(const char* kind, const char* item = "", uint16_t index = 0, uint16_t count = 0, uint32_t targetMs = 0);
