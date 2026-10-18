// Runtime planning owns generations and page selection. SpriteAssets owns storage and RAM pixels.
#include "mini_sprite.h"
#include "logo_residency.h"

bool ensureRuntimeLogo(const String& key, bool allowDownload) {
  mini_sprite::Reference reference;
  if (!mini_sprite::parseReference(key.c_str(), reference)) return false;
  xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  if (!mini_sprite::plannedLogo(key, logoWorkPrimary, logoWorkCount)) {
    xSemaphoreGive(logoWorkMutex);
    return false;
  }
  const bool cached = spriteAssets.pinCached(key);
  xSemaphoreGive(logoWorkMutex);
  if (cached) return true;
  for (uint8_t index = 0; allowDownload && index < logoRetryCount; ++index) {
    if (logoRetryUrls[index] == key && static_cast<int32_t>(millis() - logoRetryAfter[index]) < 0) return false;
  }
  uint8_t bytes[mini_sprite::kBytes];
  if (!(allowDownload ? spriteAssets.load(key, bytes) : spriteAssets.loadCached(key, bytes))) {
      if (!allowDownload) return false;
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
  xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
  if (!mini_sprite::plannedLogo(key, logoWorkPrimary, logoWorkCount)) {
    xSemaphoreGive(logoWorkMutex);
    return false;
  }
  const bool installed = spriteAssets.install(key, bytes);
  xSemaphoreGive(logoWorkMutex);
  return installed;
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
  for (uint8_t index = 0; index < count; ++index) ready += spriteAssets.available(keys[index]);
  return ready;
}

bool foregroundLogoPlanReady() { return foregroundLogoReadyCount() == logoForegroundCount; }

uint16_t logoWorkReadyCount() {
  uint16_t ready = 0;
  for (uint8_t index = 0; index < logoWorkCount; ++index) ready += spriteAssets.available(logoWorkPrimary[index]);
  return ready;
}

bool sportsGameAssetsCached(JsonObjectConst game) {
  return spriteAssets.available(miniSpriteToken(game, "away_logo_asset")) && spriteAssets.available(miniSpriteToken(game, "home_logo_asset"));
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
    while (musicArtwork.pending()) musicArtwork.loadPending();
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
      for (uint8_t index = 0; index < count; ++index) ensureRuntimeLogo(keys[index], false);
      for (uint8_t index = 0; index < count; ++index) {
        xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
        const bool stale = logoWorkerPending || logoPlanGeneration != generation;
        xSemaphoreGive(logoWorkMutex);
        if (stale) break;
        ensureRuntimeLogo(keys[index], true);
        delay(1);
      }
      xSemaphoreTake(logoWorkMutex, portMAX_DELAY);
      if (!logoWorkerPending && logoPlanGeneration == generation) {
        logoProgressComplete = logoWorkReadyCount();
        logoWorkerBusy = false;
        logoWorkerGeneration = generation;
        logoWorkerCompleted = true;
        Serial.printf("Sprite worker complete generation=%lu hits=%u downloads=%u invalid=%u evictions=%u heap_after_tls=%u\n", static_cast<unsigned long>(generation), spriteAssets.metrics().flashHits, spriteAssets.metrics().downloads, spriteAssets.metrics().invalidFiles, spriteAssets.metrics().evictions, spriteAssets.metrics().heapAfterTls);
      }
      xSemaphoreGive(logoWorkMutex);
    }
  }
}

void prepareMusicArtwork() {
  JsonObjectConst music;
  if (displayMode == "music" && !pairingMode) {
    for (JsonObjectConst item : payload.document()["content"]["music"].as<JsonArrayConst>()) {
      if (!shownItem(item)) continue;
      music = item["data"].as<JsonObjectConst>();
      break;
    }
  }
  if (musicArtwork.request(music) && logoWorkerHandle) xTaskNotifyGive(logoWorkerHandle);
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

  const uint16_t windowSize = min<uint16_t>(gameCount, spriteAssets.slotCount() / 2);
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
  JsonArrayConst items = payload.document()["content"]["sports"].as<JsonArrayConst>();
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
  spriteAssets.pinWindow(logoWorkPrimary, logoWorkCount);
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
