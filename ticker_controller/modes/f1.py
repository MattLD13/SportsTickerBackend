"""Formula 1 display mode built on the IndyCar racing layout."""

from PIL import Image, ImageDraw


class F1Mixin:
    def _f1_as_indycar_game(self, game):
        mapped = dict(game or {})
        f1 = dict(mapped.get('f1') or {})
        mapped['indycar'] = f1
        return mapped

    def draw_f1_scroll_card(self, game):
        return self.draw_indycar_scroll_card(self._f1_as_indycar_game(game))

    def draw_f1_full(self, game):
        return self.draw_indycar_full(self._f1_as_indycar_game(game))

    def _draw_f1_generated_car(self, card, x, y, w, h, primary, secondary):
        if w <= 8 or h <= 4:
            return
        overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        body_y = max(1, h // 2 - 2)
        d.rectangle([3, body_y, w - 7, body_y + 3], fill=primary)
        d.polygon([(w - 18, body_y - 2), (w - 8, body_y), (w - 18, body_y + 3)], fill=primary)
        d.rectangle([w - 7, body_y + 1, w - 2, body_y + 2], fill=secondary)
        d.rectangle([10, body_y - 2, 21, body_y - 1], fill=secondary)
        wheel = (18, 18, 22, 255)
        rim = (160, 160, 170, 255)
        for cx in (12, w - 15):
            d.ellipse([cx - 3, h - 6, cx + 3, h], fill=wheel)
            d.point((cx, h - 3), fill=rim)
        card.alpha_composite(overlay, (x, y))
