#include "logo_residency.h"
#include <cassert>
#include <iostream>
#include <string>
#include <vector>

struct Logo {
  std::string url;
  bool valid = false, pinned = false;
};

int main() {
  size_t checks = 0;
  for (size_t capacity : {8u, 32u}) {
    for (size_t games : {15u, 20u, 50u}) {
      std::vector<Logo> slots(capacity);
      const size_t window = capacity / 2;
      auto keysFor = [&](size_t page) {
        std::vector<std::string> keys;
        for (size_t offset = 0; offset < std::min(games, window); ++offset)
          for (size_t side = 0; side < 2; ++side)
            keys.push_back(std::to_string(((page + offset) % games) * 2 + side));
        return keys;
      };
      auto initial = keysFor(0);
      for (size_t index = 0; index < initial.size(); ++index) slots[index] = {initial[index], true, true};
      for (size_t page = 1; page <= games * 3; ++page) {
        const auto keys = keysFor(page);
        mini_sprite::pinResidentWindow(slots.data(), slots.size(), keys.data(), keys.size());
        // The previous window already contains both logos for the next game.
        for (size_t side = 0; side < 2; ++side) {
          bool ready = false;
          for (const auto& slot : slots) ready |= slot.valid && slot.url == keys[side] && slot.pinned;
          assert(ready);
          ++checks;
        }
        for (const auto& key : keys) {
          bool resident = false;
          for (const auto& slot : slots) resident |= slot.valid && slot.url == key;
          if (resident) continue;
          bool loaded = false;
          for (auto& slot : slots) {
            if (slot.pinned) continue;
            slot = {key, true, true};
            loaded = true;
            break;
          }
          assert(loaded);
        }
        assert(mini_sprite::acceptLogoResult(7, 7, keys[0], keys.data(), keys.size()));
        assert(!mini_sprite::acceptLogoResult(6, 7, keys[0], keys.data(), keys.size()));
        assert(!mini_sprite::acceptLogoResult(7, 7, std::string("obsolete"), keys.data(), keys.size()));
      }
    }
  }
  std::cout << "Mini logo window: " << checks << " next-game logo checks passed at 15, 20, and 50 games\n";
}
