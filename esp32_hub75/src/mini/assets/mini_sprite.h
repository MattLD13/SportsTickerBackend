#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace mini_sprite {

static constexpr size_t kSize = 18;
static constexpr size_t kPixels = kSize * kSize;
static constexpr size_t kHeader = 16;
static constexpr size_t kMask = (kPixels + 7) / 8;
static constexpr size_t kBytes = kHeader + kPixels * 2 + kMask;
static constexpr char kPrefix[] = "sprite1:";

using Hash = bool (*)(const uint8_t*, size_t, uint8_t*);

struct Reference {
  char id[65] = {};
  char checksum[65] = {};
};

inline int hexValue(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  return -1;
}

inline bool digestValid(const char* value) {
  if (value == nullptr || strlen(value) != 64) return false;
  for (size_t index = 0; index < 64; ++index) {
    if (hexValue(value[index]) < 0) return false;
  }
  return true;
}

inline bool parseReference(const char* token, Reference& reference) {
  const size_t prefix = sizeof(kPrefix) - 1;
  if (token == nullptr || strlen(token) != prefix + 129 || strncmp(token, kPrefix, prefix) != 0 || token[prefix + 64] != ':') return false;
  memcpy(reference.id, token + prefix, 64);
  memcpy(reference.checksum, token + prefix + 65, 64);
  reference.id[64] = reference.checksum[64] = '\0';
  return digestValid(reference.id) && digestValid(reference.checksum);
}

inline uint16_t little16(const uint8_t* bytes) {
  return static_cast<uint16_t>(bytes[0]) | static_cast<uint16_t>(bytes[1]) << 8;
}

inline bool validate(const uint8_t* bytes, size_t length, const Reference& reference, Hash hash) {
  if (length != kBytes || !digestValid(reference.id) || !digestValid(reference.checksum) || hash == nullptr) return false;
  if (memcmp(bytes, "MTS1", 4) != 0 || bytes[4] != 1 || bytes[5] != 1 || bytes[6] != kSize || bytes[7] != kSize || bytes[8] != 1 || bytes[9] != 1) return false;
  if (little16(bytes + 10) != kPixels * 2 || little16(bytes + 12) != kMask || little16(bytes + 14) != 0 || (bytes[length - 1] & 0xf0) != 0) return false;
  uint8_t actual[32] = {};
  if (!hash(bytes, length, actual)) return false;
  uint8_t difference = 0;
  for (size_t index = 0; index < 32; ++index) {
    const uint8_t expected = static_cast<uint8_t>((hexValue(reference.checksum[index * 2]) << 4) | hexValue(reference.checksum[index * 2 + 1]));
    difference |= expected ^ actual[index];
  }
  return difference == 0;
}

inline void decodeScaled(const uint8_t* bytes, uint16_t* pixels, uint8_t* mask, size_t targetSize) {
  if (targetSize == 0 || targetSize > kSize) return;
  for (size_t y = 0; y < targetSize; ++y) {
    for (size_t x = 0; x < targetSize; ++x) {
      const size_t sourceY = (2 * y + 1) * kSize / (2 * targetSize);
      const size_t sourceX = (2 * x + 1) * kSize / (2 * targetSize);
      const size_t source = sourceY * kSize + sourceX;
      const size_t target = y * targetSize + x;
      pixels[target] = little16(bytes + kHeader + source * 2);
      mask[target] = (bytes[kHeader + kPixels * 2 + source / 8] >> (source % 8)) & 1;
    }
  }
}

inline void decode(const uint8_t* bytes, uint16_t* pixels, uint8_t* mask) {
  decodeScaled(bytes, pixels, mask, kSize);
}

class Store {
 public:
  virtual ~Store() = default;
  virtual size_t read(const char* id, uint8_t* bytes, size_t capacity, bool staged = false) = 0;
  virtual bool stage(const uint8_t* bytes, size_t length) = 0;
  virtual bool commit(const char* id) = 0;
  virtual void discard() = 0;
  virtual bool erase(const char* id) = 0;
  virtual size_t count() = 0;
  virtual bool oldest(char* id, const char* protectedId) = 0;
};

enum class LoadResult { Hit, Miss, Invalid };

class Cache {
 public:
  Cache(Store& store, Hash hash, size_t limit) : store_(store), hash_(hash), limit_(limit) {}

  LoadResult load(const Reference& reference, uint8_t* bytes) {
    if (!digestValid(reference.id) || !digestValid(reference.checksum)) return LoadResult::Invalid;
    const size_t length = store_.read(reference.id, bytes, kBytes);
    if (length == 0) return LoadResult::Miss;
    if (validate(bytes, length, reference, hash_)) return LoadResult::Hit;
    store_.erase(reference.id);
    return LoadResult::Invalid;
  }

  bool save(const Reference& reference, const uint8_t* bytes) {
    if (limit_ == 0 || !validate(bytes, kBytes, reference, hash_)) return false;
    uint8_t checked[kBytes];
    if (!store_.stage(bytes, kBytes) || store_.read(reference.id, checked, sizeof(checked), true) != kBytes || !validate(checked, sizeof(checked), reference, hash_) || !store_.commit(reference.id)) {
      store_.discard();
      return false;
    }
    while (store_.count() > limit_) {
      char id[65] = {};
      if (!store_.oldest(id, reference.id)) return false;
      if (!store_.erase(id)) return false;
    }
    return true;
  }

 private:
  Store& store_;
  Hash hash_;
  size_t limit_;
};

}  // namespace mini_sprite
