uint32_t logoUrlHash(const String& url) {
  return hashBody(url);
}

RuntimeLogo* freeRuntimeLogoSlot(uint32_t urlHash) {
  for (uint8_t index = 0; index < RUNTIME_LOGO_SLOTS; ++index) {
    if (!runtimeLogos[index].valid) {
      return &runtimeLogos[index];
    }
  }
  const uint8_t preferred = urlHash % RUNTIME_LOGO_SLOTS;
  if (!runtimeLogos[preferred].pinned) {
    return &runtimeLogos[preferred];
  }
  for (uint8_t offset = 1; offset < RUNTIME_LOGO_SLOTS; ++offset) {
    const uint8_t index = (preferred + offset) % RUNTIME_LOGO_SLOTS;
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
  if (!file || file.size() < static_cast<size_t>(slot + 1) * sizeof(PersistedLogo)) {
    return false;
  }
  file.seek(static_cast<size_t>(slot) * sizeof(PersistedLogo));
  const size_t readCount = file.readBytes(reinterpret_cast<char*>(&record), sizeof(record));
  file.close();
  return readCount == sizeof(record);
}

int findPersistedLogoSlot(uint32_t urlHash, const String& url, bool allowEmpty) {
  const uint16_t start = urlHash % FLASH_LOGO_CACHE_SLOTS;
  PersistedLogo record = {};
  for (uint8_t attempt = 0; attempt < FLASH_LOGO_PROBE_LIMIT; ++attempt) {
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
}

RuntimeLogo* loadPersistedLogo(const String& url) {
  if (!logoCacheReady || url.length() == 0) {
    return nullptr;
  }
  const uint32_t wantedHash = logoUrlHash(url);
  const int slot = findPersistedLogoSlot(wantedHash, url, false);
  if (slot >= 0) {
    PersistedLogo record = {};
    if (readPersistedLogo(static_cast<uint16_t>(slot), record)) {
      RuntimeLogo* result = freeRuntimeLogoSlot(wantedHash);
      if (result == nullptr) {
        return nullptr;
      }
      result->url = url;
      memcpy(result->pixels, record.pixels, sizeof(result->pixels));
      memcpy(result->mask, record.mask, sizeof(result->mask));
      result->valid = true;
      result->pinned = false;
      return result;
    }
  }
  return nullptr;
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
  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(8000);
  http.setFollowRedirects(HTTPC_FORCE_FOLLOW_REDIRECTS);
  http.setRedirectLimit(3);
  if (!http.begin(url)) {
    Serial.print("Logo begin failed: ");
    Serial.println(url);
    return false;
  }
  http.setUserAgent("Mozilla/5.0 MiniTicker/1.0");
  http.addHeader("Accept", "image/png,image/jpeg,image/*,*/*;q=0.8");
  const int status = http.GET();
  const int expected = http.getSize();
  Serial.printf("Logo HTTP %d size=%d url=%s\n", status, expected, url.c_str());
  if (status != HTTP_CODE_OK) {
    lastLogoFailurePermanent = status == HTTP_CODE_NOT_FOUND || status == HTTP_CODE_BAD_REQUEST;
    http.end();
    return false;
  }
  if (expected > static_cast<int>(LOGO_DOWNLOAD_LIMIT)) {
    lastLogoFailurePermanent = true;
    Serial.printf("Logo rejected: %d bytes exceeds %u-byte limit\n", expected, LOGO_DOWNLOAD_LIMIT);
    http.end();
    return false;
  }

  logoDownloadCapacity = expected > 0 ? static_cast<size_t>(expected) : LOGO_DOWNLOAD_LIMIT;
  if (logoDownloadCapacity > 96 * 1024 && psramFound()) {
    logoDownloadBuffer = static_cast<uint8_t*>(heap_caps_malloc(logoDownloadCapacity, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  } else {
    logoDownloadBuffer = static_cast<uint8_t*>(malloc(logoDownloadCapacity));
  }
  if (logoDownloadBuffer == nullptr) {
    logoDownloadCapacity = 0;
    http.end();
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
  if (url.length() == 0 || knownLogoFailure(url)) {
    return false;
  }
  for (uint8_t index = 0; index < RUNTIME_LOGO_SLOTS; ++index) {
    if (runtimeLogos[index].valid && runtimeLogos[index].url == url) {
      return true;
    }
  }
  return logoCacheReady && findPersistedLogoSlot(logoUrlHash(url), url, false) >= 0;
}

bool logoDeferredOrUnavailable(const String& url) {
  return knownLogoFailure(url) || logoRetrySuppressed(url);
}

bool logoCandidateReady(const String& primaryUrl, const String& fallbackUrl) {
  if (logoAvailableInCache(primaryUrl)) {
    return true;
  }
  if (!logoDeferredOrUnavailable(primaryUrl)) {
    return false;
  }
  return logoAvailableInCache(fallbackUrl) || logoDeferredOrUnavailable(fallbackUrl);
}

int pngLogoDraw(PNGDRAW* draw) {
  if (activeLogoDecode == nullptr || draw->iWidth > LOGO_DECODE_WIDTH_LIMIT) {
    return 0;
  }
  pngDecoder.getLineAsRGB565(draw, logoDecodeLine, PNG_RGB565_LITTLE_ENDIAN, 0xffffffff);
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

bool decodeDownloadedLogo(RuntimeLogo* logo, size_t length) {
  if (length >= 8 && memcmp(logoDownloadBuffer, "\x89PNG\r\n\x1a\n", 8) == 0) {
    return decodePngLogo(logo, length);
  }
  if (length >= 2 && logoDownloadBuffer[0] == 0xff && logoDownloadBuffer[1] == 0xd8) {
    return decodeJpegLogo(logo, length);
  }
  return decodePngLogo(logo, length) || decodeJpegLogo(logo, length);
}

RuntimeLogo* ensureRuntimeLogo(const String& url) {
  if (url.length() == 0) {
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
  for (uint8_t index = 0; index < RUNTIME_LOGO_SLOTS; ++index) {
    if (runtimeLogos[index].valid && runtimeLogos[index].url == url) {
      if (logoCacheMutex != nullptr) {
        xSemaphoreGive(logoCacheMutex);
      }
      return &runtimeLogos[index];
    }
  }
  if (RuntimeLogo* persisted = loadPersistedLogo(url)) {
    if (logoCacheMutex != nullptr) {
      xSemaphoreGive(logoCacheMutex);
    }
    return persisted;
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
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
  const bool decodedOk = decodeDownloadedLogo(&decoded, length);
  if (logoDecodeMutex != nullptr) {
    xSemaphoreGive(logoDecodeMutex);
  }
  releaseLogoDownloadBuffer();
  if (!decodedOk) {
    Serial.print("Logo decode failed: ");
    Serial.println(url);
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
    Serial.print("Logo empty: ");
    Serial.println(url);
    rememberLogoFailure(url);
    if (logoDownloadMutex != nullptr) {
      xSemaphoreGive(logoDownloadMutex);
    }
    return nullptr;
  }
  // Match the larger ticker asset pipeline. Dark logos receive a one-pixel
  // light ring so they remain visible on the black matrix background.
  uint16_t opaqueCount = 0;
  uint16_t darkCount = 0;
  for (uint8_t row = 0; row < RUNTIME_LOGO_SIZE; ++row) {
    for (uint8_t column = 0; column < RUNTIME_LOGO_SIZE; ++column) {
      const size_t index = static_cast<size_t>(row) * RUNTIME_LOGO_SIZE + column;
      if (decoded.mask[index] == 0) continue;
      ++opaqueCount;
      const uint16_t pixel = decoded.pixels[index];
      const uint8_t red = ((pixel >> 11) & 0x1F) * 255 / 31;
      const uint8_t green = ((pixel >> 5) & 0x3F) * 255 / 63;
      const uint8_t blue = (pixel & 0x1F) * 255 / 31;
      if (red * 212 + green * 715 + blue * 72 < 40000) ++darkCount;
    }
  }
  if (opaqueCount > 0 && darkCount * 100 >= opaqueCount * 92) {
    uint8_t originalMask[RUNTIME_LOGO_SIZE * RUNTIME_LOGO_SIZE] = {};
    memcpy(originalMask, decoded.mask, sizeof(originalMask));
    const uint16_t ringColor = color(245, 245, 245);
    for (uint8_t row = 0; row < RUNTIME_LOGO_SIZE; ++row) {
      for (uint8_t column = 0; column < RUNTIME_LOGO_SIZE; ++column) {
        const size_t index = static_cast<size_t>(row) * RUNTIME_LOGO_SIZE + column;
        if (originalMask[index] != 0) continue;
        bool adjacent = false;
        for (int8_t rowDelta = -1; rowDelta <= 1 && !adjacent; ++rowDelta) {
          for (int8_t columnDelta = -1; columnDelta <= 1; ++columnDelta) {
            const int16_t neighborRow = row + rowDelta;
            const int16_t neighborColumn = column + columnDelta;
            if (neighborRow >= 0 && neighborRow < RUNTIME_LOGO_SIZE &&
                neighborColumn >= 0 && neighborColumn < RUNTIME_LOGO_SIZE &&
                originalMask[static_cast<size_t>(neighborRow) * RUNTIME_LOGO_SIZE + neighborColumn] != 0) {
              adjacent = true;
              break;
            }
          }
        }
        if (adjacent) {
          decoded.pixels[index] = ringColor;
          decoded.mask[index] = 1;
        }
      }
    }
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
  persistLogo(url, result);
  Serial.print("Logo cached: ");
  Serial.println(url);
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
  }
  if (logoDownloadMutex != nullptr) {
    xSemaphoreGive(logoDownloadMutex);
  }
  return result;
}

RuntimeLogo* findCachedLogo(const String& url) {
  if (url.length() == 0 || knownLogoFailure(url)) {
    return nullptr;
  }
  for (uint8_t index = 0; index < RUNTIME_LOGO_SLOTS; ++index) {
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

void setupLogoCache() {
  logoCacheReady = LittleFS.begin(true);
}

void drawFallbackLogo(const String& abbreviation, int16_t x, int16_t y, uint16_t background) {
  (void)abbreviation;
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
    Serial.print("Logo fallback used: ");
    Serial.println(fallbackUrl);
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
  logoWorkPrimary[logoWorkCount] = sportsLogoUrl(game, field, abbreviation);
  logoWorkFallback[logoWorkCount] = fallbackSportsLogoUrl(game, abbreviation);
  ++logoWorkCount;
}

void appendLogoWorkUrls(const String& primaryUrl, const String& fallbackUrl) {
  if (logoWorkCount >= LOGO_WORK_QUEUE_SLOTS) {
    return;
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
        RuntimeLogo* logo = ensureRuntimeLogo(primary[index]);
        if (logo == nullptr && fallback[index] != primary[index]) {
          logo = ensureRuntimeLogo(fallback[index]);
        }
        if (logo != nullptr) {
          if (logoCacheMutex != nullptr) {
            xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
          }
          logo->pinned = true;
          if (logoWorkMutex != nullptr) {
            xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
          }
          ++logoProgressComplete;
          if (logoWorkMutex != nullptr) {
            xSemaphoreGive(logoWorkMutex);
          }
          if (logoCacheMutex != nullptr) {
            xSemaphoreGive(logoCacheMutex);
          }
        }
      }

      if (logoWorkMutex != nullptr) {
        xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      }
      const bool newerPlanPending = logoWorkerPending || logoPlanGeneration != generation;
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
                      RUNTIME_LOGO_SLOTS, ESP.getFreeHeap());
        break;
      }
    }
  }
}

RuntimeLogo* loadAndPinLogoForeground(const String& primaryUrl, const String& fallbackUrl) {
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
    if (logoWorkMutex != nullptr) {
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
    }
    ++logoProgressComplete;
    if (logoWorkMutex != nullptr) {
      xSemaphoreGive(logoWorkMutex);
    }
  }
  bool loading = false;
  uint16_t complete = 0;
  uint16_t total = 0;
  logoProgressSnapshot(loading, complete, total);
  if (loading) {
    drawDownloadingProgress(complete, total);
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
    loadAndPinLogoForeground(primary[index], fallback[index]);
  }
}

void prepareSportsLogoWorkingSet() {
  bool workerActive = false;
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  workerActive = logoWorkerBusy || logoWorkerPending;
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  }
  for (uint8_t index = 0; index < RUNTIME_LOGO_SLOTS; ++index) {
    runtimeLogos[index].pinned = false;
  }
  if (!sportsMode || pairingMode) {
    if (logoCacheMutex != nullptr) {
      xSemaphoreGive(logoCacheMutex);
    }
    return;
  }

  const uint16_t gameCount = countShownGames();
  if (gameCount == 0) {
    if (logoCacheMutex != nullptr) {
      xSemaphoreGive(logoCacheMutex);
    }
    return;
  }
  if (pageIndex >= gameCount) {
    pageIndex = 0;
  }

  const uint16_t windowSize = min<uint16_t>(gameCount, RAM_LOGO_WORKING_SET_GAMES);
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  logoWorkCount = 0;
  logoForegroundCount = 0;
  logoProgressComplete = 0;
  logoProgressTotal = windowSize * 2;
  ++logoPlanGeneration;
  JsonArrayConst items = payload["content"]["sports"].as<JsonArrayConst>();
  for (uint16_t offset = 0; offset < windowSize; ++offset) {
    const uint16_t targetIndex = (pageIndex + offset) % gameCount;
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
          if (offset < LOGO_FOREGROUND_GAMES && !workerActive) {
            appendLogoForeground(game, "away_logo", away);
            appendLogoForeground(game, "home_logo", home);
          } else {
            appendLogoWork(game, "away_logo", away);
            appendLogoWork(game, "home_logo", home);
          }
        }
        break;
      }
      ++visibleIndex;
    }
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }

  if (workerActive) {
    if (logoWorkMutex != nullptr) {
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      logoWorkerPending = true;
      logoWorkerCompleted = false;
      xSemaphoreGive(logoWorkMutex);
    } else {
      logoWorkerPending = true;
      logoWorkerCompleted = false;
    }
    if (logoWorkerHandle != nullptr) {
      xTaskNotifyGive(logoWorkerHandle);
    }
    return;
  }

  bool foregroundNeedsDownload = false;
  if (logoCacheMutex != nullptr) {
    xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  }
  for (uint8_t index = 0; index < logoForegroundCount; ++index) {
    if (!logoAvailableInCache(logoForegroundPrimary[index]) &&
        !logoAvailableInCache(logoForegroundFallback[index])) {
      foregroundNeedsDownload = true;
      break;
    }
  }
  if (logoCacheMutex != nullptr) {
    xSemaphoreGive(logoCacheMutex);
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  assetsLoading = foregroundNeedsDownload;
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  bool loading = false;
  uint16_t complete = 0;
  uint16_t total = 0;
  logoProgressSnapshot(loading, complete, total);
  if (loading) {
    drawDownloadingProgress(complete, total);
  }
  for (uint8_t index = 0; index < logoForegroundCount; ++index) {
    RuntimeLogo* logo = loadAndPinLogoForeground(logoForegroundPrimary[index], logoForegroundFallback[index]);
    if (logo == nullptr) {
      appendLogoWorkUrls(logoForegroundPrimary[index], logoForegroundFallback[index]);
    }
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  }
  assetsLoading = false;
  const bool hasBackgroundWork = logoWorkCount > 0;
  logoWorkerCompleted = false;
  if (hasBackgroundWork && logoWorkerHandle != nullptr) {
    logoWorkerBusy = true;
    logoWorkerPending = true;
  }
  if (logoWorkMutex != nullptr) {
    xSemaphoreGive(logoWorkMutex);
  }
  if (hasBackgroundWork && logoWorkerHandle != nullptr) {
    xTaskNotifyGive(logoWorkerHandle);
  } else if (hasBackgroundWork) {
    if (logoWorkMutex != nullptr) {
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
    }
    assetsLoading = true;
    if (logoWorkMutex != nullptr) {
      xSemaphoreGive(logoWorkMutex);
    }
    Serial.println("Logo worker unavailable. Loading remaining assets on display task.");
    loadQueuedLogosSynchronously();
    if (logoWorkMutex != nullptr) {
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
    }
    assetsLoading = false;
    if (logoWorkMutex != nullptr) {
      xSemaphoreGive(logoWorkMutex);
    }
  }
}
// Owns logo source resolution, decoding, cache storage, retry state, and worker planning.
