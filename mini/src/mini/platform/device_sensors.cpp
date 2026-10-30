#include <Arduino.h>
#include <Wire.h>
#include "device_sensors.h"

void MiniDeviceSensors::begin() {
  Wire.begin();
  Wire.setTimeOut(10);
  accelerometerReady_ = accelerometer_.begin(0x19);
  if (accelerometerReady_) {
    accelerometer_.setRange(LIS3DH_RANGE_2_G);
    accelerometer_.setDataRate(LIS3DH_DATARATE_25_HZ);
  }
  lastTemperatureAt_ = millis() - 10000;
}

bool MiniDeviceSensors::tick(uint32_t now) {
  if (uint32_t(now - lastTemperatureAt_) >= 10000) {
    lastTemperatureAt_ = now;
    const float value = temperatureRead();
    temperatureC_ = std::isfinite(value) && value >= -40 && value <= 125 ? value : NAN;
  }
  if (!accelerometerReady_ || uint32_t(now - lastMotionAt_) < 100) return false;
  lastMotionAt_ = now;
  if (!accelerometer_.haveNewData()) {
    orientation_.unavailable();
    return false;
  }
  accelerometer_.read();
  acceleration_[0] = accelerometer_.x_g;
  acceleration_[1] = accelerometer_.y_g;
  acceleration_[2] = accelerometer_.z_g;
  return orientation_.observe(x(), y(), z(), now);
}
