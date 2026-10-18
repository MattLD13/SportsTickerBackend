#include <cassert>
#include <cstdio>
#include <artwork_window.h>

mini_sprite::Reference reference(int value) {
  mini_sprite::Reference result;
  std::snprintf(result.id, sizeof(result.id), "%064x", value);
  memcpy(result.checksum, result.id, sizeof(result.id));
  return result;
}

int main() {
  mini_artwork::Window cache;
  mini_sprite::Reference plan[5] = {reference(1), reference(2), reference(3), reference(4), reference(5)}, next;
  cache.plan(plan, 5);
  for (int index = 0; index < 5; ++index) {
    assert(cache.next(100, next) && mini_artwork::same(next, plan[index]));
    assert(cache.finish(next, true, 100) >= 0);
  }
  assert(!cache.next(100, next) && cache.resident() == 5);
  mini_sprite::Reference advanced[5] = {reference(2), reference(3), reference(4), reference(6), reference(1)};
  cache.plan(advanced, 5);
  assert(cache.hits() == 1 && cache.find(reference(2)) >= 0 && cache.find(reference(1)) >= 0);
  assert(cache.next(200, next) && mini_artwork::same(next, reference(6)));
  assert(cache.finish(next, false, 200) == -1);
  cache.plan(advanced, 5);
  assert(!cache.next(201, next) && cache.hits() == 1);
  assert(cache.next(10200, next));
  assert(cache.finish(next, true, 10200) >= 0 && cache.find(reference(5)) == -1);
  assert(cache.resident() == 5 && !cache.next(10200, next));
  mini_sprite::Reference reversed[5] = {reference(1), reference(2), reference(3), reference(4), reference(4)};
  cache.plan(reversed, 5);
  assert(cache.hits() == 2 && cache.planned() == 4 && !cache.next(10300, next));
  mini_sprite::Reference skipped[1] = {reference(7)};
  cache.plan(skipped, 1);
  assert(cache.next(10400, next));
  cache.plan(reversed, 5);
  assert(cache.finish(next, true, 10500) == -1 && cache.find(reference(7)) == -1);
  mini_sprite::Reference changed = reference(1);
  memcpy(changed.checksum, reference(8).checksum, sizeof(changed.checksum));
  assert(cache.find(changed) == -1);
  cache.plan(nullptr, 0);
  assert(!cache.next(10600, next) && cache.resident() == 5);
  std::puts("Artwork priority, five covers, forward/back reuse, retries, stale transfers, and bounded eviction pass");
}
