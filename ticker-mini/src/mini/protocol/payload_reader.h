#pragma once

#include <algorithm>
#include <cstddef>
#include <cstring>

class PayloadReader {
 public:
  PayloadReader(const char* bytes, size_t size) : bytes_(bytes), size_(size) {}
  int read() { return position_ < size_ ? static_cast<unsigned char>(bytes_[position_++]) : -1; }
  size_t readBytes(char* target, size_t count) {
    count = std::min(count, size_ - position_);
    std::memcpy(target, bytes_ + position_, count);
    position_ += count;
    return count;
  }
  size_t position() const { return position_; }
 private:
  const char* bytes_;
  size_t size_;
  size_t position_ = 0;
};
