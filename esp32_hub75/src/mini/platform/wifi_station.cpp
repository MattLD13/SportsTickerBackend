#include "wifi_station.h"

void WifiStation::begin(const String& ssid, const String& password) {
  WiFi.onEvent([this](WiFiEvent_t event, WiFiEventInfo_t info) { record(event, info); });
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFi.setSleep(false);
  configure(ssid, password, millis());
}

void WifiStation::configure(const String& ssid, const String& password, uint32_t now) {
  ssid_ = ssid;
  password_ = password;
  leaveSetup(now);
}

void WifiStation::renew(uint32_t now) {
  if (setup_) return;
  renewal_ = true;
  retry_.configure(now);
}

void WifiStation::requestSetup() {
  if (setup_) return;
  paused_ = false;
  setup_ = true;
  setupReady_ = false;
}

void WifiStation::leaveSetup(uint32_t now) {
  startRadio_ = setupReady_;
  setup_ = setupReady_ = false;
  renew(now);
}

void WifiStation::pauseForTest(uint32_t now, uint32_t duration) {
  paused_ = true;
  pauseApplied_ = false;
  pauseDuration_ = duration;
  pauseUntil_ = now;
}

bool WifiStation::tick(uint32_t now, bool transportIdle) {
  if (setup_) {
    if (!setupReady_ && transportIdle) {
      NetworkLease lease(gate_, 0);
      if (lease) { WiFi.mode(WIFI_OFF); setupReady_ = true; }
    }
    return false;
  }
  if (paused_ && pauseApplied_ && static_cast<int32_t>(now - pauseUntil_) >= 0) {
    paused_ = false;
    renewal_ = true;
    retry_.configure(now);
  }
  if (paused_) {
    if (!pauseApplied_ && transportIdle) {
      NetworkLease lease(gate_, 0);
      if (lease) { WiFi.disconnect(false, false); pauseApplied_ = true; pauseUntil_ = now + pauseDuration_; }
    }
    return pauseApplied_ ? false : WiFi.status() == WL_CONNECTED && !renewal_;
  }
  const bool connected = WiFi.status() == WL_CONNECTED;
  retry_.observe(connected && !renewal_, now);
  if ((renewal_ || retry_.due(now)) && transportIdle) {
    NetworkLease lease(gate_, 0);
    if (lease) {
      if (startRadio_) { WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(false); startRadio_ = false; }
      if (renewal_ && attempts_) ++renewals_;
      WiFi.setSleep(false);
      WiFi.disconnect(false, false);
      WiFi.begin(ssid_.c_str(), password_.c_str());
      renewal_ = false;
      retry_.started(now);
      ++attempts_;
      Serial.printf("Wi-Fi association attempt=%lu\n", static_cast<unsigned long>(attempts_));
    }
    return false;
  }
  return connected && !renewal_;
}

void WifiStation::record(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event != ARDUINO_EVENT_WIFI_STA_DISCONNECTED && event != ARDUINO_EVENT_WIFI_STA_GOT_IP) return;
  portENTER_CRITICAL(&eventMux_);
  lastEventMs_ = millis();
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    ++disconnects_;
    lastReason_ = info.wifi_sta_disconnected.reason;
  } else ++gotIp_;
  portEXIT_CRITICAL(&eventMux_);
}

void WifiStation::describe(JsonObject output, uint32_t now) {
  uint32_t disconnects, gotIp, eventMs;
  uint16_t reason;
  portENTER_CRITICAL(&eventMux_);
  disconnects = disconnects_; gotIp = gotIp_; eventMs = lastEventMs_; reason = lastReason_;
  portEXIT_CRITICAL(&eventMux_);
  output["association_attempts"] = attempts_;
  output["renewals"] = renewals_;
  output["disconnect_events"] = disconnects;
  output["got_ip_events"] = gotIp;
  output["last_disconnect_reason"] = reason;
  output["last_wifi_event_ms"] = eventMs;
  output["association_active"] = retry_.state() == StationRetry::State::Associating;
  output["test_pause_ms"] = paused_ && pauseApplied_ && static_cast<int32_t>(pauseUntil_ - now) > 0 ? pauseUntil_ - now : 0;
  output["test_pause_pending"] = paused_ && !pauseApplied_;
}
