#include "dns_answer.h"
#include <cassert>
#include <iostream>

int main() {
  const std::string host = "ticker.mattdicks.org";
  JsonDocument response;
  assert(!deserializeJson(response, R"({"Status":0,"Question":[{"name":"ticker.mattdicks.org.","type":1}],"Answer":[{"type":5,"TTL":30,"data":"alias.example"},{"type":1,"TTL":300,"data":"104.21.20.25"}]})"));
  auto answer = readDnsAnswer(response.as<JsonObjectConst>(), host);
  assert(answer.valid && answer.ttlSeconds == 30);
  assert(answer.address[0] == 104 && answer.address[1] == 21 && answer.address[2] == 20 && answer.address[3] == 25);
  response["Status"] = 3;
  assert(!readDnsAnswer(response.as<JsonObjectConst>(), host).valid);
  response["Status"] = 0;
  response["TC"] = true;
  assert(!readDnsAnswer(response.as<JsonObjectConst>(), host).valid);
  response["TC"] = false;
  assert(!readDnsAnswer(response.as<JsonObjectConst>(), "other.example").valid);
  for (const char* value : {"999.1.2.3", "1.2.3", "1.2.3.4.5", "1.2.-3.4", "1.2.3.4text", "0.0.0.0"}) {
    response["Answer"][1]["data"] = value;
    assert(!readDnsAnswer(response.as<JsonObjectConst>(), host).valid);
  }
  response["Answer"][1]["data"] = "104.21.20.25";
  response["Answer"][0]["TTL"] = 0;
  answer = readDnsAnswer(response.as<JsonObjectConst>(), host);
  assert(answer.valid && answer.ttlSeconds == 0);
  assert(!dnsCacheFresh(1000, 0, 1000));
  assert(dnsCacheFresh(1000, 30000, 30999));
  assert(!dnsCacheFresh(1000, 30000, 31000));
  assert(dnsCacheFresh(0xfffff000u, 30000, 0x10u));
  assert(!dnsCacheFresh(0xfffff000u, 30000, 0x8000u));
  response["Answer"][0]["TTL"] = -1;
  assert(!readDnsAnswer(response.as<JsonObjectConst>(), host).valid);
  std::cout << "Mini HTTPS DNS answers, strict IPv4 parsing, TTL, and clock rollover passed\n";
}
