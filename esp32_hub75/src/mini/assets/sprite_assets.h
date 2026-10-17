#pragma once
#include <Arduino.h>
class NetworkWorker;
class NetworkGate;
class Adafruit_GFX;

class SpriteAssets {
 public:
  struct Metrics {
    uint32_t flashHits = 0, downloads = 0, reusedDownloads = 0, invalidFiles = 0, evictions = 0;
    uint32_t heapBeforeTls = 0, heapDuringTls = 0, heapAfterTls = 0, largestDuringTls = 0;
  };
  SpriteAssets(NetworkWorker& transport, NetworkGate& gate, const char* backend);
  SpriteAssets(const SpriteAssets&) = delete;
  SpriteAssets& operator=(const SpriteAssets&) = delete;
  bool begin();
  bool ready() const;
  uint8_t slotCount() const;
  uint16_t residentCount();
  bool available(const String& key);
  bool pinCached(const String& key);
  void pinWindow(const String* keys, uint8_t count);
  bool loadCached(const String& key, uint8_t* bytes);
  bool load(const String& key, uint8_t* bytes);
  bool install(const String& key, const uint8_t* bytes);
  bool draw(const String& key, int16_t x, int16_t y, Adafruit_GFX& surface);
  const Metrics& metrics() const { return metrics_; }

 private:
  struct State;
  State* state_ = nullptr;
  NetworkWorker& transport_;
  NetworkGate& gate_;
  const char* backend_;
  Metrics metrics_;
};
