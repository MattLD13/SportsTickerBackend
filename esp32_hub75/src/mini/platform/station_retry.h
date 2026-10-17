#pragma once

#include <cstdint>

class StationRetry {
 public:
  enum class State { Waiting, Associating, Online };
  void configure(uint32_t now) { state_ = State::Waiting; due_ = now; failures_ = 0; }
  void observe(bool connected, uint32_t now) {
    if (connected) { state_ = State::Online; failures_ = 0; return; }
    if (state_ == State::Online) { state_ = State::Waiting; due_ = now; }
    if (state_ == State::Associating && now - started_ >= 15000) {
      state_ = State::Waiting;
      const uint32_t delay = failures_ < 5 ? 1000u << failures_ : 30000u;
      if (failures_ < 5) ++failures_;
      due_ = now + delay;
    }
  }
  bool due(uint32_t now) const { return state_ == State::Waiting && static_cast<int32_t>(now - due_) >= 0; }
  void started(uint32_t now) { state_ = State::Associating; started_ = now; }
  State state() const { return state_; }

 private:
  State state_ = State::Waiting;
  uint32_t due_ = 0, started_ = 0;
  uint8_t failures_ = 0;
};
