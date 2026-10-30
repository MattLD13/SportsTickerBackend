#include "station_retry.h"
#include <cassert>
#include <iostream>

int main() {
  StationRetry retry;
  retry.configure(100);
  assert(retry.due(100));
  retry.started(100);
  for (uint32_t time = 101; time < 15100; ++time) {
    retry.observe(false, time);
    assert(!retry.due(time));
  }
  retry.observe(false, 15100);
  assert(!retry.due(16099));
  assert(retry.due(16100));
  retry.started(16100);
  retry.observe(true, 16500);
  assert(retry.state() == StationRetry::State::Online);
  assert(!retry.due(100000));
  retry.observe(false, 100001);
  assert(retry.due(100001));
  retry.started(100001);
  retry.observe(true, 100500);
  retry.observe(false, 101000);
  assert(retry.due(101000));
  retry.started(101000);
  uint32_t now = 101000;
  for (unsigned attempt = 0; attempt < 200; ++attempt) {
    now += 15000;
    retry.observe(false, now);
    assert(!retry.due(now));
    now += 30000;
    assert(retry.due(now));
    retry.started(now);
  }
  retry.configure(0xfffffff0u);
  assert(retry.due(0xfffffff0u));
  retry.started(0xfffffff0u);
  retry.observe(false, 0xfffffff0u + 15000u);
  assert(!retry.due(0xfffffff0u + 15000u));
  assert(retry.due(0xfffffff0u + 16000u));
  std::cout << "Station retries preserve association time, recover after loss, retry indefinitely, and handle timer rollover\n";
}
