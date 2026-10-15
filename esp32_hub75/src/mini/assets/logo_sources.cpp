#include "logo_sources.h"
#include "mini_sprite.h"

String miniSpriteToken(JsonObjectConst game, const char* field) {
  const JsonObjectConst asset = game[field].as<JsonObjectConst>();
  const String state = asset["state"] | "unavailable";
  if (state == "pending") return "sprite-pending";
  if (state != "ready" || (asset["length"] | 0) != mini_sprite::kBytes ||
      (asset["width"] | 0) != mini_sprite::kSize || (asset["height"] | 0) != mini_sprite::kSize ||
      (asset["pipeline_version"] | 0) != 1 || String(asset["format"] | "") != "rgb565-le-mask-lsb") return "";
  const char* id = asset["asset_id"] | "";
  const char* checksum = asset["sha256"] | "";
  if (!mini_sprite::digestValid(id) || !mini_sprite::digestValid(checksum)) return "";
  return String(mini_sprite::kPrefix) + id + ":" + checksum;
}
