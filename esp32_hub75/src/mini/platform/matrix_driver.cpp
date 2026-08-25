#include <Arduino.h>
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>

#include "config.h"
#include "matrix_driver.h"

MatrixPanel_I2S_DMA* matrix = nullptr;

uint16_t color(uint8_t red, uint8_t green, uint8_t blue) {
  return matrix->color565(red, green, blue);
}

void presentFrame() {
  matrix->flipDMABuffer();
}

void setupMatrix() {
  HUB75_I2S_CFG::i2s_pins pins = {
    R1_PIN, G1_PIN, B1_PIN, R2_PIN, G2_PIN, B2_PIN,
    A_PIN, B_PIN, C_PIN, D_PIN, E_PIN, LAT_PIN, OE_PIN, CLK_PIN
  };
  HUB75_I2S_CFG config(64, 32, 1, pins);
  config.double_buff = true;
  config.clkphase = true;
  config.latch_blanking = 1;
  config.i2sspeed = HUB75_I2S_CFG::HZ_8M;
  config.min_refresh_rate = 240;
  matrix = new MatrixPanel_I2S_DMA(config);
  matrix->begin();
  matrix->setBrightness8(PANEL_BRIGHTNESS);
  matrix->setTextWrap(false);
  matrix->setTextSize(1);
}
