#pragma once

#include <cstddef>
#include "transfer_deadline.h"

// Bound all stream operations, including HTTP loops that wait for body bytes indefinitely.
template <typename Transport, uint32_t (*Now)()>
class DeadlineClient : public Transport {
 public:
  DeadlineClient() { deadline_.start(Now(), TransferDeadline::DefaultBudgetMs); }
  void setTransferBudget(uint32_t milliseconds) { deadline_.start(Now(), milliseconds); timedOut_ = false; }
  bool deadlineExpired() const { return timedOut_; }
  uint8_t connected() override { return expire() ? 0 : Transport::connected(); }
  int available() override { return expire() ? 0 : Transport::available(); }
  int read() override { return expire() ? -1 : Transport::read(); }
  int read(uint8_t* bytes, size_t count) override { return expire() ? -1 : Transport::read(bytes, count); }
  size_t write(uint8_t value) override { return write(&value, 1); }
  size_t write(const uint8_t* bytes, size_t count) override { return expire() ? 0 : Transport::write(bytes, count); }

 private:
  bool expire() {
    if (!timedOut_ && deadline_.expired(Now())) { timedOut_ = true; this->stop(); }
    return timedOut_;
  }
  TransferDeadline deadline_;
  bool timedOut_ = false;
};
