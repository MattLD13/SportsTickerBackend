uint32_t hashBody(const String& body) {
  uint32_t hash = 2166136261u;
  for (size_t index = 0; index < body.length(); ++index) {
    hash ^= static_cast<uint8_t>(body[index]);
    hash *= 16777619u;
  }
  return hash;
}

String localDeviceId() {
  const uint64_t mac = ESP.getEfuseMac();
  String high = String(static_cast<uint32_t>(mac >> 32), HEX);
  String low = String(static_cast<uint32_t>(mac), HEX);
  while (high.length() < 4) high = "0" + high;
  while (low.length() < 8) low = "0" + low;
  high.toUpperCase();
  low.toUpperCase();
  return "esp32s3-" + high + low;
}

String backendEndpoint(const String& suffix) {
  String base = BACKEND_URL;
  while (base.endsWith("/")) {
    base.remove(base.length() - 1);
  }
  return base + suffix;
}

void logSecureHttpError(const char* operation, int status, WiFiClientSecure& client) {
  if (status >= 0) {
    return;
  }
  char tlsError[96] = {};
  const int tlsStatus = client.lastError(tlsError, sizeof(tlsError));
  Serial.printf("%s failed: %s", operation, HTTPClient::errorToString(status).c_str());
  if (tlsStatus != 0) {
    Serial.printf(" TLS %d %s", tlsStatus, tlsError);
  }
  Serial.println();
}

bool registerDevice() {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }
  if (!acquireNetwork(10000)) {
    Serial.println("Register deferred: network busy");
    return false;
  }

  WiFiClientSecure client;
  client.setInsecure();
  client.setTimeout(8);
  client.setHandshakeTimeout(8);
  HTTPClient http;
  http.useHTTP10(true);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (!http.begin(client, backendEndpoint("/api/v2/devices/register"))) {
    releaseNetwork();
    showFetchError("REGISTER SETUP");
    return false;
  }

  JsonDocument request;
  request["device_id"] = localDeviceId();
  request["name"] = DEVICE_NAME;
  request["profile"]["product_family"] = "mini";
  request["profile"]["hardware"] = MINI_FIRMWARE_HARDWARE;
  request["profile"]["firmware"] = MINI_FIRMWARE_VERSION;
  request["profile"]["display"]["width"] = 64;
  request["profile"]["display"]["height"] = 32;
  request["profile"]["display"]["panel_count"] = 1;
  const char* modes[] = {"sports", "stock", "weather", "music", "flights", "airports", "clock"};
  for (uint8_t index = 0; index < sizeof(modes) / sizeof(modes[0]); ++index) {
    request["profile"]["capabilities"]["modes"][index] = modes[index];
  }
  request["profile"]["capabilities"]["asset_cache"] = false;
  request["profile"]["capabilities"]["ota"] = true;
  request["profile"]["capabilities"]["color_depth"] = 16;
  request["metadata"]["build"] = MINI_FIRMWARE_VERSION;
  request["metadata"]["mode"] = displayMode;
  for (uint8_t index = 0; index < sizeof(modes) / sizeof(modes[0]); ++index) {
    request["metadata"]["capabilities"][index] = modes[index];
  }
  String body;
  serializeJson(request, body);
  http.addHeader("Content-Type", "application/json");
  int status = http.POST(body);
  Serial.print("Register HTTP status: ");
  Serial.println(status);
  logSecureHttpError("Register", status, client);
  if (status != HTTP_CODE_OK && status != HTTP_CODE_CREATED) {
    showFetchError("REGISTER " + String(status));
    http.end();
    releaseNetwork();
    return false;
  }

  String responseBody = http.getString();
  http.end();
  releaseNetwork();
  JsonDocument response;
  if (deserializeJson(response, responseBody)) {
    showFetchError("REGISTER JSON");
    return false;
  }

  String nextTickerId = response["ticker_id"] | "";
  nextTickerId.trim();
  if (nextTickerId.length() == 0) {
    showFetchError("REGISTER ID");
    return false;
  }

  tickerId = nextTickerId;
  dataUrl = backendEndpoint("/api/v2/tickers/") + tickerId + "/data";
  heartbeatUrl = backendEndpoint("/api/v2/tickers/") + tickerId + "/heartbeat";
  const bool backendPaired = response["paired"] | false;
  pairingMode = !backendPaired;
  savePairingCode(response["pairing_code"] | "");
  if (backendPaired && blePairingStarted) {
    stopBlePairing();
  } else if (!backendPaired) {
    if (blePairingCharacteristic != nullptr && pairingCode.length() > 0) {
      blePairingCharacteristic->setValue(std::string(pairingCode.c_str()));
    }
  }
  registered = true;
  pageCount = 0;
  message = "";
  renderCurrent();
  return true;
}

// Owns V2 registration, device identity, and endpoint construction.
