#pragma once

#include <ArduinoJson.h>
#include "response_body.h"

// Own the retained document and commit complete V2 responses atomically.
class DevicePayload {
 public:
  DevicePayload();
  bool accept(const ResponseBody& body);
  JsonObjectConst document() const { return document_.as<JsonObjectConst>(); }
  const char* error() const { return error_; }
  size_t offset() const { return offset_; }

 private:
  JsonDocument filter_, document_;
  const char* error_ = "";
  size_t offset_ = 0;
};
