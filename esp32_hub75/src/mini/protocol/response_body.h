#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <cstring>

// Own response bytes without the Arduino String growth limit.
class ResponseBody {
 public:
  using Resize = void* (*)(void*, size_t);
  using Release = void (*)(void*);
  explicit ResponseBody(size_t limit = 512 * 1024, Resize resize = std::realloc, Release release = std::free)
      : limit_(limit), resize_(resize), release_(release) {}
  ~ResponseBody() { release_(bytes_); }
  ResponseBody(const ResponseBody&) = delete;
  ResponseBody& operator=(const ResponseBody&) = delete;

  size_t append(const unsigned char* source, size_t count) {
    if (failed_ || count > limit_ - size_) { failed_ = true; return 0; }
    if (size_ + count > capacity_) {
      const size_t capacity = std::min(limit_, std::max(size_ + count, std::max(size_t(4096), capacity_ * 2)));
      void* next = resize_(bytes_, capacity);
      if (!next) { failed_ = true; return 0; }
      bytes_ = static_cast<char*>(next);
      capacity_ = capacity;
    }
    if (count) std::memcpy(bytes_ + size_, source, count);
    size_ += count;
    return count;
  }
  const char* data() const { return bytes_; }
  size_t size() const { return size_; }
  bool failed() const { return failed_; }

 private:
  char* bytes_ = nullptr;
  size_t size_ = 0, capacity_ = 0, limit_;
  Resize resize_;
  Release release_;
  bool failed_ = false;
};
