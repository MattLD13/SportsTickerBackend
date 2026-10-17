#include "firmware_validation.h"
#include <cassert>
#include <iostream>
#include <string>

int main() {
  using namespace mini_firmware;
  assert(safeVersion(std::string("mini-1.3.12")));
  for (const char* value : {"", "../image", "version with spaces", "v?test", "v\n"})
    assert(!safeVersion(std::string(value)));
  assert(safeVersion(std::string(63, 'a')));
  assert(!safeVersion(std::string(64, 'a')));
  uint8_t expected[32] = {}, actual[32] = {};
  assert(parseSha256(std::string(64, 'A'), expected));
  assert(expected[0] == 0xaa && expected[31] == 0xaa);
  assert(parseSha256(std::string(64, 'a'), actual));
  assert(transferComplete(true, 1280000, 1280000, actual, expected));
  assert(!transferComplete(false, 1280000, 1280000, actual, expected));
  assert(!transferComplete(true, 1279999, 1280000, actual, expected));
  assert(!transferComplete(true, 1280001, 1280000, actual, expected));
  for (size_t byte = 0; byte < 32; ++byte) {
    actual[byte] ^= 1;
    assert(!transferComplete(true, 1280000, 1280000, actual, expected));
    actual[byte] ^= 1;
  }
  assert(!parseSha256(std::string(63, 'a'), actual));
  assert(!parseSha256(std::string(65, 'a'), actual));
  for (size_t digit = 0; digit < 64; ++digit) {
    std::string hash(64, 'a');
    hash[digit] = 'g';
    assert(!parseSha256(hash, actual));
  }
  assert(bootReceipt(std::string("mini-1.3.12"), std::string("mini-1.3.12"), false) == BootReceipt::Pending);
  assert(bootReceipt(std::string(), std::string("mini-1.3.12"), false) == BootReceipt::None);
  assert(bootReceipt(std::string("mini-1.3.12"), std::string("mini-1.3.12"), true) == BootReceipt::Confirm);
  assert(bootReceipt(std::string("mini-1.3.12"), std::string("mini-1.3.11"), false) == BootReceipt::Rollback);
  const std::string version = "mini-1.3.12", target = "esp32s3", hardware = "matrixportal_s3";
  const std::string url = "https://ticker.example/firmware.bin";
  auto manifest = [&](const std::string& requested, const std::string& actualVersion, const std::string& actualTarget,
                      const std::string& actualHardware, const std::string& actualUrl, int64_t size) {
    return manifestMatches(requested, actualVersion, actualTarget, actualHardware, actualUrl, size,
                           target.c_str(), hardware.c_str(), 65536, 2093056);
  };
  assert(manifest(version, version, target, hardware, url, 65536));
  assert(manifest(version, version, target, hardware, url, 2093056));
  assert(!manifest(version, version, target, hardware, url, 65535));
  assert(!manifest(version, version, target, hardware, url, 2093057));
  assert(!manifest(version, version, target, hardware, url, -1));
  assert(!manifest(version, "mini-old", target, hardware, url, 1280000));
  assert(!manifest(version, version, "esp32c5", hardware, url, 1280000));
  assert(!manifest(version, version, target, "other", url, 1280000));
  assert(!manifest(version, version, target, hardware, "http://ticker.example/image", 1280000));
  assert(!manifest(version, version, target, hardware, "https:", 1280000));
  assert(sameReceipt(version, std::string("command-2"), version, std::string("command-2")));
  assert(!sameReceipt(version, std::string("command-1"), version, std::string("command-2")));
  assert(!sameReceipt(std::string("mini-old"), std::string("command-2"), version, std::string("command-2")));
  std::cout << "Mini firmware version, checksum, interrupted transfer, and boot receipt checks passed\n";
}
