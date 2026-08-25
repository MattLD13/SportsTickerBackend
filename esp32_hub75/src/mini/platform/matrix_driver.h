#pragma once

#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>

extern MatrixPanel_I2S_DMA* matrix;

void setupMatrix();
uint16_t color(uint8_t red, uint8_t green, uint8_t blue);
void presentFrame();
