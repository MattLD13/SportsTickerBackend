#include "device_credentials.h"
#include <Preferences.h>
#include <esp_system.h>

static bool validToken(const String& token) {
  if (token.length() != 64) return false;
  for (size_t index = 0; index < token.length(); ++index)
    if (!((token[index] >= '0' && token[index] <= '9') || (token[index] >= 'a' && token[index] <= 'f'))) return false;
  return true;
}

bool DeviceCredentials::load() {
  Preferences storage;
  if (!storage.begin("device_auth", false)) return false;
  const bool exists = storage.isKey("token");
  String saved = storage.getString("token", "");
  storage.end();
  if (exists) {
    if (!validToken(saved)) return false;
    token_ = saved;
    return true;
  }
  uint8_t bytes[32];
  esp_fill_random(bytes, sizeof(bytes));
  char encoded[65] = {};
  for (unsigned index = 0; index < sizeof(bytes); ++index) sprintf(encoded + index * 2, "%02x", bytes[index]);
  return replace(String(encoded));
}

bool DeviceCredentials::replace(const String& token) {
  if (!validToken(token)) return false;
  Preferences storage;
  if (!storage.begin("device_auth", false)) return false;
  const bool stored = storage.putString("token", token) > 0;
  storage.end();
  if (stored) token_ = token;
  return stored;
}
