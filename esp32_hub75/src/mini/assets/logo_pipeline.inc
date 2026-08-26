uint32_t logoUrlHash(const String& url) {
  return hashBody(url);
}

RuntimeLogo* freeRuntimeLogoSlot(uint32_t urlHash) {
  if (runtimeLogos == nullptr || runtimeLogoSlotCount == 0) {
    return nullptr;
  }
  for (uint8_t index = 0; index < runtimeLogoSlotCount; ++index) {
    if (!runtimeLogos[index].valid) {
      return &runtimeLogos[index];
    }
  }
  const uint8_t preferred = urlHash % runtimeLogoSlotCount;
  if (!runtimeLogos[preferred].pinned) {
    return &runtimeLogos[preferred];
  }
  for (uint8_t offset = 1; offset < runtimeLogoSlotCount; ++offset) {
    const uint8_t index = (preferred + offset) % runtimeLogoSlotCount;
    if (!runtimeLogos[index].pinned) {
      return &runtimeLogos[index];
    }
  }
  return nullptr;
}

bool readPersistedLogo(uint16_t slot, PersistedLogo& record) {
  if (!LittleFS.exists(LOGO_CACHE_FILE)) {
    return false;
  }
  File file = LittleFS.open(LOGO_CACHE_FILE, "r");
  if (!file) {
    return false;
  }
  const size_t offset = static_cast<size_t>(slot) * sizeof(PersistedLogo);
  if (file.size() < offset + sizeof(PersistedLogo)) {
    file.close();
    return false;
  }
  if (!file.seek(offset)) {
    file.close();
    return false;
  }
  const size_t readCount = file.readBytes(reinterpret_cast<char*>(&record), sizeof(record));
  file.close();
  return readCount == sizeof(record);
}

int findPersistedLogoSlot(uint32_t urlHash, const String& url, bool allowEmpty) {
  const uint16_t start = urlHash % FLASH_LOGO_CACHE_SLOTS;
  PersistedLogo record = {};
  for (uint16_t attempt = 0; attempt < FLASH_LOGO_PROBE_LIMIT; ++attempt) {
    const uint16_t slot = (start + attempt) % FLASH_LOGO_CACHE_SLOTS;
    if (!readPersistedLogo(slot, record)) {
      return allowEmpty ? slot : -1;
    }
    if (record.urlHash == 0) {
      return allowEmpty ? slot : -1;
    }
    if (record.urlHash == urlHash && (url.length() >= sizeof(record.url) || strcmp(record.url, url.c_str()) == 0)) {
      return slot;
    }
  }
  return allowEmpty ? start : -1;
}

void persistLogo(const String& url, RuntimeLogo* logo) {
  if (!logoCacheReady || logo == nullptr || !logo->valid) {
    return;
  }
  if (logoStorageMutex != nullptr) {
    xSemaphoreTake(logoStorageMutex, portMAX_DELAY);
  }
  PersistedLogo record = {};
  record.urlHash = logoUrlHash(url);
  url.substring(0, sizeof(record.url) - 1).toCharArray(record.url, sizeof(record.url));
  memcpy(record.pixels, logo->pixels, sizeof(record.pixels));
  memcpy(record.mask, logo->mask, sizeof(record.mask));
  int slot = findPersistedLogoSlot(record.urlHash, url, true);
  if (slot < 0) {
    slot = record.urlHash % FLASH_LOGO_CACHE_SLOTS;
  }
  File file = LittleFS.exists(LOGO_CACHE_FILE)
    ? LittleFS.open(LOGO_CACHE_FILE, "r+")
    : LittleFS.open(LOGO_CACHE_FILE, "w+");
  if (file) {
    file.seek(static_cast<size_t>(slot) * sizeof(PersistedLogo));
    file.write(reinterpret_cast<const uint8_t*>(&record), sizeof(record));
    file.close();
  }
  if (logoStorageMutex != nullptr) {
    xSemaphoreGive(logoStorageMutex);
  }
}

RuntimeLogo* loadPersistedLogo(const String& url) {
  if (!logoCacheReady || url.length() == 0) {
    return nullptr;
  }
  const uint32_t wantedHash = logoUrlHash(url);
  PersistedLogo record = {};
  bool recordReady = false;
  if (logoStorageMutex != nullptr) {
    xSemaphoreTake(logoStorageMutex, portMAX_DELAY);
  }
  const int slot = findPersistedLogoSlot(wantedHash, url, false);
  if (slot >= 0) {
    recordReady = readPersistedLogo(static_cast<uint16_t>(slot), record);
  }
  if (logoStorageMutex != nullptr) {
    xSemaphoreGive(logoStorageMutex);
  }
  if (!recordReady) {
    return nullptr;
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  }
  RuntimeLogo* result = freeRuntimeLogoSlot(wantedHash);
  if (result == nullptr) {
    if (logoCacheMutex != nullptr) {
      xSemaphoreGive(logoCacheMutex);
    }
    return nullptr;
  }
  result->url = url;
  memcpy(result->pixels, record.pixels, sizeof(result->pixels));
  memcpy(result->mask, record.mask, sizeof(result->mask));
  result->valid = true;
  result->pinned = false;
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
  }
  return result;
}

void releaseLogoDownloadBuffer() {
  if (logoDownloadBuffer != nullptr) {
    heap_caps_free(logoDownloadBuffer);
    logoDownloadBuffer = nullptr;
    logoDownloadCapacity = 0;
  }
}

bool knownLogoFailure(const String& url) {
  for (uint8_t index = 0; index < logoFailureCount; ++index) {
    if (logoFailureUrls[index] == url) {
      return true;
    }
  }
  return false;
}

bool logoRetrySuppressed(const String& url) {
  for (uint8_t index = 0; index < logoRetryCount; ++index) {
    if (logoRetryUrls[index] == url) {
      return static_cast<int32_t>(millis() - logoRetryAfter[index]) < 0;
    }
  }
  return false;
}

void rememberLogoRetry(const String& url) {
  if (url.length() == 0 || knownLogoFailure(url)) {
    return;
  }
  for (uint8_t index = 0; index < logoRetryCount; ++index) {
    if (logoRetryUrls[index] == url) {
      logoRetryAfter[index] = millis() + LOGO_RETRY_BACKOFF_MS;
      return;
    }
  }
  if (logoRetryCount < LOGO_FAILURE_SLOTS) {
    logoRetryUrls[logoRetryCount] = url;
    logoRetryAfter[logoRetryCount] = millis() + LOGO_RETRY_BACKOFF_MS;
    ++logoRetryCount;
    return;
  }
  logoRetryUrls[logoRetryIndex] = url;
  logoRetryAfter[logoRetryIndex] = millis() + LOGO_RETRY_BACKOFF_MS;
  logoRetryIndex = (logoRetryIndex + 1) % LOGO_FAILURE_SLOTS;
}

void clearLogoRetry(const String& url) {
  for (uint8_t index = 0; index < logoRetryCount; ++index) {
    if (logoRetryUrls[index] == url) {
      logoRetryUrls[index] = "";
      logoRetryAfter[index] = 0;
      return;
    }
  }
}

void rememberLogoFailure(const String& url) {
  if (url.length() == 0 || knownLogoFailure(url)) {
    return;
  }
  if (logoFailureCount < LOGO_FAILURE_SLOTS) {
    logoFailureUrls[logoFailureCount++] = url;
    return;
  }
  logoFailureUrls[logoFailureIndex] = url;
  logoFailureIndex = (logoFailureIndex + 1) % LOGO_FAILURE_SLOTS;
}

bool downloadLogo(const String& url, size_t& length) {
  length = 0;
  lastLogoFailurePermanent = false;
  if (WiFi.status() != WL_CONNECTED || url.length() == 0) {
    return false;
  }
  if (!acquireNetwork(12000)) {
    Serial.printf("Logo deferred: network busy id=%08lX\n", static_cast<unsigned long>(logoUrlHash(url)));
    return false;
  }
  WiFiClientSecure client;
  client.setInsecure();
  client.setTimeout(10);
  client.setHandshakeTimeout(10);
  HTTPClient http;
  http.useHTTP10(true);
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(8000);
  http.setFollowRedirects(HTTPC_FORCE_FOLLOW_REDIRECTS);
  http.setRedirectLimit(3);
  if (!http.begin(client, url)) {
    Serial.printf("Logo begin failed id=%08lX\n", static_cast<unsigned long>(logoUrlHash(url)));
    releaseNetwork();
    return false;
  }
  http.setUserAgent("Mozilla/5.0 MiniTicker/1.0");
  http.addHeader("Accept", "image/png,image/jpeg,image/*,*/*;q=0.8");
  const char* responseHeaders[] = {"Content-Type", "Content-Length"};
  http.collectHeaders(responseHeaders, 2);
  const int status = http.GET();
  const int expected = http.getSize();
  const String contentType = http.header("Content-Type");
  Serial.printf("Logo HTTP %d size=%d mime=%s id=%08lX\n", status, expected,
                contentType.c_str(), static_cast<unsigned long>(logoUrlHash(url)));
  logSecureHttpError("Logo", status, client);
  if (status != HTTP_CODE_OK) {
    lastLogoFailurePermanent = status == HTTP_CODE_NOT_FOUND || status == HTTP_CODE_BAD_REQUEST;
    http.end();
    releaseNetwork();
    return false;
  }
  if (expected > static_cast<int>(LOGO_DOWNLOAD_LIMIT)) {
    lastLogoFailurePermanent = true;
    Serial.printf("Logo rejected: %d bytes exceeds %u-byte limit\n", expected, LOGO_DOWNLOAD_LIMIT);
    http.end();
    releaseNetwork();
    return false;
  }

  logoDownloadCapacity = expected > 0 ? static_cast<size_t>(expected) : LOGO_DOWNLOAD_LIMIT;
  if (psramFound()) {
    logoDownloadBuffer = static_cast<uint8_t*>(heap_caps_malloc(logoDownloadCapacity, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  } else {
    logoDownloadBuffer = static_cast<uint8_t*>(malloc(logoDownloadCapacity));
  }
  if (logoDownloadBuffer == nullptr) {
    logoDownloadCapacity = 0;
    http.end();
    releaseNetwork();
    return false;
  }

  WiFiClient* stream = http.getStreamPtr();
  uint32_t lastDataAt = millis();
  while (length < logoDownloadCapacity) {
    const size_t available = stream->available();
    if (available > 0) {
      const size_t requested = min(available, logoDownloadCapacity - length);
      const size_t readCount = stream->readBytes(logoDownloadBuffer + length, requested);
      length += readCount;
      lastDataAt = millis();
      if (readCount == 0) {
        break;
      }
      continue;
    }
    if (expected >= 0 && length >= static_cast<size_t>(expected)) {
      break;
    }
    if (!http.connected() && stream->available() == 0) {
      break;
    }
    if (millis() - lastDataAt > 8000) {
      break;
    }
    delay(1);
  }
  // An unknown-length response that fills the configured buffer cannot prove
  // that the image ended cleanly. Reject it instead of caching a truncation.
  const bool unknownLengthFilledBuffer = expected < 0 && length == logoDownloadCapacity;
  if (unknownLengthFilledBuffer) {
    lastLogoFailurePermanent = false;
    Serial.printf("Logo rejected: unknown-length response reached %u-byte limit\n", LOGO_DOWNLOAD_LIMIT);
  }
  http.end();
  releaseNetwork();
  const bool complete = length > 0 && !unknownLengthFilledBuffer &&
    (expected < 0 || length == static_cast<size_t>(expected));
  if (!complete) {
    releaseLogoDownloadBuffer();
  }
  return complete;
}

void prepareLogoDecode(RuntimeLogo* logo, int width, int height) {
  activeLogoDecode = logo;
  activeLogoWidth = max(1, width);
  activeLogoHeight = max(1, height);
  const float scale = min(
    static_cast<float>(RUNTIME_LOGO_SIZE) / activeLogoWidth,
    static_cast<float>(RUNTIME_LOGO_SIZE) / activeLogoHeight
  );
  activeLogoScaledWidth = max(1, static_cast<int>(activeLogoWidth * scale + 0.5f));
  activeLogoScaledHeight = max(1, static_cast<int>(activeLogoHeight * scale + 0.5f));
  activeLogoOffsetX = (RUNTIME_LOGO_SIZE - activeLogoScaledWidth) / 2;
  activeLogoOffsetY = (RUNTIME_LOGO_SIZE - activeLogoScaledHeight) / 2;
  memset(logo->pixels, 0, sizeof(logo->pixels));
  memset(logo->mask, 0, sizeof(logo->mask));
  memset(logoSampleCounts, 0, sizeof(logoSampleCounts));
  memset(logoOpaqueCounts, 0, sizeof(logoOpaqueCounts));
  memset(logoRedSums, 0, sizeof(logoRedSums));
  memset(logoGreenSums, 0, sizeof(logoGreenSums));
  memset(logoBlueSums, 0, sizeof(logoBlueSums));
}

void storeDecodedLogoPixel(int sourceX, int sourceY, uint16_t pixel, bool opaque) {
  if (activeLogoDecode == nullptr) {
    return;
  }
  const int targetX = activeLogoOffsetX + (sourceX * activeLogoScaledWidth) / activeLogoWidth;
  const int targetY = activeLogoOffsetY + (sourceY * activeLogoScaledHeight) / activeLogoHeight;
  if (targetX < 0 || targetX >= RUNTIME_LOGO_SIZE || targetY < 0 || targetY >= RUNTIME_LOGO_SIZE) {
    return;
  }
  const size_t index = static_cast<size_t>(targetY) * RUNTIME_LOGO_SIZE + targetX;
  ++logoSampleCounts[index];
  if (!opaque) {
    return;
  }
  ++logoOpaqueCounts[index];
  logoRedSums[index] += ((pixel >> 11) & 0x1F) * 255 / 31;
  logoGreenSums[index] += ((pixel >> 5) & 0x3F) * 255 / 63;
  logoBlueSums[index] += (pixel & 0x1F) * 255 / 31;
}

void finishLogoDecode(RuntimeLogo* logo) {
  if (logo == nullptr) return;
  for (size_t index = 0; index < LOGO_PIXEL_COUNT; ++index) {
    const uint32_t samples = logoSampleCounts[index];
    const uint32_t opaque = logoOpaqueCounts[index];
    if (samples == 0 || opaque == 0) continue;
    // PIL composites transparent antialiased edges against the black panel.
    // Area averaging gives the same visual result without storing the source image.
    if (opaque * 100 < samples * 6) continue;
    const uint32_t averageRed = logoRedSums[index] / opaque;
    const uint32_t averageGreen = logoGreenSums[index] / opaque;
    const uint32_t averageBlue = logoBlueSums[index] / opaque;
    const uint32_t red = averageRed * opaque / samples;
    const uint32_t green = averageGreen * opaque / samples;
    const uint32_t blue = averageBlue * opaque / samples;
    logo->pixels[index] = color(red, green, blue);
    logo->mask[index] = 1;
  }
}

bool logoAvailableInCache(const String& url) {
  if (url.length() == 0) {
    return false;
  }
  if (miniGeneratedLogoAvailable(url)) {
    return true;
  }
  if (knownLogoFailure(url)) {
    return false;
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  }
  for (uint8_t index = 0; index < runtimeLogoSlotCount; ++index) {
    if (runtimeLogos[index].valid && runtimeLogos[index].url == url) {
      if (logoCacheMutex != nullptr) {
        xSemaphoreGive(logoCacheMutex);
      }
      return true;
    }
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
  }
  bool persisted = false;
  if (logoCacheReady) {
    if (logoStorageMutex != nullptr) {
      xSemaphoreTake(logoStorageMutex, portMAX_DELAY);
    }
    persisted = findPersistedLogoSlot(logoUrlHash(url), url, false) >= 0;
    if (logoStorageMutex != nullptr) {
      xSemaphoreGive(logoStorageMutex);
    }
  }
  return persisted;
}

bool logoDeferredOrUnavailable(const String& url) {
  return knownLogoFailure(url) || logoRetrySuppressed(url);
}

bool logoCandidateCached(const String& primaryUrl, const String& fallbackUrl) {
  if (primaryUrl.length() > 0 && logoAvailableInCache(primaryUrl)) {
    return true;
  }
  return fallbackUrl.length() > 0 && fallbackUrl != primaryUrl &&
         logoAvailableInCache(fallbackUrl);
}

bool logoCandidateReady(const String& primaryUrl, const String& fallbackUrl) {
  if (primaryUrl.length() == 0 && fallbackUrl.length() == 0) {
    return true;
  }
  if (primaryUrl.length() == 0) {
    return logoAvailableInCache(fallbackUrl) || logoDeferredOrUnavailable(fallbackUrl);
  }
  if (logoAvailableInCache(primaryUrl)) {
    return true;
  }
  if (!logoDeferredOrUnavailable(primaryUrl)) {
    return false;
  }
  if (fallbackUrl.length() == 0 || fallbackUrl == primaryUrl) {
    return true;
  }
  return logoAvailableInCache(fallbackUrl) || logoDeferredOrUnavailable(fallbackUrl);
}

int pngLogoDraw(PNGDRAW* draw) {
  if (activeLogoDecode == nullptr || draw->iWidth > LOGO_DECODE_WIDTH_LIMIT) {
    return 0;
  }
  pngDecoder.getLineAsRGB565(draw, logoDecodeLine, PNG_RGB565_LITTLE_ENDIAN, 0x00000000);
  pngDecoder.getAlphaMask(draw, logoDecodeMask, 128);
  for (int sourceX = 0; sourceX < draw->iWidth; ++sourceX) {
    const bool opaque = (logoDecodeMask[sourceX / 8] & (0x80 >> (sourceX % 8))) != 0;
    storeDecodedLogoPixel(sourceX, draw->y, logoDecodeLine[sourceX], opaque);
  }
  return 1;
}

int jpegLogoDraw(JPEGDRAW* draw) {
  if (activeLogoDecode == nullptr) {
    return 0;
  }
  for (int row = 0; row < draw->iHeight; ++row) {
    for (int column = 0; column < draw->iWidthUsed; ++column) {
      const size_t index = static_cast<size_t>(row) * draw->iWidth + column;
      storeDecodedLogoPixel(draw->x + column, draw->y + row, draw->pPixels[index], true);
    }
  }
  return 1;
}

bool decodePngLogo(RuntimeLogo* logo, size_t length) {
  const int result = pngDecoder.openRAM(logoDownloadBuffer, static_cast<int>(length), pngLogoDraw);
  if (result != PNG_SUCCESS) {
    return false;
  }
  prepareLogoDecode(logo, pngDecoder.getWidth(), pngDecoder.getHeight());
  const int decodeResult = pngDecoder.decode(nullptr, 0);
  pngDecoder.close();
  finishLogoDecode(logo);
  activeLogoDecode = nullptr;
  return decodeResult == PNG_SUCCESS;
}

bool decodeJpegLogo(RuntimeLogo* logo, size_t length) {
  if (jpegDecoder.openRAM(logoDownloadBuffer, static_cast<int>(length), jpegLogoDraw) == 0) {
    return false;
  }
  const int width = jpegDecoder.getWidth();
  const int height = jpegDecoder.getHeight();
  int options = 0;
  if (max(width, height) > RUNTIME_LOGO_SIZE * 8) {
    options = JPEG_SCALE_EIGHTH;
  } else if (max(width, height) > RUNTIME_LOGO_SIZE * 4) {
    options = JPEG_SCALE_QUARTER;
  } else if (max(width, height) > RUNTIME_LOGO_SIZE * 2) {
    options = JPEG_SCALE_HALF;
  }
  const int divisor = options == JPEG_SCALE_EIGHTH ? 8 : options == JPEG_SCALE_QUARTER ? 4 : options == JPEG_SCALE_HALF ? 2 : 1;
  jpegDecoder.setPixelType(RGB565_LITTLE_ENDIAN);
  prepareLogoDecode(logo, max(1, width / divisor), max(1, height / divisor));
  const int decodeResult = jpegDecoder.decode(0, 0, options);
  jpegDecoder.close();
  finishLogoDecode(logo);
  activeLogoDecode = nullptr;
  return decodeResult == 1;
}

bool decodeDownloadedLogo(RuntimeLogo* logo, size_t length, const String& url) {
  if (length >= 8 && memcmp(logoDownloadBuffer, "\x89PNG\r\n\x1a\n", 8) == 0) {
    return decodePngLogo(logo, length);
  }
  if (length >= 2 && logoDownloadBuffer[0] == 0xff && logoDownloadBuffer[1] == 0xd8) {
    return decodeJpegLogo(logo, length);
  }
  if (decodePngLogo(logo, length) || decodeJpegLogo(logo, length)) {
    return true;
  }
  Serial.printf("Logo format unsupported or decode failed id=%08lX\n",
                static_cast<unsigned long>(logoUrlHash(url)));
  return false;
}

RuntimeLogo* ensureRuntimeLogo(const String& url) {
  if (url.length() == 0) {
    return nullptr;
  }
  if (miniGeneratedLogoAvailable(url)) {
    return nullptr;
  }
  if (knownLogoFailure(url)) {
    return nullptr;
  }
  if (logoRetrySuppressed(url)) {
    return nullptr;
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  }
  for (uint8_t index = 0; index < runtimeLogoSlotCount; ++index) {
    if (runtimeLogos[index].valid && runtimeLogos[index].url == url) {
      if (logoCacheMutex != nullptr) {
        xSemaphoreGive(logoCacheMutex);
      }
      return &runtimeLogos[index];
    }
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
  }
  if (RuntimeLogo* persisted = loadPersistedLogo(url)) {
    return persisted;
  }

  // The download buffer is shared. Serialize transfers separately, because
  // the decoder mutex must not block on network I/O.
  if (logoDownloadMutex != nullptr) {
    xSemaphoreTake(logoDownloadMutex, portMAX_DELAY);
  }
  size_t length = 0;
  RuntimeLogo decoded;
  if (!downloadLogo(url, length)) {
    if (lastLogoFailurePermanent) {
      rememberLogoFailure(url);
    } else {
      rememberLogoRetry(url);
    }
    releaseLogoDownloadBuffer();
    if (logoDownloadMutex != nullptr) {
      xSemaphoreGive(logoDownloadMutex);
    }
    return nullptr;
  }
  clearLogoRetry(url);
  if (logoDecodeMutex != nullptr) {
    xSemaphoreTake(logoDecodeMutex, portMAX_DELAY);
  }
  const bool decodedOk = decodeDownloadedLogo(&decoded, length, url);
  if (logoDecodeMutex != nullptr) {
    xSemaphoreGive(logoDecodeMutex);
  }
  releaseLogoDownloadBuffer();
  if (!decodedOk) {
    Serial.printf("Logo decode failed id=%08lX\n", static_cast<unsigned long>(logoUrlHash(url)));
    rememberLogoFailure(url);
    if (logoDownloadMutex != nullptr) {
      xSemaphoreGive(logoDownloadMutex);
    }
    return nullptr;
  }
  bool hasPixels = false;
  for (uint8_t index = 0; index < RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE; ++index) {
    if (decoded.mask[index] != 0) {
      hasPixels = true;
      break;
    }
  }
  if (!hasPixels) {
    Serial.printf("Logo empty id=%08lX\n", static_cast<unsigned long>(logoUrlHash(url)));
    rememberLogoFailure(url);
    if (logoDownloadMutex != nullptr) {
      xSemaphoreGive(logoDownloadMutex);
    }
    return nullptr;
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  }
  RuntimeLogo* result = freeRuntimeLogoSlot(logoUrlHash(url));
  if (result == nullptr) {
    if (logoCacheMutex != nullptr) {
      xSemaphoreGive(logoCacheMutex);
    }
    if (logoDownloadMutex != nullptr) {
      xSemaphoreGive(logoDownloadMutex);
    }
    Serial.println("Logo cache full: all working-set logos are pinned");
    return nullptr;
  }
  result->url = url;
  memcpy(result->pixels, decoded.pixels, sizeof(result->pixels));
  memcpy(result->mask, decoded.mask, sizeof(result->mask));
  result->valid = true;
  result->pinned = false;
  RuntimeLogo persistenceSnapshot;
  persistenceSnapshot.url = result->url;
  memcpy(persistenceSnapshot.pixels, result->pixels, sizeof(persistenceSnapshot.pixels));
  memcpy(persistenceSnapshot.mask, result->mask, sizeof(persistenceSnapshot.mask));
  persistenceSnapshot.valid = true;
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
  }
  persistLogo(url, &persistenceSnapshot);
  Serial.printf("Logo cached id=%08lX\n", static_cast<unsigned long>(logoUrlHash(url)));
  if (logoDownloadMutex != nullptr) {
    xSemaphoreGive(logoDownloadMutex);
  }
  return result;
}

RuntimeLogo* findCachedLogo(const String& url) {
  if (url.length() == 0 || knownLogoFailure(url)) {
    return nullptr;
  }
  for (uint8_t index = 0; index < runtimeLogoSlotCount; ++index) {
    if (runtimeLogos[index].valid && runtimeLogos[index].url == url) {
      return &runtimeLogos[index];
    }
  }
  // Persistent records are hydrated by ensureRuntimeLogo before rendering.
  // The renderer can therefore read RAM only and never perform LittleFS I/O.
  return nullptr;
}

void prepareSelectedGameLogoSources(JsonObjectConst game) {
  preparedGameLogos.awayPrimary = "";
  preparedGameLogos.awayFallback = "";
  preparedGameLogos.homePrimary = "";
  preparedGameLogos.homeFallback = "";
  if (game.isNull()) {
    return;
  }
  const String away = shortValue(game["away_abbr"], "AWY", 4);
  const String home = shortValue(game["home_abbr"], "HOM", 4);
  preparedGameLogos.awayPrimary = sportsLogoUrl(game, "away_logo", away);
  preparedGameLogos.awayFallback = fallbackSportsLogoUrl(game, away);
  preparedGameLogos.homePrimary = sportsLogoUrl(game, "home_logo", home);
  preparedGameLogos.homeFallback = fallbackSportsLogoUrl(game, home);
}

bool setupRuntimeLogoMemory() {
  const size_t bytes = sizeof(RuntimeLogo) * RUNTIME_LOGO_SLOTS;
  void* storage = nullptr;
  if (psramFound()) {
    storage = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  }
  if (storage != nullptr) {
    runtimeLogoSlotCount = RUNTIME_LOGO_SLOTS;
    Serial.printf("Logo RAM cache: %u slots in PSRAM, internal heap=%u\n",
                  runtimeLogoSlotCount, ESP.getFreeHeap());
  } else {
    runtimeLogoSlotCount = min<uint8_t>(RUNTIME_LOGO_SLOTS, 8);
    storage = heap_caps_malloc(
      sizeof(RuntimeLogo) * runtimeLogoSlotCount,
      MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT
    );
    Serial.printf("Logo RAM cache: PSRAM unavailable, using %u internal slots\n",
                  runtimeLogoSlotCount);
  }
  if (storage == nullptr) {
    runtimeLogoSlotCount = 0;
    Serial.println("Logo RAM cache allocation failed");
    return false;
  }
  runtimeLogos = static_cast<RuntimeLogo*>(storage);
  for (uint8_t index = 0; index < runtimeLogoSlotCount; ++index) {
    new (&runtimeLogos[index]) RuntimeLogo();
  }
  return true;
}

void setupLogoCache() {
  logoCacheReady = LittleFS.begin(true);
}

void drawFallbackLogo(const String& abbreviation, int16_t x, int16_t y, uint16_t background) {
  x += CONTENT_X_OFFSET;
  const uint8_t red = ((background >> 11) & 0x1F) * 255 / 31;
  const uint8_t green = ((background >> 5) & 0x3F) * 255 / 63;
  const uint8_t blue = (background & 0x1F) * 255 / 31;
  const uint16_t dark = color(red / 2, green / 2, blue / 2);
  const uint16_t inner = color(red * 9 / 10, green * 9 / 10, blue * 9 / 10);
  const uint16_t highlight = color(
    red + (255 - red) / 4,
    green + (255 - green) / 4,
    blue + (255 - blue) / 4
  );
  if (abbreviation.length() > 0) {
    String label = abbreviation;
    label.toUpperCase();
    if (label.length() > 3) label.remove(3);
    const int16_t labelWidth = compactPixelTextWidth(label, 1);
    matrix->fillRect(x, y, 18, 18, dark);
    matrix->drawFastHLine(x, y, 18, background);
    matrix->drawFastHLine(x, y + 17, 18, background);
    matrix->drawFastVLine(x, y, 18, background);
    matrix->drawFastVLine(x + 17, y, 18, background);
    drawCompactPixelText(label, x - CONTENT_X_OFFSET + (18 - labelWidth) / 2, y + 6, highlight, 1);
    return;
  }
  matrix->fillRect(x, y, 18, 18, dark);
  matrix->fillRect(x + 2, y + 2, 14, 14, inner);
  matrix->drawFastHLine(x, y, 18, background);
  matrix->drawFastHLine(x, y + 17, 18, background);
  matrix->drawFastVLine(x, y, 18, background);
  matrix->drawFastVLine(x + 17, y, 18, background);
  matrix->drawFastHLine(x + 1, y + 1, 16, highlight);
  matrix->drawFastVLine(x + 1, y + 1, 16, highlight);
}

void drawRuntimeLogo(const RuntimeLogo* logo, int16_t x, int16_t y) {
  if (logo == nullptr || !logo->valid) {
    return;
  }
  for (uint8_t row = 0; row < RUNTIME_LOGO_SIZE; ++row) {
    for (uint8_t column = 0; column < RUNTIME_LOGO_SIZE; ++column) {
      const int16_t targetX = x + CONTENT_X_OFFSET + column;
      const int16_t targetY = y + row;
      if (targetX < 0 || targetX >= 64 || targetY < 0 || targetY >= 32) {
        continue;
      }
      const size_t index = static_cast<size_t>(row) * RUNTIME_LOGO_SIZE + column;
      if (logo->mask[index] != 0) {
        matrix->drawPixel(targetX, targetY, logo->pixels[index]);
      }
    }
  }
}

bool drawLogoAsset(const String& url, int16_t x, int16_t y) {
  if (url.length() == 0) {
    return false;
  }
  const uint16_t* generatedPixels = nullptr;
  const uint8_t* generatedMask = nullptr;
  if (miniGeneratedLogoAsset(url, generatedPixels, generatedMask)) {
    for (uint16_t index = 0; index < LOGO_PIXEL_COUNT; ++index) {
      const uint8_t mask = pgm_read_byte(generatedMask + index / 8);
      if ((mask & (1U << (index % 8))) == 0) {
        continue;
      }
      const int16_t targetX = x + CONTENT_X_OFFSET + index % RUNTIME_LOGO_SIZE;
      const int16_t targetY = y + index / RUNTIME_LOGO_SIZE;
      if (targetX >= 0 && targetX < 64 && targetY >= 0 && targetY < 32) {
        matrix->drawPixel(targetX, targetY, pgm_read_word(generatedPixels + index));
      }
    }
    return true;
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  }
  RuntimeLogo* logo = findCachedLogo(url);
  if (logo != nullptr) {
    drawRuntimeLogo(logo, x, y);
    if (logoCacheMutex != nullptr) {
      xSemaphoreGive(logoCacheMutex);
    }
    return true;
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
  }
  return false;
}

void drawLogoWithFallback(
  const String& primaryUrl,
  const String& fallbackUrl,
  const String& abbreviation,
  int16_t x,
  int16_t y,
  uint16_t fallback
) {
  if (drawLogoAsset(primaryUrl, x, y)) {
    return;
  }
  if (fallbackUrl != primaryUrl && drawLogoAsset(fallbackUrl, x, y)) {
    Serial.printf("Logo fallback used id=%08lX\n",
                  static_cast<unsigned long>(logoUrlHash(fallbackUrl)));
    return;
  }
  drawFallbackLogo(abbreviation, x, y, fallback);
}

bool sportsGameAssetsCached(JsonObjectConst game) {
  String away = shortValue(game["away_abbr"], "AWY", 4);
  String home = shortValue(game["home_abbr"], "HOM", 4);
  const String awayUrl = sportsLogoUrl(game, "away_logo", away);
  const String homeUrl = sportsLogoUrl(game, "home_logo", home);
  const String awayFallback = fallbackSportsLogoUrl(game, away);
  const String homeFallback = fallbackSportsLogoUrl(game, home);
  return logoCandidateReady(awayUrl, awayFallback) &&
         logoCandidateReady(homeUrl, homeFallback);
}

void appendLogoWork(JsonObjectConst game, const char* field, const String& abbreviation) {
  if (logoWorkCount >= LOGO_WORK_QUEUE_SLOTS) {
    return;
  }
  const String primary = sportsLogoUrl(game, field, abbreviation);
  const String fallback = fallbackSportsLogoUrl(game, abbreviation);
  if (primary.length() == 0 && fallback.length() == 0) {
    return;
  }
  for (uint8_t index = 0; index < logoWorkCount; ++index) {
    if (logoWorkPrimary[index] == primary && logoWorkFallback[index] == fallback) {
      return;
    }
  }
  logoWorkPrimary[logoWorkCount] = primary;
  logoWorkFallback[logoWorkCount] = fallback;
  ++logoWorkCount;
}

void appendLogoWorkUrls(const String& primaryUrl, const String& fallbackUrl) {
  if (logoWorkCount >= LOGO_WORK_QUEUE_SLOTS) {
    return;
  }
  if (primaryUrl.length() == 0 && fallbackUrl.length() == 0) {
    return;
  }
  for (uint8_t index = 0; index < logoWorkCount; ++index) {
    if (logoWorkPrimary[index] == primaryUrl && logoWorkFallback[index] == fallbackUrl) {
      return;
    }
  }
  logoWorkPrimary[logoWorkCount] = primaryUrl;
  logoWorkFallback[logoWorkCount] = fallbackUrl;
  ++logoWorkCount;
}

void appendLogoForeground(JsonObjectConst game, const char* field, const String& abbreviation) {
  if (logoForegroundCount >= LOGO_FOREGROUND_GAMES * 2) {
    return;
  }
  logoForegroundPrimary[logoForegroundCount] = sportsLogoUrl(game, field, abbreviation);
  logoForegroundFallback[logoForegroundCount] = fallbackSportsLogoUrl(game, abbreviation);
  ++logoForegroundCount;
}

bool foregroundLogoPlanReady() {
  String primary[LOGO_FOREGROUND_GAMES * 2];
  String fallback[LOGO_FOREGROUND_GAMES * 2];
  uint8_t count = 0;
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  count = logoForegroundCount;
  for (uint8_t index = 0; index < count; ++index) {
    primary[index] = logoForegroundPrimary[index];
    fallback[index] = logoForegroundFallback[index];
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  bool ready = true;
  for (uint8_t index = 0; index < count && ready; ++index) {
    ready = logoCandidateCached(primary[index], fallback[index]);
  }
  return ready;
}

uint16_t foregroundLogoReadyCount() {
  String primary[LOGO_FOREGROUND_GAMES * 2];
  String fallback[LOGO_FOREGROUND_GAMES * 2];
  uint8_t count = 0;
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  count = min<uint8_t>(logoForegroundCount, LOGO_FOREGROUND_GAMES * 2);
  for (uint8_t index = 0; index < count; ++index) {
    primary[index] = logoForegroundPrimary[index];
    fallback[index] = logoForegroundFallback[index];
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  uint16_t readyCount = 0;
  for (uint8_t index = 0; index < count; ++index) {
    if (logoCandidateCached(primary[index], fallback[index])) {
      ++readyCount;
    }
  }
  return readyCount;
}

uint16_t logoWorkReadyCount() {
  String primary[LOGO_WORK_QUEUE_SLOTS];
  String fallback[LOGO_WORK_QUEUE_SLOTS];
  uint8_t count = 0;
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  count = logoWorkCount;
  for (uint8_t index = 0; index < count; ++index) {
    primary[index] = logoWorkPrimary[index];
    fallback[index] = logoWorkFallback[index];
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  uint16_t readyCount = 0;
  for (uint8_t index = 0; index < count; ++index) {
    if (logoCandidateCached(primary[index], fallback[index])) {
      ++readyCount;
    }
  }
  return readyCount;
}

bool commitReadySportsLogoPlan(uint32_t generation) {
  if (generation != logoPlanGeneration || !foregroundLogoPlanReady()) {
    return false;
  }
  pageIndex = logoPlanPageIndex;
  sportsFrameReady = true;
  assetsLoading = false;
  logoPlanDisplayPending = false;
  assetLoadingStartedAt = 0;
  lastPageAt = millis();
  return true;
}

void logoWorkerTask(void* parameter) {
  (void)parameter;
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    for (;;) {
      String primary[LOGO_WORK_QUEUE_SLOTS];
      String fallback[LOGO_WORK_QUEUE_SLOTS];
      uint8_t workCount = 0;
      uint32_t generation = 0;
      if (logoWorkMutex != nullptr) {
        xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      }
      if (!logoWorkerPending) {
        logoWorkerBusy = false;
        if (logoWorkMutex != nullptr) {
          xSemaphoreGive(logoWorkMutex);
        }
        break;
      }
      logoWorkerPending = false;
      logoWorkerBusy = true;
      generation = logoPlanGeneration;
      workCount = logoWorkCount;
      for (uint8_t index = 0; index < workCount; ++index) {
        primary[index] = logoWorkPrimary[index];
        fallback[index] = logoWorkFallback[index];
      }
      if (logoWorkMutex != nullptr) {
        xSemaphoreGive(logoWorkMutex);
      }

      // Network and decoding run without the cache mutex. The decoder mutex
      // only protects the shared PNG/JPEG contexts and download buffer.
      for (uint8_t index = 0; index < workCount; ++index) {
        bool stalePlan = false;
        if (logoWorkMutex != nullptr) {
          xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
          stalePlan = logoWorkerPending || logoPlanGeneration != generation;
          xSemaphoreGive(logoWorkMutex);
        }
        if (stalePlan) {
          break;
        }
        if (miniGeneratedLogoAvailable(primary[index])) {
          continue;
        }
        const bool wasReady = logoCandidateCached(primary[index], fallback[index]);
        RuntimeLogo* logo = ensureRuntimeLogo(primary[index]);
        if (logo == nullptr && fallback[index] != primary[index]) {
          logo = ensureRuntimeLogo(fallback[index]);
        }
        if (logo != nullptr) {
          if (logoCacheMutex != nullptr) {
            xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
          }
          logo->pinned = true;
          if (logoCacheMutex != nullptr) {
            xSemaphoreGive(logoCacheMutex);
          }
          if (!wasReady && logoWorkMutex != nullptr) {
            xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
          }
          if (!wasReady && logoCandidateCached(primary[index], fallback[index])) {
            ++logoProgressComplete;
          }
          if (!wasReady && logoWorkMutex != nullptr) {
            xSemaphoreGive(logoWorkMutex);
          }
        }
      }

      if (logoWorkMutex != nullptr) {
        xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      }
      const bool newerPlanPending = logoWorkerPending || logoPlanGeneration != generation;
      if (logoWorkMutex != nullptr) {
        xSemaphoreGive(logoWorkMutex);
      }
      if (logoWorkMutex != nullptr) {
        xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      }
      if (!newerPlanPending) {
        logoWorkerBusy = false;
        logoWorkerGeneration = generation;
        logoWorkerCompleted = true;
      }
      const uint16_t complete = logoProgressComplete;
      const uint16_t total = logoProgressTotal;
      if (logoWorkMutex != nullptr) {
        xSemaphoreGive(logoWorkMutex);
      }
      if (!newerPlanPending) {
        Serial.printf("Logo worker complete: generation=%lu assets=%u/%u, slots=%u, free heap=%u\n",
                      static_cast<unsigned long>(generation), complete, total,
                      runtimeLogoSlotCount, ESP.getFreeHeap());
        break;
      }
    }
  }
}

RuntimeLogo* loadAndPinLogoForeground(const String& primaryUrl, const String& fallbackUrl, bool countProgress) {
  if (miniGeneratedLogoAvailable(primaryUrl)) {
    return nullptr;
  }
  const bool wasReady = countProgress && logoCandidateCached(primaryUrl, fallbackUrl);
  RuntimeLogo* logo = ensureRuntimeLogo(primaryUrl);
  if (logo == nullptr && fallbackUrl != primaryUrl) {
    logo = ensureRuntimeLogo(fallbackUrl);
  }
  if (logo != nullptr) {
    if (logoCacheMutex != nullptr) {
      xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
    }
    logo->pinned = true;
    if (logoCacheMutex != nullptr) {
      xSemaphoreGive(logoCacheMutex);
    }
    if (countProgress && !wasReady && logoWorkMutex != nullptr) {
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
    }
    if (countProgress && !wasReady && logoCandidateCached(primaryUrl, fallbackUrl)) {
      ++logoProgressComplete;
    }
    if (countProgress && !wasReady && logoWorkMutex != nullptr) {
      xSemaphoreGive(logoWorkMutex);
    }
  }
  return logo;
}

void loadQueuedLogosSynchronously() {
  String primary[LOGO_WORK_QUEUE_SLOTS];
  String fallback[LOGO_WORK_QUEUE_SLOTS];
  uint8_t workCount = 0;
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  workCount = logoWorkCount;
  for (uint8_t index = 0; index < workCount; ++index) {
    primary[index] = logoWorkPrimary[index];
    fallback[index] = logoWorkFallback[index];
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  for (uint8_t index = 0; index < workCount; ++index) {
    loadAndPinLogoForeground(primary[index], fallback[index], index < LOGO_FOREGROUND_GAMES * 2);
  }
}

void prepareSportsLogoWorkingSet(uint16_t requestedPage = 0xFFFF) {
  if (logoCacheMutex != nullptr) {
    xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  }
  for (uint8_t index = 0; index < runtimeLogoSlotCount; ++index) {
    runtimeLogos[index].pinned = false;
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
  }
  if (!sportsMode || pairingMode) {
    assetsLoading = false;
    return;
  }

  const uint16_t gameCount = countShownGames();
  if (gameCount == 0) {
    return;
  }
  const uint16_t targetPage = requestedPage == 0xFFFF ? pageIndex : requestedPage % gameCount;

  const uint16_t windowSize = min<uint16_t>(gameCount, RAM_LOGO_WORKING_SET_GAMES);
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  logoWorkCount = 0;
  logoForegroundCount = 0;
  logoPlanPageIndex = targetPage;
  logoPlanDisplayPending = true;
  logoProgressComplete = 0;
  logoProgressTotal = 0;
  ++logoPlanGeneration;
  JsonArrayConst items = payload["content"]["sports"].as<JsonArrayConst>();
  for (uint16_t offset = 0; offset < windowSize; ++offset) {
    const uint16_t targetIndex = (targetPage + offset) % gameCount;
    uint16_t visibleIndex = 0;
    for (JsonObjectConst item : items) {
      if (!shownItem(item)) {
        continue;
      }
      if (visibleIndex == targetIndex) {
        JsonObjectConst game = item["data"].as<JsonObjectConst>();
        if (!game.isNull()) {
          String away = shortValue(game["away_abbr"], "AWY", 4);
          String home = shortValue(game["home_abbr"], "HOM", 4);
          if (offset < LOGO_FOREGROUND_GAMES) {
            appendLogoForeground(game, "away_logo", away);
            appendLogoForeground(game, "home_logo", home);
          }
          appendLogoWork(game, "away_logo", away);
          appendLogoWork(game, "home_logo", home);
        }
        break;
      }
      ++visibleIndex;
    }
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }

  const uint16_t initialReady = logoWorkReadyCount();
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  logoProgressTotal = logoWorkCount;
  logoProgressComplete = initialReady;
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }

  const bool readyBeforeWorker = foregroundLogoPlanReady();
  if (readyBeforeWorker) {
    pageIndex = targetPage;
    sportsFrameReady = true;
    assetsLoading = false;
    logoPlanDisplayPending = false;
    assetLoadingStartedAt = 0;
    lastPageAt = millis();
  } else {
    assetsLoading = !sportsFrameReady;
    if (assetsLoading && assetLoadingStartedAt == 0) {
      assetLoadingStartedAt = millis();
    }
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  const bool hasWork = logoWorkCount > 0;
  logoWorkerCompleted = false;
  if (hasWork && logoWorkerHandle != nullptr) {
    logoWorkerBusy = true;
    logoWorkerPending = true;
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  if (hasWork && logoWorkerHandle != nullptr) {
    xTaskNotifyGive(logoWorkerHandle);
  } else if (hasWork) {
    Serial.println("Logo worker unavailable. Loading remaining assets on display task.");
    loadQueuedLogosSynchronously();
    commitReadySportsLogoPlan(logoPlanGeneration);
  }
}
// Owns logo source resolution, decoding, cache storage, retry state, and worker planning.
