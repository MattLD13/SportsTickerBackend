#include "device_payload.h"
#include "payload_reader.h"
#include "fields_generated.h"
#include <utility>
#ifdef ARDUINO_ARCH_ESP32
#include <esp_heap_caps.h>
#endif

namespace {
class PayloadAllocator final : public ArduinoJson::Allocator {
 public:
  void* allocate(size_t size) override { return reallocate(nullptr, size); }
  void deallocate(void* pointer) override {
#ifdef ARDUINO_ARCH_ESP32
    heap_caps_free(pointer);
#else
    std::free(pointer);
#endif
  }
  void* reallocate(void* pointer, size_t size) override {
#ifdef ARDUINO_ARCH_ESP32
    return heap_caps_realloc(pointer, size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
#else
    return std::realloc(pointer, size);
#endif
  }
};
PayloadAllocator payloadAllocator;
}

DevicePayload::DevicePayload() : filter_(&payloadAllocator), document_(&payloadAllocator) {}

void DevicePayload::initializeFilter() {
  const auto error = deserializeJson(filter_, MINI_PAYLOAD_FILTER);
  filterReady_ = !error && !filter_.overflowed();
}

bool DevicePayload::accept(const ResponseBody& body) {
  if (!filterReady_) initializeFilter();
  if (!filterReady_) { error_ = "Filter allocation failed"; return false; }
  JsonDocument candidate(&payloadAllocator);
  PayloadReader reader(body.data(), body.size());
  const auto error = deserializeJson(candidate, reader, DeserializationOption::Filter(filter_));
  offset_ = reader.position();
  error_ = error ? error.c_str() : "";
  if (error) return false;
  if (candidate["api_version"] != "v2" || !candidate["settings"].is<JsonObject>() ||
      !candidate["content"].is<JsonObject>() || !candidate["meta"]["pairing"]["paired"].is<bool>()) {
    error_ = "Invalid V2 display contract";
    return false;
  }
  document_ = std::move(candidate);
  return true;
}
