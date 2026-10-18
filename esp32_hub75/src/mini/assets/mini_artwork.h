#pragma once
#include "mini_sprite.h"

namespace mini_artwork {
static constexpr size_t Size = 32, Header = 16, Bytes = Header + Size * Size * 2;

inline bool validate(const uint8_t* bytes, size_t length, const mini_sprite::Reference& reference, mini_sprite::Hash hash) {
  if (!bytes || length != Bytes || !hash || !mini_sprite::digestValid(reference.id) || !mini_sprite::digestValid(reference.checksum)) return false;
  if (memcmp(bytes, "MTA1", 4) != 0 || bytes[4] != 1 || bytes[5] != 1 || bytes[6] != Size || bytes[7] != Size) return false;
  if (mini_sprite::little16(bytes + 8) != Size * Size * 2) return false;
  for (size_t i = 10; i < Header; ++i) if (bytes[i] != 0) return false;
  uint8_t digest[32] = {};
  if (!hash(bytes, length, digest)) return false;
  uint8_t difference = 0;
  for (size_t i = 0; i < 32; ++i)
    difference |= digest[i] ^ ((mini_sprite::hexValue(reference.checksum[i * 2]) << 4) | mini_sprite::hexValue(reference.checksum[i * 2 + 1]));
  return difference == 0;
}
}  // namespace mini_artwork
