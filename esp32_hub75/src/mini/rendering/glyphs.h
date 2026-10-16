#pragma once

#include <cctype>
#include "ui_generated.h"

namespace ticker_ui {

inline int glyphIndex(char ch) {
  const unsigned char value = static_cast<unsigned char>(ch);
  const int upper = std::toupper(value);
  return upper >= 32 && upper <= 126 ? upper - 32 : 0;
}

}  // namespace ticker_ui
