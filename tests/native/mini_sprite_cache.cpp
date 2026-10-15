// Check the firmware codec and cache state machine against Python wire fixtures.
#include "mini_sprite.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstring>
#include <dlfcn.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using DigestFunction = unsigned char* (*)(const unsigned char*, size_t, unsigned char*);
DigestFunction digestFunction = nullptr;

bool sha256(const uint8_t* bytes, size_t length, uint8_t* output) {
  return digestFunction(bytes, length, output) != nullptr;
}

class NativeStore : public mini_sprite::Store {
 public:
  explicit NativeStore(fs::path root) : root_(root) { fs::create_directories(root_); }
  bool failStage = false;
  bool failCommit = false;
  fs::path path(const char* id) { return root_ / (std::string(id) + ".mts"); }
  fs::path temporary() { return root_ / ".write.tmp"; }
  size_t read(const char* id, uint8_t* bytes, size_t capacity, bool staged = false) override {
    const auto selected = staged ? temporary() : path(id);
    if (!fs::exists(selected)) return 0;
    const auto length = fs::file_size(selected);
    if (length > capacity) return length;
    std::ifstream input(selected, std::ios::binary);
    input.read(reinterpret_cast<char*>(bytes), length);
    return input.gcount();
  }
  bool stage(const uint8_t* bytes, size_t length) override {
    std::ofstream output(temporary(), std::ios::binary);
    output.write(reinterpret_cast<const char*>(bytes), failStage ? length / 2 : length);
    output.close();
    return !failStage && output.good();
  }
  bool commit(const char* id) override {
    if (failCommit) return false;
    fs::rename(temporary(), path(id));
    return true;
  }
  void discard() override { fs::remove(temporary()); }
  bool erase(const char* id) override { return fs::remove(path(id)); }
  size_t count() override {
    size_t total = 0;
    for (const auto& entry : fs::directory_iterator(root_)) total += entry.path().extension() == ".mts";
    return total;
  }
  bool oldest(char* id, const char* protectedId) override {
    std::vector<fs::path> paths;
    for (const auto& entry : fs::directory_iterator(root_)) {
      if (entry.path().extension() == ".mts" && entry.path().stem() != protectedId) paths.push_back(entry.path());
    }
    if (paths.empty()) return false;
    std::sort(paths.begin(), paths.end(), [](const fs::path& a, const fs::path& b) {
      const auto left = fs::last_write_time(a), right = fs::last_write_time(b);
      return left == right ? a.filename() < b.filename() : left < right;
    });
    std::strcpy(id, paths[0].stem().string().c_str());
    return true;
  }
 private:
  fs::path root_;
};

std::vector<uint8_t> bytes(const fs::path& path) {
  std::ifstream input(path, std::ios::binary);
  return std::vector<uint8_t>(std::istreambuf_iterator<char>(input), {});
}

int main(int argc, char** argv) {
  assert(argc == 3);
  void* crypto = dlopen("libcrypto.so.3", RTLD_NOW);
  if (!crypto) crypto = dlopen("libcrypto.so.1.1", RTLD_NOW);
  assert(crypto != nullptr);
  digestFunction = reinterpret_cast<DigestFunction>(dlsym(crypto, "SHA256"));
  assert(digestFunction != nullptr);
  uint8_t known[32] = {};
  assert(sha256(reinterpret_cast<const uint8_t*>("abc"), 3, known));
  assert(known[0] == 0xba && known[31] == 0xad);

  const fs::path vectors = argv[1];
  NativeStore store(argv[2]);
  mini_sprite::Cache cache(store, sha256, 2);
  std::ifstream manifest(vectors / "manifest.txt");
  std::string id, checksum;
  size_t total = 0;
  while (manifest >> id >> checksum) {
    mini_sprite::Reference reference;
    assert(mini_sprite::parseReference(("sprite1:" + id + ":" + checksum).c_str(), reference));
    const auto wire = bytes(vectors / (id + ".mts"));
    assert(mini_sprite::validate(wire.data(), wire.size(), reference, sha256));
    std::array<uint16_t, mini_sprite::kPixels> pixels;
    std::array<uint8_t, mini_sprite::kPixels> mask;
    mini_sprite::decode(wire.data(), pixels.data(), mask.data());
    const auto expectedPixels = bytes(vectors / (id + ".pixels"));
    const auto expectedMask = bytes(vectors / (id + ".mask"));
    for (size_t index = 0; index < mini_sprite::kPixels; ++index) {
      assert(pixels[index] == mini_sprite::little16(expectedPixels.data() + index * 2));
      assert(mask[index] == expectedMask[index]);
    }
    auto damaged = wire;
    damaged[100] ^= 1;
    assert(!mini_sprite::validate(damaged.data(), damaged.size(), reference, sha256));
    assert(!mini_sprite::validate(wire.data(), wire.size() - 1, reference, sha256));
    assert(cache.save(reference, wire.data()));
    assert(store.count() <= 2);
    mini_sprite::Cache restarted(store, sha256, 2);
    std::array<uint8_t, mini_sprite::kBytes> loaded;
    assert(restarted.load(reference, loaded.data()) == mini_sprite::LoadResult::Hit);
    assert(std::equal(wire.begin(), wire.end(), loaded.begin()));
    for (bool failWrite : {true, false}) {
      store.failStage = failWrite;
      store.failCommit = !failWrite;
      assert(!cache.save(reference, wire.data()));
      assert(!fs::exists(store.temporary()));
      assert(restarted.load(reference, loaded.data()) == mini_sprite::LoadResult::Hit);
    }
    store.failStage = store.failCommit = false;
    std::ofstream corrupt(store.path(reference.id), std::ios::binary);
    corrupt.write(reinterpret_cast<const char*>(damaged.data()), damaged.size());
    corrupt.close();
    assert(restarted.load(reference, loaded.data()) == mini_sprite::LoadResult::Invalid);
    assert(restarted.load(reference, loaded.data()) == mini_sprite::LoadResult::Miss);
    assert(cache.save(reference, wire.data()));
    ++total;
  }
  assert(total == 3 && store.count() == 2);
  mini_sprite::Reference invalid;
  assert(!mini_sprite::parseReference("sprite1:../../bad:123", invalid));
  std::cout << "PASS: 3 Python vectors, all pixels, masks, restart reuse, corruption, interrupted writes, and eviction\n";
  dlclose(crypto);
}
