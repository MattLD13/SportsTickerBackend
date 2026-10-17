#pragma once

#include <cstdint>

class TransferDeadline {
 public:
  static constexpr uint32_t DefaultBudgetMs = 20000;
  void start(uint32_t now, uint32_t budget) { started_ = now; budget_ = budget; }
  bool expired(uint32_t now) const { return now - started_ >= budget_; }

 private:
  uint32_t started_ = 0, budget_ = DefaultBudgetMs;
};
