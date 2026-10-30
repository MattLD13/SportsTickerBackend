"""Draw the playing surfaces behind the pinned sports layouts: field, pitch, diamond, rink, and court.

Each surface keeps both panel edges dark, so the logos and scores at the edges stay readable.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 384, 32
CHALK = (255, 255, 255)

# Football: the end zones and the playing field follow the proportions of a real field.
END_ZONE = WIDTH * (30 / 360)
PLAY = WIDTH * (300 / 360)
HASH_TOP, HASH_BOTTOM = HEIGHT * (70.75 / 160), HEIGHT * (89.25 / 160)

# The pitch, the rink, and the court fade linearly to black at each edge.
FADE_SOLID, FADE_RAMP = 45, 80
# The diamond uses a smooth fade, and the outfield stripes start only after the fade ends.
SCRIM_SOLID, SCRIM_RAMP, SCRIM_PEAK = 8, 92, 252
STRIPE_EASE = 40

GRASS, GRASS_STRIPE = (8, 28, 4), (11, 34, 6)
DIRT = (153, 111, 49)
BASE_CHALK = (232, 232, 232)
RINK_RED, RINK_BLUE = (204, 26, 26), (34, 85, 204)


def edge_fade(image: Image.Image) -> None:
    """Composite a linear black fade over both edges."""
    scrim = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(scrim)
    span = FADE_SOLID + FADE_RAMP
    for x in range(span):
        alpha = 250 if x < FADE_SOLID else max(0, int(250 * (span - x) / FADE_RAMP))
        draw.line([(x, 0), (x, image.height)], fill=(0, 0, 0, alpha))
        draw.line([(image.width - 1 - x, 0), (image.width - 1 - x, image.height)], fill=(0, 0, 0, alpha))
    image.alpha_composite(scrim)


def smooth_scrim(image: Image.Image) -> None:
    """Composite a smoothstep black fade over both edges.

    Smoothstep is flat at both ends. The solid core joins the ramp without a visible edge, and
    the ramp ends in the field without a band.
    """
    scrim = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(scrim)
    for x in range(SCRIM_SOLID + SCRIM_RAMP):
        t = (x - SCRIM_SOLID) / SCRIM_RAMP
        alpha = SCRIM_PEAK if x < SCRIM_SOLID else int(round(SCRIM_PEAK * (1 - t * t * (3 - 2 * t))))
        draw.line([(x, 0), (x, image.height)], fill=(0, 0, 0, alpha))
        draw.line([(image.width - 1 - x, 0), (image.width - 1 - x, image.height)], fill=(0, 0, 0, alpha))
    image.alpha_composite(scrim)


def football_field(left_end_zone, right_end_zone) -> Image.Image:
    """Draw the striped field with yard lines, hash marks, and the two team end zones."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    for index in range(10):
        x = END_ZONE + index * PLAY / 10
        draw.rectangle([x, 0, x + PLAY / 10, HEIGHT], fill=(22, 52, 18) if index % 2 == 0 else (27, 64, 24))
    draw.rectangle([0, 0, END_ZONE, HEIGHT], fill=left_end_zone)
    draw.rectangle([WIDTH - END_ZONE, 0, WIDTH, HEIGHT], fill=right_end_zone)
    for x in (END_ZONE, WIDTH - END_ZONE):
        draw.line([(x, 0), (x, HEIGHT)], fill=(*CHALK, 230))
    for index in range(11):
        x = END_ZONE + index * PLAY / 10
        draw.line([(x, 0), (x, HEIGHT)], fill=(*CHALK, 115 if index == 5 else 64))
    for yard in range(1, 100):
        x = END_ZONE + yard / 100 * PLAY
        five = yard % 5 == 0
        length = HEIGHT * (0.042 if five else 0.022)
        for y in (HASH_TOP, HASH_BOTTOM):
            draw.line([(x, y - length), (x, y + length)], fill=(*CHALK, 128 if five else 66))
    return image


def soccer_pitch() -> Image.Image:
    """Draw the striped pitch with the touchline, the halfway line, the center circle, and the goal areas."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    for index in range(8):
        draw.rectangle([int(index * WIDTH / 8), 0, int((index + 1) * WIDTH / 8), HEIGHT],
                       fill=(22, 104, 40) if index % 2 == 0 else (18, 96, 36))
    line = (245, 245, 245)
    draw.rectangle([1, 1, WIDTH - 2, HEIGHT - 2], outline=(*line, 210), width=1)
    draw.line([(WIDTH // 2, 0), (WIDTH // 2, HEIGHT)], fill=(*line, 180), width=1)
    draw.ellipse([WIDTH // 2 - 13, HEIGHT // 2 - 13, WIDTH // 2 + 13, HEIGHT // 2 + 13], outline=(*line, 180), width=1)
    draw.rectangle([1, 8, 10, HEIGHT - 8], fill=(*line, 28))
    draw.rectangle([WIDTH - 11, 8, WIDTH - 2, HEIGHT - 8], fill=(*line, 28))
    edge_fade(image)
    return image


def baseball_diamond(first: bool, second: bool, third: bool) -> Image.Image:
    """Draw the outfield, the infield, the base paths, the mound, and the bases.

    The diamond center and its radius are whole pixels, so each base path is a clean 45-degree run.
    The grass keeps blue near zero and red above blue, so it shows olive on the panel. The dirt
    keeps some blue, so it shows brown and not yellow.
    """
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    cx, radius, cy, bag = WIDTH // 2, int(round(HEIGHT * 0.41)), int(round(HEIGHT * 0.53)), max(2, int(round(HEIGHT * 0.13)))
    home, first_base, second_base, third_base = (cx, cy + radius), (cx + radius, cy), (cx, cy - radius), (cx - radius, cy)

    def diamond(x: int, y: int, size: int, color) -> None:
        for row in range(-size, size + 1):
            draw.line([(x - (size - abs(row)), y + row), (x + size - abs(row), y + row)], fill=color)

    # The mown stripes ease in after the scrim ends, so the fade to black stays even.
    for x in range(WIDTH):
        t = max(0.0, min(1.0, (min(x, WIDTH - 1 - x) - SCRIM_SOLID - SCRIM_RAMP) / STRIPE_EASE))
        striped = t > 0 and int(x * 10 / WIDTH) % 2
        color = tuple(int(round(a + (b - a) * t)) for a, b in zip(GRASS, GRASS_STRIPE)) if striped else GRASS
        draw.line([(x, 0), (x, HEIGHT)], fill=color)
    # The infield dirt rises from below the panel and holds all three bags.
    draw.ellipse([cx - radius - 7, cy + 3 - radius - 8, cx + radius + 7, cy + 3 + radius + 8], fill=DIRT)
    diamond(cx, cy, radius - 4, GRASS)
    for start, end in ((home, first_base), (first_base, second_base), (second_base, third_base), (third_base, home)):
        step_x, step_y = (1 if end[0] > start[0] else -1), (1 if end[1] > start[1] else -1)
        for index in range(abs(end[0] - start[0]) + 1):
            draw.point((start[0] + index * step_x, start[1] + index * step_y), fill=BASE_CHALK)
    draw.ellipse([cx - 3, cy - 2, cx + 3, cy + 2], fill=DIRT)
    draw.line([(cx - 1, cy), (cx + 1, cy)], fill=BASE_CHALK)
    draw.ellipse([home[0] - 5, home[1] - 4, home[0] + 5, home[1] + 4], fill=DIRT)
    for point, occupied in ((third_base, third), (first_base, first), (second_base, second)):
        diamond(*point, bag, (0, 0, 0))
        diamond(*point, bag - 1, (255, 204, 0) if occupied else CHALK)
    # Home plate points down to the backstop.
    draw.rectangle([home[0] - 2, home[1] - 2, home[0] + 2, home[1] - 1], fill=CHALK)
    draw.line([(home[0] - 1, home[1]), (home[0] + 1, home[1])], fill=CHALK)
    draw.point((home[0], home[1] + 1), fill=CHALK)
    return image


def hockey_rink() -> Image.Image:
    """Draw the ice with the blue lines, the red lines, the face-off spots and circles, the creases, and the nets."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    blue_left, blue_right = WIDTH * 0.28, WIDTH * 0.72
    goal_left, goal_right = WIDTH * 0.085, WIDTH * 0.915
    draw.rectangle([0, 0, WIDTH, HEIGHT], fill=(205, 228, 248))
    draw.rectangle([0, 0, blue_left, HEIGHT], fill=(196, 219, 244))
    draw.rectangle([blue_right, 0, WIDTH, HEIGHT], fill=(196, 219, 244))
    for x in (blue_left, blue_right):
        draw.rectangle([x - 1, 0, x + 1.5, HEIGHT], fill=RINK_BLUE)
    inset = max(4, int(WIDTH * 0.02))
    for x in (blue_left + inset, blue_right - inset):
        for y in (HEIGHT * 0.28, HEIGHT * 0.72):
            draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(*RINK_RED, 210), outline=(140, 12, 12, 220))
    dash = int(HEIGHT / 6 * 0.7)
    for index in range(6):
        top = int(index * HEIGHT / 6)
        draw.rectangle([WIDTH / 2 - 0.6, top, WIDTH / 2 + 0.6, top + dash], fill=RINK_RED)
    for x in (goal_left, goal_right):
        draw.line([(x, 0), (x, HEIGHT)], fill=RINK_RED, width=1)
    circle = HEIGHT * 0.40
    draw.ellipse([WIDTH / 2 - circle, HEIGHT / 2 - circle, WIDTH / 2 + circle, HEIGHT / 2 + circle], outline=(*RINK_RED, 128), width=1)
    draw.ellipse([WIDTH / 2 - 2, HEIGHT / 2 - 2, WIDTH / 2 + 2, HEIGHT / 2 + 2], fill=(*RINK_RED, 179))
    circle, spot = HEIGHT * 0.25, 2.5
    for x in (blue_left * 0.5, blue_right + (WIDTH - blue_right) * 0.5):
        for y in (HEIGHT * 0.28, HEIGHT * 0.72):
            draw.ellipse([x - spot, y - spot, x + spot, y + spot], fill=(*RINK_RED, 179))
            draw.ellipse([x - circle, y - circle, x + circle, y + circle], outline=(*RINK_RED, 89), width=1)
    crease = HEIGHT * 0.32
    for x, start, end in ((goal_left, 270, 90), (goal_right, 90, 270)):
        draw.arc([x - crease, HEIGHT / 2 - crease, x + crease, HEIGHT / 2 + crease], start=start, end=end, fill=(68, 136, 238), width=1)
    net = int(HEIGHT * 0.28)
    top = (HEIGHT - net) // 2
    draw.rectangle([goal_left, top, goal_left + 4, top + net], fill=(221, 221, 221), outline=(153, 153, 153))
    draw.rectangle([goal_right - 4, top, goal_right, top + net], fill=(221, 221, 221), outline=(153, 153, 153))
    draw.rounded_rectangle([0, 0, WIDTH - 1, HEIGHT - 1], radius=int(HEIGHT * 0.45), outline=(122, 173, 206), width=1)
    edge_fade(image)
    return image


def basketball_court() -> Image.Image:
    """Draw the floor with the boundary, the half-court line, the lanes, the free-throw circles, the arcs, and the baskets."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    lane_width, lane_height = WIDTH * 0.18, HEIGHT * 0.62
    lane_top, arc = (HEIGHT - lane_height) / 2, HEIGHT * 0.54
    draw.rectangle([0, 0, WIDTH, HEIGHT], fill=(200, 120, 58))
    draw.rectangle([1, 1, WIDTH - 2, HEIGHT - 2], outline=(*CHALK, 128))
    draw.line([(WIDTH / 2, 0), (WIDTH / 2, HEIGHT)], fill=(*CHALK, 115))
    circle = HEIGHT * 0.33
    draw.ellipse([WIDTH / 2 - circle, HEIGHT / 2 - circle, WIDTH / 2 + circle, HEIGHT / 2 + circle], outline=(*CHALK, 97))
    draw.rectangle([0, lane_top, lane_width, lane_top + lane_height], fill=(160, 80, 32), outline=(*CHALK, 140))
    draw.rectangle([WIDTH - lane_width, lane_top, WIDTH, lane_top + lane_height], fill=(160, 80, 32), outline=(*CHALK, 140))
    circle = lane_height * 0.26
    for x in (lane_width, WIDTH - lane_width):
        draw.ellipse([x - circle, HEIGHT / 2 - circle, x + circle, HEIGHT / 2 + circle], outline=(*CHALK, 97))
    draw.arc([0 - arc, lane_top - 4, arc, lane_top + lane_height + 4], start=270, end=90, fill=(*CHALK, 97))
    draw.arc([WIDTH - arc, lane_top - 4, WIDTH + arc, lane_top + lane_height + 4], start=90, end=270, fill=(*CHALK, 97))
    post = lane_width * 0.45
    for x in (post, WIDTH - post):
        draw.line([(x, HEIGHT * 0.33), (x, HEIGHT * 0.67)], fill=(220, 220, 220, 165), width=1)
    edge_fade(image)
    return image
