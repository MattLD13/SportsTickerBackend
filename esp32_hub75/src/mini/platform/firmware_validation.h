#pragma once

#include <cstddef>
#include <cstdint>

namespace mini_firmware {

template <typename Text>
bool safeVersion(const Text& value) {
  if (value.length() == 0 || value.length() >= 64) return false;
  for (size_t index = 0; index < value.length(); ++index) {
    const char c = value[index];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.')) return false;
  }
  return true;
}

template <typename Text>
bool parseSha256(const Text& value, uint8_t* output) {
  if (value.length() != 64) return false;
  for (size_t index = 0; index < 32; ++index) {
    auto hex = [](char c) -> int {
      if (c >= '0' && c <= '9') return c - '0';
      if (c >= 'a' && c <= 'f') return c - 'a' + 10;
      if (c >= 'A' && c <= 'F') return c - 'A' + 10;
      return -1;
    };
    const int high = hex(value[index * 2]);
    const int low = hex(value[index * 2 + 1]);
    if (high < 0 || low < 0) return false;
    output[index] = static_cast<uint8_t>((high << 4) | low);
  }
  return true;
}

inline bool transferComplete(bool valid, size_t received, size_t expected,
                             const uint8_t* actualHash, const uint8_t* expectedHash) {
  uint8_t difference = 0;
  for (size_t index = 0; index < 32; ++index) difference |= actualHash[index] ^ expectedHash[index];
  return valid && received == expected && difference == 0;
}

enum class BootReceipt { None, Pending, Confirm, Rollback };

template <typename Text>
bool manifestMatches(const Text& requested, const Text& version, const Text& target, const Text& hardware,
                     const Text& url, int64_t size, const char* expectedTarget, const char* expectedHardware,
                     size_t minimumSize, size_t maximumSize) {
  static constexpr char prefix[] = "https://";
  if (url.length() < sizeof(prefix) - 1) return false;
  for (size_t index = 0; index < sizeof(prefix) - 1; ++index)
    if (url[index] != prefix[index]) return false;
  return safeVersion(requested) && version == requested && target == expectedTarget && hardware == expectedHardware &&
         size >= static_cast<int64_t>(minimumSize) && size <= static_cast<int64_t>(maximumSize);
}

template <typename Text>
bool sameReceipt(const Text& version, const Text& command, const Text& currentVersion, const Text& currentCommand) {
  return version == currentVersion && command == currentCommand;
}

template <typename Text>
BootReceipt bootReceipt(const Text& pending, const Text& current, bool displayValidated) {
  return pending.length() == 0 ? BootReceipt::None
       : pending != current ? BootReceipt::Rollback
       : displayValidated ? BootReceipt::Confirm : BootReceipt::Pending;
}

}  // namespace mini_firmware
