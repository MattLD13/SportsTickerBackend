#include "sprite_assets.h"
#include "mini_sprite.h"
#include "logo_residency.h"
#include "../platform/config.h"
#include "../runtime/network.h"
#include <Adafruit_GFX.h>
#include <LittleFS.h>
#include <esp_heap_caps.h>
#include <mbedtls/md.h>
#include <new>

static bool spriteHash(const uint8_t* bytes, size_t length, uint8_t* output) {
  const auto* algorithm = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  return algorithm && mbedtls_md(algorithm, bytes, length, output) == 0;
}

class LittleSpriteStore : public mini_sprite::Store {
 public:
  explicit LittleSpriteStore(SpriteAssets::Metrics& metrics) : metrics_(metrics) {}
  ~LittleSpriteStore() { heap_caps_free(entries_); }
  bool begin() {
    if (!reserve(SPRITE_FLASH_LIMIT + 1)) return false;
    File directory = LittleFS.open("/sprites");
    size_t visited = 0;
    for (File file = directory.openNextFile(); file; file = directory.openNextFile()) {
      String name = file.name();
      name = name.substring(name.lastIndexOf('/') + 1);
      if (name.endsWith(".mts")) {
        name.remove(name.length() - 4);
        if (mini_sprite::digestValid(name.c_str()) && !remember(name.c_str(), file.getLastWrite())) {
          file.close(); directory.close(); return false;
        }
      }
      file.close();
      if (++visited % 8 == 0) delay(1);
    }
    directory.close();
    while (count_ > SPRITE_FLASH_LIMIT) {
      char identity[65];
      if (!oldest(identity, "") || !erase(identity)) return false;
    }
    return true;
  }
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
  bool commit(const char* id) override {
    if (!LittleFS.rename("/sprites/.write.tmp", path(id))) return false;
    File file = LittleFS.open(path(id), "r");
    if (!file) return false;
    const time_t modified = file.getLastWrite();
    file.close();
    return remember(id, modified);
  }
  void discard() override { LittleFS.remove("/sprites/.write.tmp"); }
  bool erase(const char* id) override {
    if (!LittleFS.remove(path(id))) return false;
    for (size_t index = 0; index < count_; ++index) if (strcmp(entries_[index].id, id) == 0) {
      entries_[index] = entries_[--count_];
      break;
    }
    ++metrics_.evictions;
    return true;
  }
  size_t count() override { return count_; }
  bool oldest(char* id, const char* protectedId) override {
    const Entry* selected = nullptr;
    for (size_t index = 0; index < count_; ++index) {
      const auto& entry = entries_[index];
      if (strcmp(entry.id, protectedId) == 0) continue;
      if (!selected || entry.modified < selected->modified ||
          (entry.modified == selected->modified && strcmp(entry.id, selected->id) < 0)) selected = &entry;
    }
    if (!selected) return false;
    memcpy(id, selected->id, 65);
    return true;
  }
 private:
  struct Entry { char id[65]; time_t modified; };
  Entry* entries_ = nullptr;
  size_t count_ = 0, capacity_ = 0;
  bool reserve(size_t count) {
    if (count <= capacity_) return true;
    const size_t next = max(count, capacity_ * 2);
    void* memory = heap_caps_realloc(entries_, next * sizeof(Entry), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!memory) return false;
    entries_ = static_cast<Entry*>(memory);
    capacity_ = next;
    return true;
  }
  bool remember(const char* id, time_t modified) {
    for (size_t index = 0; index < count_; ++index) if (strcmp(entries_[index].id, id) == 0) {
      entries_[index].modified = modified;
      return true;
    }
    if (!reserve(count_ + 1)) return false;
    memcpy(entries_[count_].id, id, 65);
    entries_[count_++].modified = modified;
    return true;
  }
  SpriteAssets::Metrics& metrics_;
};


struct SpriteAssets::State {
  struct Slot {
    String url;
    uint16_t pixels[LOGO_PIXEL_COUNT] = {};
    uint8_t mask[LOGO_PIXEL_COUNT] = {};
    bool valid = false, pinned = false;
  };
  Slot* slots = nullptr;
  uint8_t count = 0;
  SemaphoreHandle_t mutex = nullptr;
  bool mounted = false;
  LittleSpriteStore store;
  mini_sprite::Cache cache;
  explicit State(Metrics& metrics) : store(metrics), cache(store, spriteHash, SPRITE_FLASH_LIMIT) {}
  Slot* find(const String& key) {
    for (uint8_t i = 0; i < count; ++i) if (slots[i].valid && slots[i].url == key) return &slots[i];
    return nullptr;
  }
};

SpriteAssets::SpriteAssets(NetworkWorker& transport, NetworkGate& gate, const char* backend) : transport_(transport), gate_(gate), backend_(backend) {}

bool SpriteAssets::begin() {
  if (state_) return ready();
  state_ = new (std::nothrow) State(metrics_);
  if (!state_) return false;
  const size_t bytes = sizeof(State::Slot) * RUNTIME_LOGO_SLOTS;
  void* memory = psramFound() ? heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) : nullptr;
  state_->count = memory ? RUNTIME_LOGO_SLOTS : min<uint8_t>(RUNTIME_LOGO_SLOTS, 8);
  if (!memory) memory = heap_caps_malloc(sizeof(State::Slot) * state_->count, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (!memory) state_->count = 0;
  state_->slots = static_cast<State::Slot*>(memory);
  for (uint8_t i = 0; i < state_->count; ++i) new (&state_->slots[i]) State::Slot();
  state_->mutex = xSemaphoreCreateMutex();
  state_->mounted = LittleFS.begin(true);
  if (state_->mounted) {
    LittleFS.mkdir("/sprites");
    state_->store.discard();
    state_->mounted = state_->store.begin();
    Serial.printf("Sprite cache %s files=%u\n", state_->mounted ? "ready" : "unavailable", static_cast<unsigned>(state_->store.count()));
  }
  return ready();
}

bool SpriteAssets::ready() const { return state_ && state_->mutex && state_->count; }
uint8_t SpriteAssets::slotCount() const { return state_ ? state_->count : 0; }
uint16_t SpriteAssets::residentCount() {
  if (!ready()) return 0;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  uint16_t count = 0;
  for (uint8_t i = 0; i < state_->count; ++i) count += state_->slots[i].valid;
  xSemaphoreGive(state_->mutex);
  return count;
}
bool SpriteAssets::available(const String& key) {
  if (key.isEmpty()) return true;
  if (!ready()) return false;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  const bool found = state_->find(key) != nullptr;
  xSemaphoreGive(state_->mutex);
  return found;
}
bool SpriteAssets::pinCached(const String& key) {
  if (!ready()) return false;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  auto* slot = state_->find(key);
  if (slot) slot->pinned = true;
  xSemaphoreGive(state_->mutex);
  return slot != nullptr;
}
void SpriteAssets::pinWindow(const String* keys, uint8_t count) {
  if (!ready()) return;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  mini_sprite::pinResidentWindow(state_->slots, state_->count, keys, count);
  xSemaphoreGive(state_->mutex);
}

bool SpriteAssets::loadCached(const String& key, uint8_t* bytes) {
  if (!ready()) return false;
  NetworkLease flash(gate_, 10000, NetworkAccess::DeviceRequests);
  if (!flash) return false;
  mini_sprite::Reference reference;
  if (!mini_sprite::parseReference(key.c_str(), reference) || !state_->mounted) return false;
  const auto loaded = state_->cache.load(reference, bytes);
  if (loaded == mini_sprite::LoadResult::Hit) { ++metrics_.flashHits; return true; }
  if (loaded == mini_sprite::LoadResult::Invalid) ++metrics_.invalidFiles;
  return false;
}

bool SpriteAssets::load(const String& key, uint8_t* bytes) {
  if (!ready()) return false;
  mini_sprite::Reference reference;
  if (!mini_sprite::parseReference(key.c_str(), reference)) return false;
  if (loadCached(key, bytes)) return true;
  AssetTransfer transfer;
  const bool received = transport_.fetchAsset(String(backend_) + "/assets/sprites/" + reference.id + ".mts", bytes, mini_sprite::kBytes, transfer);
  metrics_.heapBeforeTls = transfer.heapBefore;
  metrics_.heapDuringTls = transfer.heapDuring;
  metrics_.largestDuringTls = transfer.largestDuring;
  metrics_.heapAfterTls = ESP.getFreeHeap();
  const bool valid = received && mini_sprite::validate(bytes, mini_sprite::kBytes, reference, spriteHash);
  Serial.printf("Sprite HTTP status=%d valid=%d duration_ms=%lu reused=%d heap=%u\n", transfer.status, valid, static_cast<unsigned long>(transfer.durationMs), transfer.reused, transfer.heapDuring);
  if (!valid) return false;
  ++metrics_.downloads;
  if (transfer.reused) ++metrics_.reusedDownloads;
  if (state_->mounted) {
    NetworkLease flash(gate_, 10000, NetworkAccess::DeviceRequests);
    const uint32_t started = millis();
    if (!flash || !state_->cache.save(reference, bytes)) Serial.println("Sprite flash write failed");
    else Serial.printf("Sprite cache commit duration_ms=%lu files=%u\n", static_cast<unsigned long>(millis() - started), static_cast<unsigned>(state_->store.count()));
  }
  return true;
}

bool SpriteAssets::install(const String& key, const uint8_t* bytes) {
  if (!ready()) return false;
  uint32_t hash = 2166136261u;
  for (size_t i = 0; i < key.length(); ++i) { hash ^= key[i]; hash *= 16777619u; }
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  auto* slot = state_->find(key);
  for (uint8_t i = 0; !slot && i < state_->count; ++i) if (!state_->slots[i].valid) slot = &state_->slots[i];
  for (uint8_t offset = 0; !slot && offset < state_->count; ++offset) {
    auto* candidate = &state_->slots[(hash + offset) % state_->count];
    if (!candidate->pinned) slot = candidate;
  }
  if (slot) {
    slot->valid = false;
    slot->url = key;
    mini_sprite::decodeScaled(bytes, slot->pixels, slot->mask, RUNTIME_LOGO_SIZE);
    slot->valid = slot->pinned = true;
  }
  xSemaphoreGive(state_->mutex);
  return slot != nullptr;
}

bool SpriteAssets::draw(const String& key, int16_t x, int16_t y, Adafruit_GFX& surface) {
  if (!ready()) return false;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  auto* slot = state_->find(key);
  if (slot) for (uint16_t i = 0; i < LOGO_PIXEL_COUNT; ++i) {
    const int16_t tx = x + i % RUNTIME_LOGO_SIZE, ty = y + i / RUNTIME_LOGO_SIZE;
    if (slot->mask[i] && tx >= 0 && tx < 64 && ty >= 0 && ty < 32) surface.drawPixel(tx, ty, slot->pixels[i]);
  }
  xSemaphoreGive(state_->mutex);
  return slot != nullptr;
}
