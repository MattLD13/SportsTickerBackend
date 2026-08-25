bool scanForSavedWifi() {
  Serial.print("Scanning for saved Wi-Fi: ");
  Serial.println(wifiSsid);
  const int networkCount = WiFi.scanNetworks(false, true);
  savedWifiVisible = false;
  if (networkCount < 0) {
    Serial.print("Wi-Fi scan failed: ");
    Serial.println(networkCount);
    WiFi.scanDelete();
    return false;
  }
  for (int index = 0; index < networkCount; ++index) {
    if (WiFi.SSID(index) == wifiSsid) {
      savedWifiVisible = true;
      break;
    }
  }
  Serial.print("Saved Wi-Fi visible: ");
  Serial.println(savedWifiVisible ? "yes" : "no");
  WiFi.scanDelete();
  return savedWifiVisible;
}

void loadWifiCredentials() {
  preferences.begin("ticker", false);
  wifiSsid = preferences.getString("wifi_ssid", "");
  wifiPassword = preferences.getString("wifi_pass", "");
  pairingCode = preferences.getString("pairing_code", "");
  wifiSsid.trim();
  if (wifiSsid.length() == 0 || wifiSsid == "Rem 6") {
    wifiSsid = WIFI_SSID;
    wifiPassword = WIFI_PASSWORD;
    saveWifiCredentials(wifiSsid, wifiPassword);
    Serial.println("Using default Wi-Fi credentials");
  }
}

void saveWifiCredentials(const String& ssid, const String& password) {
  preferences.putString("wifi_ssid", ssid);
  preferences.putString("wifi_pass", password);
}

void savePairingCode(const String& code) {
  pairingCode = code;
  preferences.putString("pairing_code", code);
}

bool decodeBase64(const String& input, uint8_t*& output, size_t& outputLength) {
  output = nullptr;
  outputLength = 0;
  const size_t capacity = (input.length() * 3) / 4 + 4;
  output = static_cast<uint8_t*>(malloc(capacity));
  if (output == nullptr) return false;
  size_t decodedLength = 0;
  const int result = mbedtls_base64_decode(
    output,
    capacity,
    &decodedLength,
    reinterpret_cast<const unsigned char*>(input.c_str()),
    input.length()
  );
  if (result != 0) {
    free(output);
    output = nullptr;
    return false;
  }
  outputLength = decodedLength;
  return true;
}

bool challengeMatches(const String& value) {
  if (value.length() != BLE_CHALLENGE_LENGTH * 2) return false;
  for (uint8_t index = 0; index < BLE_CHALLENGE_LENGTH; ++index) {
    String byteValue = value.substring(index * 2, index * 2 + 2);
    char* end = nullptr;
    const unsigned long decoded = strtoul(byteValue.c_str(), &end, 16);
    if (end == byteValue.c_str() || *end != '\0' || decoded != bleChallenge[index]) {
      return false;
    }
  }
  return true;
}

bool deriveHkdfSha256(const uint8_t* salt, size_t saltLength, const uint8_t* input, size_t inputLength, const uint8_t* info, size_t infoLength, uint8_t* output, size_t outputLength) {
  if (outputLength > 32) return false;
  const mbedtls_md_info_t* sha256 = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (sha256 == nullptr) return false;

  uint8_t pseudorandomKey[32] = {};
  mbedtls_md_context_t extract;
  mbedtls_md_init(&extract);
  if (mbedtls_md_setup(&extract, sha256, 1) != 0 ||
      mbedtls_md_hmac_starts(&extract, salt, saltLength) != 0 ||
      mbedtls_md_hmac_update(&extract, input, inputLength) != 0 ||
      mbedtls_md_hmac_finish(&extract, pseudorandomKey) != 0) {
    mbedtls_md_free(&extract);
    return false;
  }
  mbedtls_md_free(&extract);

  uint8_t block[32] = {};
  mbedtls_md_context_t expand;
  mbedtls_md_init(&expand);
  if (mbedtls_md_setup(&expand, sha256, 1) != 0 ||
      mbedtls_md_hmac_starts(&expand, pseudorandomKey, sizeof(pseudorandomKey)) != 0 ||
      mbedtls_md_hmac_update(&expand, info, infoLength) != 0) {
    mbedtls_md_free(&expand);
    return false;
  }
  const uint8_t counter = 1;
  const bool valid = mbedtls_md_hmac_update(&expand, &counter, 1) == 0 &&
                     mbedtls_md_hmac_finish(&expand, block) == 0;
  mbedtls_md_free(&expand);
  if (!valid) return false;
  memcpy(output, block, outputLength);
  return true;
}

bool decryptWifiCredentials(const String& encodedEnvelope, String& ssid, String& password) {
  uint8_t* envelopeBytes = nullptr;
  size_t envelopeLength = 0;
  if (!decodeBase64(encodedEnvelope, envelopeBytes, envelopeLength)) return false;

  JsonDocument envelope;
  const DeserializationError envelopeError = deserializeJson(envelope, envelopeBytes, envelopeLength);
  free(envelopeBytes);
  if (envelopeError) return false;

  const int version = envelope["v"] | 0;
  const String challengeHex = envelope["challenge"] | "";
  const String nonceEncoded = envelope["nonce"] | "";
  const String ciphertextEncoded = envelope["ciphertext"] | "";
  if (version != 1 || !challengeMatches(challengeHex) || nonceEncoded.length() == 0 || ciphertextEncoded.length() == 0) {
    return false;
  }

  uint8_t* nonce = nullptr;
  uint8_t* ciphertext = nullptr;
  size_t nonceLength = 0;
  size_t ciphertextLength = 0;
  if (!decodeBase64(nonceEncoded, nonce, nonceLength) ||
      !decodeBase64(ciphertextEncoded, ciphertext, ciphertextLength)) {
    if (nonce != nullptr) free(nonce);
    if (ciphertext != nullptr) free(ciphertext);
    return false;
  }
  if (nonceLength != 12 || ciphertextLength <= 16) {
    free(nonce);
    free(ciphertext);
    return false;
  }

  uint8_t key[32] = {};
  if (!deriveHkdfSha256(
    bleChallenge,
    BLE_CHALLENGE_LENGTH,
    reinterpret_cast<const unsigned char*>(setupCode.c_str()),
    setupCode.length(),
    reinterpret_cast<const unsigned char*>(BLE_PROTOCOL_INFO),
    strlen(BLE_PROTOCOL_INFO),
    key,
    sizeof(key)
  )) {
    free(nonce);
    free(ciphertext);
    return false;
  }

  const size_t plaintextLength = ciphertextLength - 16;
  uint8_t* plaintext = static_cast<uint8_t*>(malloc(plaintextLength + 1));
  if (plaintext == nullptr) {
    free(nonce);
    free(ciphertext);
    return false;
  }
  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  const int keyResult = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key, 256);
  const int decryptResult = keyResult == 0
    ? mbedtls_gcm_auth_decrypt(
        &gcm,
        plaintextLength,
        nonce,
        nonceLength,
        bleChallenge,
        BLE_CHALLENGE_LENGTH,
        ciphertext + plaintextLength,
        16,
        ciphertext,
        plaintext
      )
    : keyResult;
  mbedtls_gcm_free(&gcm);
  free(nonce);
  free(ciphertext);
  if (decryptResult != 0) {
    free(plaintext);
    return false;
  }

  plaintext[plaintextLength] = '\0';
  JsonDocument credentials;
  const DeserializationError credentialsError = deserializeJson(credentials, plaintext, plaintextLength);
  free(plaintext);
  if (credentialsError) return false;
  ssid = credentials["ssid"] | "";
  password = credentials["password"] | "";
  ssid.trim();
  return ssid.length() > 0 && password.length() > 0 && ssid.length() <= 32 && password.length() <= 64;
}

void setBleResult(const char* value) {
  if (bleResultCharacteristic != nullptr) {
    bleResultCharacteristic->setValue(std::string(value));
  }
}

void resetBleChunks() {
  bleCredentialChunkTotal = 0;
  bleCredentialChunkCount = 0;
  for (uint8_t index = 0; index < BLE_MAX_CREDENTIAL_CHUNKS; ++index) {
    bleCredentialChunks[index] = "";
    bleCredentialChunkReceived[index] = false;
  }
}

void processBleCredentials() {
  String encodedEnvelope;
  for (uint8_t index = 0; index < bleCredentialChunkTotal; ++index) {
    encodedEnvelope += bleCredentialChunks[index];
  }
  String nextSsid;
  String nextPassword;
  if (!decryptWifiCredentials(encodedEnvelope, nextSsid, nextPassword)) {
    setBleResult("ERROR");
    resetBleChunks();
    return;
  }
  portENTER_CRITICAL(&bleProvisioningMux);
  nextSsid.toCharArray(pendingWifiSsid, sizeof(pendingWifiSsid));
  nextPassword.toCharArray(pendingWifiPassword, sizeof(pendingWifiPassword));
  pendingWifiReady = true;
  portEXIT_CRITICAL(&bleProvisioningMux);
  setBleResult("OK");
  Serial.println("Wi-Fi credentials queued from BLE");
  resetBleChunks();
}

class PairingServerCallbacks : public NimBLEServerCallbacks {
  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int) override {
    if (blePairingStarted) NimBLEDevice::startAdvertising();
  }
};

class PairingCredentialsCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
    const std::string value = characteristic->getValue();
    const String packet(value.c_str());
    const int slash = packet.indexOf('/');
    const int colon = packet.indexOf(':');
    if (slash <= 0 || colon <= slash + 1) {
      setBleResult("ERROR");
      return;
    }
    const int index = packet.substring(0, slash).toInt();
    const int total = packet.substring(slash + 1, colon).toInt();
    if (index < 0 || total <= 0 || total > BLE_MAX_CREDENTIAL_CHUNKS || index >= total) {
      setBleResult("ERROR");
      return;
    }
    if (index == 0 && bleCredentialChunkCount > 0) resetBleChunks();
    if (bleCredentialChunkTotal == 0) {
      bleCredentialChunkTotal = static_cast<uint8_t>(total);
    }
    if (bleCredentialChunkTotal != total) {
      setBleResult("ERROR");
      resetBleChunks();
      return;
    }
    if (!bleCredentialChunkReceived[index]) {
      bleCredentialChunks[index] = packet.substring(colon + 1);
      bleCredentialChunkReceived[index] = true;
      ++bleCredentialChunkCount;
    }
    if (bleCredentialChunkTotal > 0 && bleCredentialChunkCount == bleCredentialChunkTotal) {
      processBleCredentials();
    }
  }
};

void startBlePairing() {
  if (blePairingStarted) return;
  setupCode = String(100000 + (esp_random() % 900000));
  for (uint8_t index = 0; index < BLE_CHALLENGE_LENGTH; ++index) {
    bleChallenge[index] = static_cast<uint8_t>(esp_random() & 0xFF);
  }
  resetBleChunks();
  Serial.printf("BLE start, free heap: %u\n", ESP.getFreeHeap());
  NimBLEDevice::init("MiniTicker Setup");
  NimBLEDevice::setMTU(185);
  NimBLEServer* server = NimBLEDevice::createServer();
  if (server == nullptr) {
    Serial.println("BLE error: createServer failed");
    NimBLEDevice::deinit(true);
    return;
  }
  server->setCallbacks(new PairingServerCallbacks());
  NimBLEService* service = server->createService(BLE_SERVICE_UUID);
  if (service == nullptr) {
    Serial.println("BLE error: createService failed");
    NimBLEDevice::deinit(true);
    return;
  }
  bleChallengeCharacteristic = service->createCharacteristic(BLE_CHALLENGE_UUID, NIMBLE_PROPERTY::READ);
  bleCredentialsCharacteristic = service->createCharacteristic(BLE_CREDENTIALS_UUID, NIMBLE_PROPERTY::WRITE);
  bleResultCharacteristic = service->createCharacteristic(BLE_RESULT_UUID, NIMBLE_PROPERTY::READ);
  blePairingCharacteristic = service->createCharacteristic(BLE_PAIRING_UUID, NIMBLE_PROPERTY::READ);
  if (bleChallengeCharacteristic == nullptr || bleCredentialsCharacteristic == nullptr ||
      bleResultCharacteristic == nullptr || blePairingCharacteristic == nullptr) {
    Serial.println("BLE error: characteristic creation failed");
    NimBLEDevice::deinit(true);
    return;
  }
  bleChallengeCharacteristic->setValue(bleChallenge, BLE_CHALLENGE_LENGTH);
  bleResultCharacteristic->setValue(std::string("WAITING"));
  blePairingCharacteristic->setValue(std::string(pairingCode.length() > 0 ? pairingCode.c_str() : "NONE"));
  bleCredentialsCharacteristic->setCallbacks(new PairingCredentialsCallbacks());
  server->start();
  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  if (advertising == nullptr) {
    Serial.println("BLE error: advertising unavailable");
    NimBLEDevice::deinit(true);
    return;
  }
  advertising->addServiceUUID(BLE_SERVICE_UUID);
  NimBLEDevice::startAdvertising();
  blePairingStarted = true;
  Serial.print("BLE pairing PIN: ");
  Serial.println(setupCode);
}

void stopBlePairing() {
  if (!blePairingStarted) return;
  NimBLEDevice::stopAdvertising();
  NimBLEDevice::deinit(true);
  blePairingStarted = false;
  bleChallengeCharacteristic = nullptr;
  bleCredentialsCharacteristic = nullptr;
  bleResultCharacteristic = nullptr;
  blePairingCharacteristic = nullptr;
}

void startPairingMode() {
  if (wifiPairingMode) return;
  if (blePairingStarted) stopBlePairing();
  wifiPairingMode = true;
  pairingMode = true;
  pageCount = 0;
  message = "";
  WiFi.disconnect(false, false);
  WiFi.mode(WIFI_OFF);
  delay(100);
  startBlePairing();
  renderCurrent();
  Serial.println("Wi-Fi unavailable for 30 seconds. Entering pairing mode.");
}

void showFetchError(const String& value) {
  if (pairingMode) {
    message = "";
    renderCurrent();
    return;
  }
  String displayValue = value;
  if (displayValue.startsWith("REGISTER ")) {
    displayValue = "REG " + displayValue.substring(9);
  }
  if (displayValue.startsWith("REGISTER")) {
    displayValue = "REG" + displayValue.substring(8);
  }
  if (pageCount == 0) {
    message = displayValue;
    return;
  }
  // Keep the last valid sports page visible while the backend is unavailable.
  message = "";
  renderCurrent();
}
// Owns saved Wi-Fi state, reconnect policy, BLE provisioning, and pairing transition.
