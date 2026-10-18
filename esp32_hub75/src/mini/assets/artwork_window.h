#pragma once
#include <stddef.h>
#include <stdint.h>
#include "mini_sprite.h"

namespace mini_artwork {
static constexpr size_t Slots = 5;

inline bool same(const mini_sprite::Reference& left, const mini_sprite::Reference& right) {
  return strcmp(left.id, right.id) == 0 && strcmp(left.checksum, right.checksum) == 0;
}

class Window {
 public:
  void plan(const mini_sprite::Reference* references, size_t count) {
    Wanted updated[Slots]{};
    size_t used = 0;
    for (size_t index = 0; index < count && used < Slots; ++index) {
      const auto& reference = references[index];
      if (!mini_sprite::digestValid(reference.id) || !mini_sprite::digestValid(reference.checksum)) continue;
      bool duplicate = false;
      for (size_t prior = 0; prior < used; ++prior) duplicate |= same(updated[prior].reference, reference);
      if (duplicate) continue;
      updated[used].reference = reference;
      for (size_t prior = 0; prior < wantedCount_; ++prior)
        if (same(wanted_[prior].reference, reference)) updated[used].retryAt = wanted_[prior].retryAt;
      ++used;
    }
    const mini_sprite::Reference current = count ? references[0] : mini_sprite::Reference{};
    if (!same(current_, current) && find(current) >= 0) ++hits_;
    current_ = current;
    memcpy(wanted_, updated, sizeof(wanted_));
    wantedCount_ = used;
  }

  int find(const mini_sprite::Reference& reference) const {
    if (!reference.id[0]) return -1;
    for (size_t index = 0; index < Slots; ++index) if (same(loaded_[index], reference)) return static_cast<int>(index);
    return -1;
  }

  bool next(uint32_t now, mini_sprite::Reference& reference) const {
    for (size_t index = 0; index < wantedCount_; ++index) {
      const auto& wanted = wanted_[index];
      if (find(wanted.reference) < 0 && (!wanted.retryAt || static_cast<int32_t>(now - wanted.retryAt) >= 0)) {
        reference = wanted.reference;
        return true;
      }
    }
    return false;
  }

  int finish(const mini_sprite::Reference& reference, bool valid, uint32_t now) {
    int planned = wantedIndex(reference);
    if (planned < 0) return -1;
    if (!valid) { wanted_[planned].retryAt = now + 10000; return -1; }
    wanted_[planned].retryAt = 0;
    const int existing = find(reference);
    if (existing >= 0) return existing;
    for (size_t index = 0; index < Slots; ++index) {
      if (!loaded_[index].id[0] || wantedIndex(loaded_[index]) < 0) {
        loaded_[index] = reference;
        return static_cast<int>(index);
      }
    }
    return -1;
  }

  size_t resident() const {
    size_t count = 0;
    for (const auto& reference : loaded_) count += reference.id[0] != 0;
    return count;
  }
  size_t planned() const { return wantedCount_; }
  uint32_t hits() const { return hits_; }

 private:
  struct Wanted { mini_sprite::Reference reference; uint32_t retryAt = 0; };
  Wanted wanted_[Slots]{};
  mini_sprite::Reference loaded_[Slots], current_;
  size_t wantedCount_ = 0;
  uint32_t hits_ = 0;
  int wantedIndex(const mini_sprite::Reference& reference) const {
    if (!reference.id[0]) return -1;
    for (size_t index = 0; index < wantedCount_; ++index)
      if (same(wanted_[index].reference, reference)) return static_cast<int>(index);
    return -1;
  }
};
}  // namespace mini_artwork
