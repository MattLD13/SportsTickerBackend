#pragma once

#include <Arduino.h>
#include <esp_heap_caps.h>
#include "../protocol/response_body.h"

class ResponseStream : public Stream {
 public:
  ResponseBody body{512 * 1024, resize, heap_caps_free};
  size_t write(const uint8_t* bytes, size_t count) override { return body.append(bytes, count); }
  size_t write(uint8_t value) override { return write(&value, 1); }
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override {}

 private:
  static void* resize(void* bytes, size_t count) {
    return heap_caps_realloc(bytes, count, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  }
};
