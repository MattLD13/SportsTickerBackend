#include "transfer_deadline.h"
#include "deadline_client.h"
#include <cassert>
#include <iostream>

uint32_t clockMs = 0;
uint32_t testClock() { return clockMs; }
struct StalledTransport {
  bool open = true;
  unsigned stops = 0;
  virtual ~StalledTransport() = default;
  virtual uint8_t connected() { return open; }
  virtual int available() { return 0; }
  virtual int read() { return -1; }
  virtual int read(uint8_t*, size_t) { return -1; }
  virtual size_t write(uint8_t) { return 1; }
  virtual size_t write(const uint8_t*, size_t count) { return count; }
  virtual void stop() { open = false; ++stops; }
};

int main() {
  TransferDeadline deadline;
  deadline.start(1000, 20000);
  for (uint32_t now = 1000; now < 21000; ++now) assert(!deadline.expired(now));
  assert(deadline.expired(21000));
  assert(deadline.expired(300000));
  deadline.start(0xfffffff0u, 20000);
  assert(!deadline.expired(0xfffffff0u + 19999u));
  assert(deadline.expired(0xfffffff0u + 20000u));
  deadline.start(50, 300000);
  assert(!deadline.expired(300049));
  assert(deadline.expired(300050));
  clockMs = 0;
  DeadlineClient<StalledTransport, testClock> client;
  StalledTransport& stream = client;
  while (stream.connected()) {
    assert(stream.available() == 0);
    clockMs += 1;
    assert(clockMs <= 20000);
  }
  assert(client.deadlineExpired() && client.stops == 1);
  uint8_t byte = 0;
  assert(stream.read() == -1 && stream.read(&byte, 1) == -1);
  assert(stream.write(&byte, 1) == 0 && stream.write(byte) == 0);
  assert(client.stops == 1);
  std::cout << "TLS transfer deadlines bound stalled reads and retain the OTA budget across timer rollover\n";
}
