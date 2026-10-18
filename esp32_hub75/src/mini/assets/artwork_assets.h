#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <atomic>
#include "mini_artwork.h"

class NetworkWorker;
class Adafruit_GFX;

class ArtworkAssets {
 public:
  ArtworkAssets(NetworkWorker& transport, const char* backend) : transport_(transport), backend_(backend) {}
  bool begin();
  bool request(JsonObjectConst music);
  bool pending();
  void loadPending();
  bool draw(JsonObjectConst asset, Adafruit_GFX& surface);
  uint32_t downloads() const { return downloads_.load(); }
  struct Metrics { size_t resident = 0, planned = 0; uint32_t hits = 0; };
  Metrics metrics();
 private:
  struct State;
  State* state_ = nullptr;
  NetworkWorker& transport_;
  const char* backend_;
  std::atomic<uint32_t> downloads_{0};
};
