#pragma once

#include <cstddef>
#include <cstdint>

namespace mini_sprite {

template <typename Text>
bool plannedLogo(const Text& key, const Text* keys, size_t count) {
  for (size_t index = 0; index < count; ++index) if (keys[index] == key) return true;
  return false;
}

template <typename Slot, typename Text>
void pinResidentWindow(Slot* slots, size_t slotCount, const Text* keys, size_t keyCount) {
  for (size_t index = 0; index < slotCount; ++index)
    slots[index].pinned = slots[index].valid && plannedLogo(slots[index].url, keys, keyCount);
}

template <typename Text>
bool acceptLogoResult(uint32_t requestedGeneration, uint32_t currentGeneration,
                      const Text& key, const Text* keys, size_t count) {
  return requestedGeneration == currentGeneration && plannedLogo(key, keys, count);
}

}  // namespace mini_sprite
