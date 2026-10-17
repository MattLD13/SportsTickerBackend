#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include "network_gate.h"
#include "station_retry.h"

// The display task owns configuration and retry decisions. SDK callbacks record events only.
class WifiStation {
 public:
  explicit WifiStation(NetworkGate& gate) : gate_(gate) {}
  void begin(const String& ssid, const String& password);
  void configure(const String& ssid, const String& password, uint32_t now);
  void renew(uint32_t now);
  bool tick(uint32_t now, bool transportIdle);
  void describe(JsonObject output, uint32_t now);
  void pauseForTest(uint32_t now, uint32_t duration);
  void requestSetup();
  void leaveSetup(uint32_t now);
  bool setupReady() const { return setupReady_; }

 private:
  void record(WiFiEvent_t event, WiFiEventInfo_t info);
  NetworkGate& gate_;
  StationRetry retry_;
  String ssid_, password_;
  bool renewal_ = true, paused_ = false, pauseApplied_ = false;
  bool setup_ = false, setupReady_ = false, startRadio_ = false;
  uint32_t pauseUntil_ = 0, pauseDuration_ = 0, attempts_ = 0, renewals_ = 0;
  portMUX_TYPE eventMux_ = portMUX_INITIALIZER_UNLOCKED;
  uint32_t disconnects_ = 0, gotIp_ = 0, lastEventMs_ = 0;
  uint16_t lastReason_ = 0;
};
