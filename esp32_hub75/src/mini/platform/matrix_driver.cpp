#include <Arduino.h>
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>

#include "config.h"
#include "matrix_driver.h"
#include <esp_timer.h>
#include <esp_heap_caps.h>

MiniMatrix* matrix = nullptr;
mini_display::Metrics displayMetrics;
static mini_display::Pane framePane;
static uint64_t frameStartedUs = 0;

void MiniMatrix::drawPixel(int16_t x, int16_t y, uint16_t ink) {
  uint8_t r, g, b; color565to888(ink, r, g, b);
  mirror.pixel(x, y, r, g, b);
  MatrixPanel_I2S_DMA::drawPixel(x, y, ink);
}

void MiniMatrix::drawPixelRGB888(int16_t x, int16_t y, uint8_t r, uint8_t g, uint8_t b) {
  mirror.pixel(x, y, r, g, b);
  MatrixPanel_I2S_DMA::drawPixelRGB888(x, y, r, g, b);
}

void MiniMatrix::fillScreen(uint16_t ink) {
  uint8_t r, g, b; color565to888(ink, r, g, b);
  mirror.rect(0, 0, 64, 32, r, g, b);
  MatrixPanel_I2S_DMA::fillScreen(ink);
}

void MiniMatrix::fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t ink) {
  uint8_t r, g, b; color565to888(ink, r, g, b);
  mirror.rect(x, y, w, h, r, g, b);
  MatrixPanel_I2S_DMA::fillRect(x, y, w, h, ink);
}

void MiniMatrix::drawFastHLine(int16_t x, int16_t y, int16_t w, uint16_t ink) {
  uint8_t r, g, b; color565to888(ink, r, g, b);
  mirror.rect(x, y, w, 1, r, g, b);
  MatrixPanel_I2S_DMA::drawFastHLine(x, y, w, ink);
}

void MiniMatrix::drawFastVLine(int16_t x, int16_t y, int16_t h, uint16_t ink) {
  uint8_t r, g, b; color565to888(ink, r, g, b);
  mirror.rect(x, y, 1, h, r, g, b);
  MatrixPanel_I2S_DMA::drawFastVLine(x, y, h, ink);
}

void beginFrame(const char* kind, const char* item, uint16_t index, uint16_t count, uint32_t targetMs) {
  framePane = {};
  snprintf(framePane.kind, sizeof(framePane.kind), "%s", kind);
  snprintf(framePane.item, sizeof(framePane.item), "%s", item);
  framePane.index = index; framePane.count = count; framePane.targetMs = targetMs;
  frameStartedUs = esp_timer_get_time();
}

uint16_t color(uint8_t red, uint8_t green, uint8_t blue) {
  return matrix->color565(red, green, blue);
}

bool MiniMatrix::restoreBaseFrame() {
  if (!baseFrameReady || !baseFrame) return false;
  for (int y = 0; y < 32; ++y) for (int x = 0; x < 64; ++x) {
    const size_t offset = (y * 64 + x) * 3;
    drawPixelRGB888(x, y, baseFrame[offset], baseFrame[offset + 1], baseFrame[offset + 2]);
  }
  return true;
}

void MiniMatrix::retainBaseFrame() {
  if (!baseFrame || !mirror.drawing()) return;
  memcpy(baseFrame, mirror.drawing(), mini_display::FRAME_BYTES);
  baseFrameReady = true;
}

void presentFrame() {
  matrix->flipDMABuffer();
  matrix->mirror.present();
  const uint64_t now = esp_timer_get_time();
  displayMetrics.present(framePane, now, now - frameStartedUs);
}

void setupMatrix() {
  HUB75_I2S_CFG::i2s_pins pins = {
    R1_PIN, G1_PIN, B1_PIN, R2_PIN, G2_PIN, B2_PIN,
    A_PIN, B_PIN, C_PIN, D_PIN, E_PIN, LAT_PIN, OE_PIN, CLK_PIN
  };
  HUB75_I2S_CFG config(64, 32, 1, pins);
  config.double_buff = true;
  config.clkphase = false;
  config.latch_blanking = 1;
  config.i2sspeed = HUB75_I2S_CFG::HZ_8M;
  // Retain low-bit color precision at the configured 8 MHz clock.
  config.min_refresh_rate = 200;
  matrix = new MiniMatrix(config);
  auto* pixels = static_cast<uint8_t*>(heap_caps_calloc(3, mini_display::FRAME_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  matrix->mirror.attach(pixels);
  matrix->baseFrame = pixels ? pixels + 2 * mini_display::FRAME_BYTES : nullptr;
  Serial.printf("Display capture PSRAM bytes=%u available=%d\n", 3 * mini_display::FRAME_BYTES, pixels != nullptr);
  matrix->begin();
  matrix->setBrightness8(PANEL_BRIGHTNESS);
  matrix->setTextWrap(false);
  matrix->setTextSize(1);
}
