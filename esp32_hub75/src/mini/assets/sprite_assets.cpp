#include "sprite_assets.h"
#include "mini_sprite.h"
#include "logo_residency.h"
#include "../platform/config.h"
#include "../platform/tls.h"
#include "../platform/http_diagnostics.h"
#include <Adafruit_GFX.h>
#include <LittleFS.h>
#include <esp_heap_caps.h>
#include <new>

static bool spriteHash(const uint8_t* bytes, size_t length, uint8_t* output) {
  const auto* algorithm = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  return algorithm && mbedtls_md(algorithm, bytes, length, output) == 0;
}

class LittleSpriteStore : public mini_sprite::Store {
 public:
  explicit LittleSpriteStore(SpriteAssets::Metrics& metrics) : metrics_(metrics) {}
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
    ++metrics_.evictions;
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
 private:
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

SpriteAssets::SpriteAssets(NetworkGate& gate, const char* backend) : gate_(gate), backend_(backend) {}

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
    Serial.printf("Sprite cache ready files=%u\n", static_cast<unsigned>(state_->store.count()));
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

static bool downloadSprite(NetworkGate& gate, const char* backend, SpriteAssets::Metrics& metrics_, const mini_sprite::Reference& reference, uint8_t* body) {
  if (WiFi.status() != WL_CONNECTED) return false;
  NetworkLease lease(gate, 12000);
  if (!lease) return false;
  bool success = false;
  metrics_.heapBeforeTls = ESP.getFreeHeap();
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
    if (http.begin(client, String(backend) + "/api/v2/assets/mini-sports/" + reference.id + ".mts")) {
      const int status = http.GET();
      metrics_.heapDuringTls = ESP.getFreeHeap();
      metrics_.largestDuringTls = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
      if (status == HTTP_CODE_OK && http.getSize() == static_cast<int>(mini_sprite::kBytes)) {
        const size_t received = http.getStreamPtr()->readBytes(body, mini_sprite::kBytes);
        success = mini_sprite::validate(body, received, reference, spriteHash);
      }
      logSecureHttpError("Sprite", status, client);
      Serial.printf("Sprite HTTP status=%d length=%d valid=%d heap_before=%u heap_during=%u largest=%u\n", status, http.getSize(), success, metrics_.heapBeforeTls, metrics_.heapDuringTls, metrics_.largestDuringTls);
      http.end();
    }
  }
  metrics_.heapAfterTls = ESP.getFreeHeap();
  if (success) ++metrics_.downloads;
  return success;
}


bool SpriteAssets::load(const String& key, uint8_t* bytes) {
  if (!ready()) return false;
  mini_sprite::Reference reference;
  if (!mini_sprite::parseReference(key.c_str(), reference)) return false;
  const auto loaded = state_->mounted ? state_->cache.load(reference, bytes) : mini_sprite::LoadResult::Miss;
  if (loaded == mini_sprite::LoadResult::Hit) {
    ++metrics_.flashHits;
  } else {
    if (loaded == mini_sprite::LoadResult::Invalid) ++metrics_.invalidFiles;
    if (!downloadSprite(gate_, backend_, metrics_, reference, bytes)) return false;
    if (state_->mounted && !state_->cache.save(reference, bytes)) Serial.println("Sprite flash write failed");
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
