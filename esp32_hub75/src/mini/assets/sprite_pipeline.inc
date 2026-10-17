// Own Mini sprite transfer, validated storage, RAM reads, and worker planning.
#include "mini_sprite.h"
#include "logo_residency.h"

uint32_t spriteFlashHits = 0;
uint32_t spriteDownloads = 0;
uint32_t spriteInvalidFiles = 0;
uint32_t spriteEvictions = 0;
uint32_t spriteHeapBeforeTls = 0;
uint32_t spriteHeapDuringTls = 0;
uint32_t spriteHeapAfterTls = 0;
uint32_t spriteLargestDuringTls = 0;

bool spriteHash(const uint8_t* bytes, size_t length, uint8_t* output) {
  const mbedtls_md_info_t* algorithm = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  return algorithm != nullptr && mbedtls_md(algorithm, bytes, length, output) == 0;
}

class LittleSpriteStore : public mini_sprite::Store {
 public:
  String path(const char* id) { return String("/sprites/") + id + ".mts"; }
  size_t read(const char* id, uint8_t* bytes, size_t capacity, bool staged = false) override {
    File file = LittleFS.open(staged ? "/sprites/.write.tmp" : path(id), "r");
    if (!file) return 0;
    const size_t length = file.size();
    const size_t readBytes = length <= capacity ? file.read(bytes, length) : length;
    file.close();
    return readBytes;
  }
  bool stage(const uint8_t* bytes, size_t length) override {
    File file = LittleFS.open("/sprites/.write.tmp", "w");
    if (!file) return false;
    const bool written = file.write(bytes, length) == length;
    file.flush();
    file.close();
    return written;
  }
  bool commit(const char* id) override { return LittleFS.rename("/sprites/.write.tmp", path(id)); }
  void discard() override { LittleFS.remove("/sprites/.write.tmp"); }
  bool erase(const char* id) override {
    if (!LittleFS.remove(path(id))) return false;
    ++spriteEvictions;
    return true;
  }
  size_t count() override {
    size_t total = 0;
    File directory = LittleFS.open("/sprites");
    for (File file = directory.openNextFile(); file; file = directory.openNextFile()) {
      if (String(file.name()).endsWith(".mts")) ++total;
      file.close();
    }
    directory.close();
    return total;
  }
  bool oldest(char* id, const char* protectedId) override {
    String selected;
    time_t selectedTime = 0;
    File directory = LittleFS.open("/sprites");
    for (File file = directory.openNextFile(); file; file = directory.openNextFile()) {
      String name = file.name();
      name = name.substring(name.lastIndexOf('/') + 1);
      if (name.endsWith(".mts")) name.remove(name.length() - 4);
      const time_t modified = file.getLastWrite();
      if (mini_sprite::digestValid(name.c_str()) && name != protectedId &&
          (selected.length() == 0 || modified < selectedTime || (modified == selectedTime && name < selected))) {
        selected = name;
        selectedTime = modified;
      }
      file.close();
    }
    directory.close();
    if (selected.length() == 0) return false;
    selected.toCharArray(id, 65);
    return true;
  }
};

LittleSpriteStore spriteStore;
mini_sprite::Cache spriteCache(spriteStore, spriteHash, SPRITE_FLASH_LIMIT);

RuntimeLogo* freeRuntimeLogoSlot(uint32_t hash) {
  if (runtimeLogos == nullptr || runtimeLogoSlotCount == 0) return nullptr;
  for (uint8_t index = 0; index < runtimeLogoSlotCount; ++index) {
    if (!runtimeLogos[index].valid) return &runtimeLogos[index];
  }
  for (uint8_t offset = 0; offset < runtimeLogoSlotCount; ++offset) {
    const uint8_t index = (hash + offset) % runtimeLogoSlotCount;
    if (!runtimeLogos[index].pinned) return &runtimeLogos[index];
  }
  return nullptr;
}

RuntimeLogo* findCachedLogo(const String& key) {
  for (uint8_t index = 0; index < runtimeLogoSlotCount; ++index) {
    if (runtimeLogos[index].valid && runtimeLogos[index].url == key) return &runtimeLogos[index];
  }
  return nullptr;
}

bool logoAvailableInCache(const String& key) {
  if (key.length() == 0) return true;
  if (logoCacheMutex == nullptr) return false;
  xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  const bool ready = findCachedLogo(key) != nullptr;
  xSemaphoreGive(logoCacheMutex);
  return ready;
}

bool downloadSprite(const mini_sprite::Reference& reference, uint8_t* body) {
  if (WiFi.status() != WL_CONNECTED) return false;
  NetworkLease lease(networkGate, 12000);
  if (!lease) return false;
  bool success = false;
  spriteHeapBeforeTls = ESP.getFreeHeap();
  {
    BackendTlsClient client;
    configureTls(client);
    client.setTimeout(8);
    client.setHandshakeTimeout(8);
    HTTPClient http;
    http.useHTTP10(true);
    http.setReuse(false);
    http.setConnectTimeout(4000);
    http.setTimeout(8000);
    if (http.begin(client, backendEndpoint(String("/api/v2/assets/mini-sports/") + reference.id + ".mts"))) {
      const int status = http.GET();
      spriteHeapDuringTls = ESP.getFreeHeap();
      spriteLargestDuringTls = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
      if (status == HTTP_CODE_OK && http.getSize() == static_cast<int>(mini_sprite::kBytes)) {
        const size_t received = http.getStreamPtr()->readBytes(body, mini_sprite::kBytes);
        success = mini_sprite::validate(body, received, reference, spriteHash);
      }
      logSecureHttpError("Sprite", status, client);
      Serial.printf("Sprite HTTP status=%d length=%d valid=%d heap_before=%u heap_during=%u largest=%u\n", status, http.getSize(), success, spriteHeapBeforeTls, spriteHeapDuringTls, spriteLargestDuringTls);
      http.end();
    }
  }
  spriteHeapAfterTls = ESP.getFreeHeap();
  if (success) ++spriteDownloads;
  return success;
}

bool ensureRuntimeLogo(const String& key, uint32_t generation) {
  mini_sprite::Reference reference;
  if (!mini_sprite::parseReference(key.c_str(), reference)) return false;
  xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  if (!mini_sprite::acceptLogoResult(generation, logoPlanGeneration, key, logoWorkPrimary, logoWorkCount)) {
    xSemaphoreGive(logoWorkMutex);
    return false;
  }
  xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  RuntimeLogo* cached = findCachedLogo(key);
  if (cached != nullptr) cached->pinned = true;
  xSemaphoreGive(logoCacheMutex);
  xSemaphoreGive(logoWorkMutex);
  if (cached != nullptr) return true;
  for (uint8_t index = 0; index < logoRetryCount; ++index) {
    if (logoRetryUrls[index] == key && static_cast<int32_t>(millis() - logoRetryAfter[index]) < 0) return false;
  }
  uint8_t bytes[mini_sprite::kBytes];
  const auto loaded = logoCacheReady ? spriteCache.load(reference, bytes) : mini_sprite::LoadResult::Miss;
  if (loaded == mini_sprite::LoadResult::Hit) {
    ++spriteFlashHits;
    Serial.printf("Sprite flash hit %.8s\n", reference.id);
  } else {
    if (loaded == mini_sprite::LoadResult::Invalid) ++spriteInvalidFiles;
    if (!downloadSprite(reference, bytes)) {
      uint8_t slot = 0;
      for (; slot < logoRetryCount; ++slot) if (logoRetryUrls[slot] == key) break;
      if (slot == logoRetryCount) slot = logoRetryCount < LOGO_FAILURE_SLOTS ? logoRetryCount++ : logoRetryIndex++ % LOGO_FAILURE_SLOTS;
      logoRetryUrls[slot] = key;
      logoRetryAfter[slot] = millis() + LOGO_RETRY_BACKOFF_MS;
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      if (spriteRetryDueAt == 0 || static_cast<int32_t>(logoRetryAfter[slot] - spriteRetryDueAt) < 0) spriteRetryDueAt = logoRetryAfter[slot];
      xSemaphoreGive(logoWorkMutex);
      return false;
    }
    if (logoCacheReady && !spriteCache.save(reference, bytes)) Serial.println("Sprite flash write failed");
  }
  xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  if (!mini_sprite::acceptLogoResult(generation, logoPlanGeneration, key, logoWorkPrimary, logoWorkCount)) {
    xSemaphoreGive(logoWorkMutex);
    return false;
  }
  xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  RuntimeLogo* result = freeRuntimeLogoSlot(hashBody(key));
  if (result != nullptr) {
    result->valid = false;
    result->url = key;
    mini_sprite::decodeScaled(bytes, result->pixels, result->mask, RUNTIME_LOGO_SIZE);
    result->valid = true;
    result->pinned = true;
  }
  xSemaphoreGive(logoCacheMutex);
  xSemaphoreGive(logoWorkMutex);
  return result != nullptr;
}

bool setupRuntimeLogoMemory() {
  const size_t bytes = sizeof(RuntimeLogo) * RUNTIME_LOGO_SLOTS;
  void* storage = psramFound() ? heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) : nullptr;
  runtimeLogoSlotCount = storage != nullptr ? RUNTIME_LOGO_SLOTS : min<uint8_t>(RUNTIME_LOGO_SLOTS, 8);
  if (storage == nullptr) storage = heap_caps_malloc(sizeof(RuntimeLogo) * runtimeLogoSlotCount, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (storage == nullptr) { runtimeLogoSlotCount = 0; return false; }
  runtimeLogos = static_cast<RuntimeLogo*>(storage);
  for (uint8_t index = 0; index < runtimeLogoSlotCount; ++index) new (&runtimeLogos[index]) RuntimeLogo();
  return true;
}

void setupLogoCache() {
  logoCacheReady = LittleFS.begin(true);
  if (!logoCacheReady) return;
  LittleFS.mkdir("/sprites");
  spriteStore.discard();
  LittleFS.remove("/logo_cache_v9.bin");
  LittleFS.remove("/logo_cache_v10.bin");
  Serial.printf("Sprite cache ready files=%u\n", static_cast<unsigned>(spriteStore.count()));
}

bool drawLogoAsset(const String& key, int16_t x, int16_t y) {
  if (logoCacheMutex == nullptr) return false;
  xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  RuntimeLogo* logo = findCachedLogo(key);
  if (logo != nullptr) {
    for (uint16_t index = 0; index < LOGO_PIXEL_COUNT; ++index) {
      const int16_t tx = x + index % RUNTIME_LOGO_SIZE;
      const int16_t ty = y + index / RUNTIME_LOGO_SIZE;
      if (logo->mask[index] && tx >= 0 && tx < 64 && ty >= 0 && ty < 32) matrix->drawPixel(tx, ty, logo->pixels[index]);
    }
  }
  xSemaphoreGive(logoCacheMutex);
  return logo != nullptr;
}

void prepareSelectedGameLogoSources(JsonObjectConst game) {
  preparedGameLogos.awayPrimary = miniSpriteToken(game, "away_logo_asset");
  preparedGameLogos.homePrimary = miniSpriteToken(game, "home_logo_asset");
}

void appendLogoWork(JsonObjectConst game, const char* field) {
  const String key = miniSpriteToken(game, field);
  if (key.length() == 0 || logoWorkCount >= LOGO_WORK_QUEUE_SLOTS) return;
  for (uint8_t index = 0; index < logoWorkCount; ++index) if (logoWorkPrimary[index] == key) return;
  logoWorkPrimary[logoWorkCount++] = key;
}

void appendLogoForeground(JsonObjectConst game, const char* field) {
  if (logoForegroundCount < LOGO_FOREGROUND_GAMES * 2) logoForegroundPrimary[logoForegroundCount++] = miniSpriteToken(game, field);
}

uint16_t foregroundLogoReadyCount() {
  if (logoWorkMutex == nullptr) return 0;
  String keys[LOGO_FOREGROUND_GAMES * 2];
  xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  const uint8_t count = logoForegroundCount;
  for (uint8_t index = 0; index < count; ++index) keys[index] = logoForegroundPrimary[index];
  xSemaphoreGive(logoWorkMutex);
  uint16_t ready = 0;
  for (uint8_t index = 0; index < count; ++index) ready += logoAvailableInCache(keys[index]);
  return ready;
}

bool foregroundLogoPlanReady() { return foregroundLogoReadyCount() == logoForegroundCount; }

uint16_t logoWorkReadyCount() {
  uint16_t ready = 0;
  for (uint8_t index = 0; index < logoWorkCount; ++index) ready += logoAvailableInCache(logoWorkPrimary[index]);
  return ready;
}

bool sportsGameAssetsCached(JsonObjectConst game) {
  return logoAvailableInCache(miniSpriteToken(game, "away_logo_asset")) && logoAvailableInCache(miniSpriteToken(game, "home_logo_asset"));
}

bool commitReadySportsLogoPlan(uint32_t generation) {
  if (generation != logoPlanGeneration || !foregroundLogoPlanReady()) return false;
  if (!sportsFrameReady) pageIndex = logoPlanPageIndex;
  sportsFrameReady = true;
  assetsLoading = false;
  logoPlanDisplayPending = false;
  assetLoadingStartedAt = 0;
  return true;
}

void logoWorkerTask(void* parameter) {
  (void)parameter;
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    for (;;) {
      String keys[LOGO_WORK_QUEUE_SLOTS];
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      if (!logoWorkerPending) {
        logoWorkerBusy = false;
        xSemaphoreGive(logoWorkMutex);
        break;
      }
      logoWorkerPending = false;
      logoWorkerBusy = true;
      const uint32_t generation = logoPlanGeneration;
      const uint8_t count = logoWorkCount;
      for (uint8_t index = 0; index < count; ++index) keys[index] = logoWorkPrimary[index];
      xSemaphoreGive(logoWorkMutex);
      for (uint8_t index = 0; index < count; ++index) {
        xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
        const bool stale = logoWorkerPending || logoPlanGeneration != generation;
        xSemaphoreGive(logoWorkMutex);
        if (stale) break;
        ensureRuntimeLogo(keys[index], generation);
      }
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      if (!logoWorkerPending && logoPlanGeneration == generation) {
        logoProgressComplete = logoWorkReadyCount();
        logoWorkerBusy = false;
        logoWorkerGeneration = generation;
        logoWorkerCompleted = true;
        Serial.printf("Sprite worker complete generation=%lu hits=%u downloads=%u invalid=%u evictions=%u heap_after_tls=%u\n", static_cast<unsigned long>(generation), spriteFlashHits, spriteDownloads, spriteInvalidFiles, spriteEvictions, spriteHeapAfterTls);
      }
      xSemaphoreGive(logoWorkMutex);
    }
  }
}

void prepareSportsLogoWorkingSet(uint16_t requestedPage = 0xFFFF) {
  if (!sportsMode || pairingMode) {
    assetsLoading = false;
    return;
  }

  const uint16_t gameCount = countShownGames();
  if (gameCount == 0) {
    return;
  }
  const uint16_t targetPage = requestedPage == 0xFFFF ? pageIndex : requestedPage % gameCount;

  const uint16_t windowSize = min<uint16_t>(gameCount, runtimeLogoSlotCount / 2);
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
          if (offset < LOGO_FOREGROUND_GAMES) {
            appendLogoForeground(game, "away_logo_asset");
            appendLogoForeground(game, "home_logo_asset");
          }
          appendLogoWork(game, "away_logo_asset");
          appendLogoWork(game, "home_logo_asset");
        }
        break;
      }
      ++visibleIndex;
    }
  }
  xSemaphoreTake(logoCacheMutex, portMAX_DELAY);
  mini_sprite::pinResidentWindow(runtimeLogos, runtimeLogoSlotCount, logoWorkPrimary, logoWorkCount);
  xSemaphoreGive(logoCacheMutex);
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
    if (!sportsFrameReady) pageIndex = targetPage;
    sportsFrameReady = true;
    assetsLoading = false;
    logoPlanDisplayPending = false;
    assetLoadingStartedAt = 0;
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
    Serial.println("Sprite worker unavailable");
    assetsLoading = false;
    if (!sportsFrameReady) pageIndex = targetPage;
    sportsFrameReady = true;
  }
}
