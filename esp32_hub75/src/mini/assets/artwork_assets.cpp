#include "artwork_assets.h"
#include "artwork_window.h"
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
  uint8_t* covers = nullptr;
  uint8_t* transfer = nullptr;
  mini_artwork::Window window;
};

bool ArtworkAssets::begin() {
  if (state_) return state_->mutex && state_->covers && state_->transfer;
  state_ = new (std::nothrow) State();
  if (!state_) return false;
  state_->mutex = xSemaphoreCreateMutex();
  state_->covers = static_cast<uint8_t*>(heap_caps_malloc(mini_artwork::Bytes * (mini_artwork::Slots + 1), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (state_->covers) state_->transfer = state_->covers + mini_artwork::Bytes * mini_artwork::Slots;
  return state_->mutex && state_->covers && state_->transfer;
}

bool ArtworkAssets::request(JsonObjectConst music) {
  if (!state_ || !state_->mutex || !state_->transfer) return false;
  mini_sprite::Reference references[mini_artwork::Slots];
  referenceFor(music["cover_asset"].as<JsonObjectConst>(), references[0]);
  size_t count = 1;
  for (JsonObjectConst asset : music["next_cover_assets"].as<JsonArrayConst>()) {
    if (count == 4) break;
    referenceFor(asset, references[count++]);
  }
  referenceFor(music["last_cover_asset"].as<JsonObjectConst>(), references[count++]);
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  state_->window.plan(references, count);
  mini_sprite::Reference next;
  const bool enqueue = state_->window.next(millis(), next);
  xSemaphoreGive(state_->mutex);
  return enqueue;
}

bool ArtworkAssets::pending() {
  if (!state_ || !state_->mutex) return false;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  mini_sprite::Reference next;
  const bool result = state_->window.next(millis(), next);
  xSemaphoreGive(state_->mutex);
  return result;
}

void ArtworkAssets::loadPending() {
  if (!state_ || !state_->transfer) return;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  mini_sprite::Reference reference;
  if (!state_->window.next(millis(), reference)) { xSemaphoreGive(state_->mutex); return; }
  xSemaphoreGive(state_->mutex);
  AssetTransfer transfer;
  const bool received = transport_.fetchAsset(String(backend_) + "/assets/artwork/" + reference.id + ".mta",
      state_->transfer, mini_artwork::Bytes, transfer);
  const bool valid = received && mini_artwork::validate(state_->transfer, mini_artwork::Bytes, reference, hashArtwork);
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  const int slot = state_->window.finish(reference, valid, millis());
  if (slot >= 0) {
    memcpy(state_->covers + slot * mini_artwork::Bytes, state_->transfer, mini_artwork::Bytes);
    ++downloads_;
  }
  xSemaphoreGive(state_->mutex);
  Serial.printf("Artwork HTTP status=%d valid=%d duration_ms=%lu reused=%d\n", transfer.status, valid,
      static_cast<unsigned long>(transfer.durationMs), transfer.reused);
}

bool ArtworkAssets::draw(JsonObjectConst asset, Adafruit_GFX& surface) {
  mini_sprite::Reference reference;
  if (!state_ || !state_->covers || !state_->mutex || !referenceFor(asset, reference)) return false;
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  const int slot = state_->window.find(reference);
  if (slot >= 0) for (size_t y = 0; y < 32; ++y) for (size_t x = 0; x < 32; ++x)
    surface.drawPixel(x, y, mini_sprite::little16(state_->covers + slot * mini_artwork::Bytes + mini_artwork::Header + (y * 32 + x) * 2));
  xSemaphoreGive(state_->mutex);
  return slot >= 0;
}

ArtworkAssets::Metrics ArtworkAssets::metrics() {
  if (!state_ || !state_->mutex) return {};
  xSemaphoreTake(state_->mutex, portMAX_DELAY);
  Metrics result;
  result.resident = state_->window.resident();
  result.planned = state_->window.planned();
  result.hits = state_->window.hits();
  xSemaphoreGive(state_->mutex);
  return result;
}
