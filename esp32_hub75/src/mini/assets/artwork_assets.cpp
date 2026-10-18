#include "artwork_assets.h"
#include "../runtime/network.h"
#include <Adafruit_GFX.h>
#include <esp_heap_caps.h>
#include <mbedtls/sha256.h>
#include <new>

namespace {
bool referenceFor(JsonObjectConst asset, mini_sprite::Reference& reference) {
  const char* id = asset["asset_id"] | "";
  const char* checksum = asset["sha256"] | "";
  if (String(asset["state"] | "") != "ready" || (asset["width"] | 0) != 32 || (asset["height"] | 0) != 32 ||
      (asset["length"] | 0) != mini_artwork::Bytes || String(asset["format"] | "") != "rgb565-le" ||
      (asset["pipeline_version"] | 0) != 1 || !mini_sprite::digestValid(id) || !mini_sprite::digestValid(checksum)) return false;
  memcpy(reference.id, id, 65); memcpy(reference.checksum, checksum, 65);
  return true;
}
bool hashArtwork(const uint8_t* bytes, size_t length, uint8_t* digest) {
  return mbedtls_sha256_ret(bytes, length, digest, 0) == 0;
}
}

struct ArtworkAssets::State {
  SemaphoreHandle_t mutex = nullptr;
  uint8_t* current = nullptr;
  uint8_t* transfer = nullptr;
  mini_sprite::Reference desired, loaded;
  bool requested = false, loading = false;
  uint32_t retryAt = 0;
};

bool ArtworkAssets::begin() {
  if (state_) return state_->mutex && state_->current && state_->transfer;
  state_ = new (std::nothrow) State();
  if (!state_) return false;
  state_->mutex = xSemaphoreCreateMutex();
  state_->current = static_cast<uint8_t*>(heap_caps_malloc(mini_artwork::Bytes * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (state_->current) state_->transfer = state_->current + mini_artwork::Bytes;
  return state_->mutex && state_->current && state_->transfer;
}

bool ArtworkAssets::request(JsonObjectConst asset) {
  if (!state_ || !state_->mutex || !state_->transfer) return false;
  mini_sprite::Reference reference;
  const bool valid = referenceFor(asset, reference);
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  const bool changed = strcmp(state_->desired.id, reference.id) != 0 || strcmp(state_->desired.checksum, reference.checksum) != 0;
  if (changed) { state_->desired = reference; state_->retryAt = 0; }
  const bool absent = strcmp(state_->loaded.id, reference.id) != 0 || strcmp(state_->loaded.checksum, reference.checksum) != 0;
  const bool enqueue = valid && absent && !state_->requested && (!state_->loading || changed) &&
      (state_->retryAt == 0 || static_cast<int32_t>(millis() - state_->retryAt) >= 0);
  if (enqueue) state_->requested = true;
  if (!valid) state_->requested = false;
  xSemaphoreGive(state_->mutex);
  return enqueue;
}

bool ArtworkAssets::pending() {
  if (!state_ || !state_->mutex) return false;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  const bool result = state_->requested;
  xSemaphoreGive(state_->mutex);
  return result;
}

void ArtworkAssets::loadPending() {
  if (!state_ || !state_->transfer) return;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  if (!state_->requested) { xSemaphoreGive(state_->mutex); return; }
  const auto reference = state_->desired;
  state_->requested = false;
  state_->loading = true;
  xSemaphoreGive(state_->mutex);
  AssetTransfer transfer;
  const bool received = transport_.fetchAsset(String(backend_) + "/api/v2/assets/mini-artwork/" + reference.id + ".mta",
      state_->transfer, mini_artwork::Bytes, transfer);
  const bool valid = received && mini_artwork::validate(state_->transfer, mini_artwork::Bytes, reference, hashArtwork);
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  state_->loading = false;
  if (!valid && strcmp(state_->desired.id, reference.id) == 0) state_->retryAt = millis() + 10000;
  if (valid && strcmp(state_->desired.id, reference.id) == 0 && strcmp(state_->desired.checksum, reference.checksum) == 0) {
    memcpy(state_->current, state_->transfer, mini_artwork::Bytes);
    state_->loaded = reference;
    state_->retryAt = 0;
    ++downloads_;
  }
  xSemaphoreGive(state_->mutex);
  Serial.printf("Artwork HTTP status=%d valid=%d duration_ms=%lu reused=%d\n", transfer.status, valid,
      static_cast<unsigned long>(transfer.durationMs), transfer.reused);
}

bool ArtworkAssets::draw(JsonObjectConst asset, Adafruit_GFX& surface) {
  mini_sprite::Reference reference;
  if (!state_ || !state_->current || !state_->mutex || !referenceFor(asset, reference)) return false;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  const bool matches = strcmp(state_->loaded.id, reference.id) == 0 && strcmp(state_->loaded.checksum, reference.checksum) == 0;
  if (matches) for (size_t y = 0; y < 32; ++y) for (size_t x = 0; x < 32; ++x)
    surface.drawPixel(x, y, mini_sprite::little16(state_->current + mini_artwork::Header + (y * 32 + x) * 2));
  xSemaphoreGive(state_->mutex);
  return matches;
}
