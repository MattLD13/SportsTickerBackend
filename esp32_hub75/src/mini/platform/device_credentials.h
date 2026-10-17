#pragma once
#include <Arduino.h>

class DeviceCredentials {
 public:
  bool load();
  bool replace(const String& token);
  bool ready() const { return token_.length() == 64; }
  const String& token() const { return token_; }
 private:
  String token_;
};
