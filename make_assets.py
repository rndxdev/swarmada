"""
Procedural bitmap-asset generator for Swarmada (space theme).

We draw simple pixel-art with pygame primitives and save them as real .png
files in assets/. Because we author them ourselves there's no licensing /
DMCA concern, and they're reproducible — re-run this to tweak the art:

    python make_assets.py
"""

import math
import os

import pygame

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _surf(size):
    return pygame.Surface((size, size), pygame.SRCALPHA)


def _icon(size, bg):
    s = _surf(size)
    c = size // 2
    pygame.draw.circle(s, bg, (c, c), c - 1)
    pygame.draw.circle(s, (15, 15, 22), (c, c), c - 1, 2)
    return s


# -- player -----------------------------------------------------------------
def player_ship():
    s = _surf(28)
    body = [(14, 2), (24, 24), (14, 19), (4, 24)]
    pygame.draw.polygon(s, (70, 195, 255), body)
    pygame.draw.polygon(s, (20, 60, 95), body, 2)
    pygame.draw.circle(s, (225, 245, 255), (14, 12), 3)      # cockpit
    pygame.draw.polygon(s, (255, 180, 80), [(11, 19), (17, 19), (14, 27)])  # thruster
    return s


# -- enemies ----------------------------------------------------------------
def enemy_grunt():
    s = _surf(24)
    c = 12
    for a in range(0, 360, 45):                              # spikes
        x = c + int(11 * math.cos(math.radians(a)))
        y = c + int(11 * math.sin(math.radians(a)))
        pygame.draw.line(s, (150, 40, 40), (c, c), (x, y), 2)
    pygame.draw.circle(s, (235, 90, 90), (c, c), 9)
    pygame.draw.circle(s, (120, 30, 30), (c, c), 9, 2)
    pygame.draw.circle(s, (255, 220, 150), (c, c), 4)        # eye
    pygame.draw.circle(s, (60, 10, 10), (c, c), 2)
    return s


def enemy_runner():
    s = _surf(18)
    dart = [(9, 1), (16, 9), (9, 17), (2, 9)]
    pygame.draw.polygon(s, (245, 170, 90), dart)
    pygame.draw.polygon(s, (120, 70, 20), dart, 2)
    pygame.draw.circle(s, (255, 235, 200), (9, 9), 2)
    return s


def enemy_brute():
    s = _surf(40)
    c = 20
    pygame.draw.circle(s, (180, 90, 200), (c, c), 17)
    pygame.draw.circle(s, (130, 55, 150), (14, 15), 4)       # craters
    pygame.draw.circle(s, (130, 55, 150), (27, 23), 5)
    pygame.draw.circle(s, (70, 20, 90), (c, c), 17, 3)
    pygame.draw.circle(s, (255, 230, 120), (15, 18), 3)      # eyes
    pygame.draw.circle(s, (255, 230, 120), (25, 18), 3)
    return s


# -- bosses -----------------------------------------------------------------
def boss_warlord():
    s = _surf(96)
    pink, dark = (255, 90, 170), (120, 20, 70)
    hull = [(48, 6), (86, 80), (48, 64), (10, 80)]
    pygame.draw.polygon(s, pink, hull)
    pygame.draw.polygon(s, dark, hull, 4)
    pygame.draw.polygon(s, pink, [(10, 80), (2, 48), (22, 66)])   # spikes
    pygame.draw.polygon(s, pink, [(86, 80), (94, 48), (74, 66)])
    pygame.draw.circle(s, (255, 220, 240), (48, 40), 9)
    pygame.draw.circle(s, dark, (48, 40), 9, 3)
    return s


def boss_devourer():
    """Deep-sea anglerfish: gaping toothy maw + a glowing lure over its head."""
    s = _surf(68)
    c = 34
    body, dark = (95, 55, 150), (35, 18, 70)
    # Bulbous body (front = up) with a tail fin
    pygame.draw.circle(s, body, (c, 42), 22)
    pygame.draw.polygon(s, body, [(c - 13, 58), (c + 13, 58), (c, 67)])      # tail
    pygame.draw.circle(s, dark, (c, 42), 22, 3)
    # Gaping maw at the front
    pygame.draw.circle(s, dark, (c, 26), 13)
    for tx in range(c - 11, c + 12, 5):                                     # upper teeth
        pygame.draw.polygon(s, (240, 245, 255), [(tx, 17), (tx + 4, 17), (tx + 2, 27)])
    for tx in range(c - 9, c + 10, 5):                                      # lower teeth
        pygame.draw.polygon(s, (240, 245, 255), [(tx, 35), (tx + 4, 35), (tx + 2, 25)])
    # Beady eye
    pygame.draw.circle(s, (255, 230, 120), (c + 9, 42), 5)
    pygame.draw.circle(s, dark, (c + 9, 42), 2)
    # Lure: stalk curving over the head + glowing bulb
    pygame.draw.line(s, (120, 90, 160), (c, 20), (c - 3, 8), 3)
    pygame.draw.circle(s, (255, 250, 190), (c - 3, 6), 6)                   # glow
    pygame.draw.circle(s, (255, 235, 110), (c - 3, 6), 4)                   # bulb
    return s


def boss_colossus():
    s = _surf(220)
    c = 110
    org, dark = (255, 150, 60), (120, 60, 10)
    pygame.draw.circle(s, org, (c, c), 100)
    pygame.draw.circle(s, dark, (c, c), 100, 9)
    for a in range(0, 360, 45):                              # armor nodes
        x = c + int(68 * math.cos(math.radians(a)))
        y = c + int(68 * math.sin(math.radians(a)))
        pygame.draw.circle(s, (205, 110, 40), (x, y), 15)
        pygame.draw.circle(s, dark, (x, y), 15, 3)
    pygame.draw.circle(s, (255, 230, 180), (c, c), 30)       # core
    pygame.draw.circle(s, dark, (c, c), 30, 6)
    return s


def boss_omega():
    s = _surf(400)
    c = 200
    red, dark = (255, 60, 90), (90, 10, 25)
    # Colossus-style armored shell
    pygame.draw.circle(s, (120, 30, 50), (c, c), 188)
    pygame.draw.circle(s, red, (c, c), 178)
    pygame.draw.circle(s, dark, (c, c), 178, 12)
    for a in range(0, 360, 30):                              # armor nodes
        x = c + int(130 * math.cos(math.radians(a)))
        y = c + int(130 * math.sin(math.radians(a)))
        pygame.draw.circle(s, (170, 40, 70), (x, y), 22)
        pygame.draw.circle(s, dark, (x, y), 22, 4)
    # Warlord-style spikes
    for a in range(0, 360, 90):
        x = c + int(178 * math.cos(math.radians(a)))
        y = c + int(178 * math.sin(math.radians(a)))
        x2 = c + int(240 * math.cos(math.radians(a)))
        y2 = c + int(240 * math.sin(math.radians(a)))
        pygame.draw.line(s, (255, 90, 120), (x, y), (x2, y2), 10)
    # Reaper-style cannon up top
    pygame.draw.rect(s, (60, 60, 72), (c - 18, 20, 36, 60), border_radius=4)
    pygame.draw.rect(s, dark, (c - 18, 20, 36, 60), 4, border_radius=4)
    # Devourer-style glowing eye core
    pygame.draw.circle(s, (255, 230, 120), (c, c), 56)
    pygame.draw.circle(s, dark, (c, c), 56, 8)
    pygame.draw.circle(s, (255, 90, 90), (c, c), 26)
    return s


def boss_reaper():
    s = _surf(80)
    tl, dark = (90, 230, 200), (20, 90, 80)
    hull = [(40, 8), (66, 50), (40, 70), (14, 50)]
    pygame.draw.polygon(s, tl, hull)
    pygame.draw.polygon(s, dark, hull, 3)
    pygame.draw.rect(s, (60, 60, 72), (35, 2, 10, 18), border_radius=2)   # cannon
    pygame.draw.rect(s, (20, 20, 26), (35, 2, 10, 18), 2, border_radius=2)
    pygame.draw.circle(s, (255, 120, 120), (40, 46), 6)      # eye
    pygame.draw.circle(s, dark, (40, 46), 6, 2)
    return s


# -- pickups ----------------------------------------------------------------
def pickup_heal():
    s = _icon(18, (90, 210, 130))
    pygame.draw.rect(s, (255, 255, 255), (7, 4, 4, 10))
    pygame.draw.rect(s, (255, 255, 255), (4, 7, 10, 4))
    return s


def pickup_shield():
    s = _icon(18, (90, 160, 235))
    pts = [(9, 3), (14, 5), (14, 10), (9, 15), (4, 10), (4, 5)]
    pygame.draw.polygon(s, (235, 245, 255), pts)
    pygame.draw.polygon(s, (30, 60, 110), pts, 1)
    return s


def pickup_speed():
    s = _icon(18, (245, 210, 90))
    pygame.draw.polygon(s, (90, 65, 10), [(10, 3), (6, 9), (9, 9), (8, 15), (13, 7), (10, 7)])
    return s


def pickup_damage():
    s = _icon(18, (240, 110, 90))
    pygame.draw.polygon(s, (255, 255, 255), [(9, 3), (14, 9), (11, 9), (11, 15), (7, 15), (7, 9), (4, 9)])
    return s


def pickup_magnet():
    s = _icon(18, (190, 140, 245))
    pygame.draw.arc(s, (60, 30, 90), (4, 3, 10, 12), 0, math.pi, 3)
    pygame.draw.rect(s, (225, 60, 60), (4, 9, 3, 5))
    pygame.draw.rect(s, (225, 60, 60), (11, 9, 3, 5))
    return s


def crate():
    s = _surf(26)
    pygame.draw.rect(s, (230, 190, 90), (2, 2, 22, 22), border_radius=3)
    pygame.draw.rect(s, (120, 90, 20), (2, 2, 22, 22), 2, border_radius=3)
    pygame.draw.line(s, (120, 90, 20), (2, 13), (24, 13), 2)
    pygame.draw.line(s, (120, 90, 20), (13, 2), (13, 24), 2)
    pygame.draw.circle(s, (255, 240, 180), (13, 13), 3)
    return s


def gem():
    s = _surf(14)
    pts = [(7, 1), (13, 7), (7, 13), (1, 7)]
    pygame.draw.polygon(s, (130, 255, 170), pts)
    pygame.draw.polygon(s, (20, 90, 50), pts, 1)
    pygame.draw.line(s, (220, 255, 235), (7, 1), (7, 13), 1)
    return s


def icon():
    """App / window / favicon: a dark space roundel, our ship, and a red threat glow."""
    s = _surf(64)
    pygame.draw.rect(s, (16, 18, 28), (2, 2, 60, 60), border_radius=12)
    pygame.draw.rect(s, (60, 70, 110), (2, 2, 60, 60), 2, border_radius=12)
    for (x, y) in [(12, 14), (50, 18), (20, 50), (47, 47), (33, 10)]:
        pygame.draw.circle(s, (185, 195, 225), (x, y), 1)
    glow = _surf(64)
    pygame.draw.circle(glow, (255, 60, 90, 70), (32, 40), 16)
    s.blit(glow, (0, 0))
    body = [(32, 12), (46, 46), (32, 38), (18, 46)]
    pygame.draw.polygon(s, (80, 200, 255), body)
    pygame.draw.polygon(s, (20, 60, 95), body, 2)
    pygame.draw.circle(s, (225, 245, 255), (32, 26), 3)
    pygame.draw.polygon(s, (255, 180, 80), [(28, 38), (36, 38), (32, 50)])
    return s


MAKERS = {
    "icon": icon,
    "player_ship": player_ship,
    "enemy_grunt": enemy_grunt,
    "enemy_runner": enemy_runner,
    "enemy_brute": enemy_brute,
    "boss_warlord": boss_warlord,
    "boss_devourer": boss_devourer,
    "boss_colossus": boss_colossus,
    "boss_reaper": boss_reaper,
    "boss_omega": boss_omega,
    "pickup_heal": pickup_heal,
    "pickup_shield": pickup_shield,
    "pickup_speed": pickup_speed,
    "pickup_damage": pickup_damage,
    "pickup_magnet": pickup_magnet,
    "crate": crate,
    "gem": gem,
}


def generate(out_dir=ASSET_DIR):
    """Create any missing PNGs. Returns the list of asset names."""
    if not pygame.get_init():
        pygame.init()
    os.makedirs(out_dir, exist_ok=True)
    for name, fn in MAKERS.items():
        pygame.image.save(fn(), os.path.join(out_dir, name + ".png"))
    return list(MAKERS)


if __name__ == "__main__":
    generate()
    print(f"Generated {len(MAKERS)} assets in {ASSET_DIR}")
