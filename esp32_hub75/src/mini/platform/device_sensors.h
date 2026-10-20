#pragma once

#include <Adafruit_LIS3DH.h>
#include "display_orientation.h"

class MiniDeviceSensors {
 public:
  void begin();
  bool tick(uint32_t now);
  bool accelerometerReady() const { return accelerometerReady_; }
  float temperatureC() const { return temperatureC_; }
  uint8_t rotation() const { return orientation_.rotation(); }
  float x() const { return acceleration_[0]; }
  float y() const { return acceleration_[1]; }
  float z() const { return acceleration_[2]; }
 private:
  Adafruit_LIS3DH accelerometer_;
  mini_display::Orientation orientation_;
  float temperatureC_ = NAN;
  float acceleration_[3] = {NAN, NAN, NAN};
  uint32_t lastTemperatureAt_ = 0, lastMotionAt_ = 0;
  bool accelerometerReady_ = false;
};
