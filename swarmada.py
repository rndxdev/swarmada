"""
Swarmada — a tiny alien-swarm survival game.

You're the last Vanguard pilot. Fly an ENDLESS slice of space (WASD / arrows),
hold the line against escalating waves of the alien Tide, collect XP, level up,
grab item clusters (including new weapons that auto-equip), and outlast the
bosses — up to the mega OMEGA.

Run:  python swarmada.py
"""

import array
import asyncio
import json
import math
import os
import random
import sys
import time

import pygame
from pygame import Vector2          # NOT `from pygame.math` — pygbag tries to pip-install that

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 960, 600
CENTER = Vector2(WIDTH / 2, HEIGHT / 2)
FPS = 60
TITLE = "Swarmada"

SPAWN_MIN, SPAWN_MAX = 640, 780     # enemies appear just off-screen
CULL_DIST2 = 1200 ** 2              # despawn enemies you've left far behind
MAX_SPEED = 7.0                    # hard cap on player move speed (base is 3.5)

# Deterministic simulation (for replay-verified leaderboards). The sim advances
# in fixed steps; given the same seed + the same per-step input masks it always
# produces the same score, so a server can re-run a replay to validate it.
SIM_DT = 1.0 / 60.0
SIM_VERSION = 4                    # bump whenever gameplay math/balance changes
IN_UP, IN_DOWN, IN_LEFT, IN_RIGHT = 1, 2, 4, 8
IN_C1, IN_C2, IN_C3 = 16, 32, 64

# Colors
BG = (16, 18, 28)
WHITE = (235, 238, 245)
DIM = (120, 128, 150)
PLAYER_COL = (80, 200, 255)
PROJ_COL = (255, 240, 140)
GEM_COL = (130, 255, 170)
HP_COL = (235, 80, 90)
SHIELD_COL = (120, 200, 255)
XP_COL = (90, 170, 255)
GOLD = (255, 210, 90)

ENEMY_TYPES = {
    # name:      (radius, base_hp, speed,  dmg, xp,  color)
    "grunt":     (12,      10,     1.5,    8,   1,   (235, 110, 110)),
    "runner":    (9,       6,      2.6,    6,   1,   (245, 170, 90)),
    "brute":     (20,      40,     0.9,    16,  4,   (200, 90, 200)),
}

# Boss archetypes — cycled (and made tougher) each time one appears.
BOSS_TYPES = [
    {"name": "THE WARLORD",   "color": (255, 80, 160), "radius": 48, "hp": 1.0, "speed": 2.4, "dmg": 1.0, "behavior": "charger", "sprite": "boss_warlord"},
    {"name": "THE DEVOURER",  "color": (150, 90, 255), "radius": 34, "hp": 0.7, "speed": 3.4, "dmg": 0.9, "behavior": "fast",    "sprite": "boss_devourer"},
    {"name": "THE COLOSSUS",  "color": (255, 140, 60), "radius": 110, "hp": 3.2, "speed": 1.2, "dmg": 1.8, "behavior": "tank",    "sprite": "boss_colossus"},
    {"name": "THE REAPER",    "color": (90, 230, 200), "radius": 40, "hp": 1.3, "speed": 2.0, "dmg": 1.0, "behavior": "shooter", "sprite": "boss_reaper"},
]

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
ART = None  # set once assets are loaded; draw code reads sprites from here


class Assets:
    """Loads bitmap PNGs from assets/ once and caches them. Generates them on
    first run, and degrades gracefully (sprite -> None) if a file is missing,
    so the game still runs anywhere even without the art."""

    def __init__(self):
        self.images = {}
        self.names = []

    def ensure(self):
        import make_assets
        self.names = list(make_assets.MAKERS)
        try:
            missing = [n for n in self.names
                       if not os.path.exists(os.path.join(ASSET_DIR, n + ".png"))]
            if missing:
                make_assets.generate(ASSET_DIR)
        except Exception:
            pass            # browser sandbox may block writes; fall back to shape art

    def load_one(self, name):
        path = os.path.join(ASSET_DIR, name + ".png")
        try:
            self.images[name] = pygame.image.load(path).convert_alpha()
        except Exception:
            self.images[name] = None

    def get(self, name):
        return self.images.get(name)


SCORES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scores.json")


def load_scores():
    try:
        with open(SCORES_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_scores(scores):
    try:
        with open(SCORES_FILE, "w") as f:
            json.dump(scores, f, indent=2)
    except OSError:
        pass


SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "savegame.json")
# Optional global leaderboard server (your VPS). Set SWARMADA_SERVER=http://host:port
SERVER_URL = os.environ.get("SWARMADA_SERVER", "").rstrip("/")


def save_game(game):
    """Autosave an in-progress run as its seed + inputs (deterministic resume)."""
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump({"v": SIM_VERSION, "seed": game.seed, "steps": game.replay,
                       "score": int(game.score), "round": game.round}, f)
    except OSError:
        pass


def load_save():
    try:
        with open(SAVE_FILE) as f:
            data = json.load(f)
        if data.get("v") == SIM_VERSION and data.get("steps"):
            return data
    except (OSError, ValueError):
        pass
    return None


def clear_save():
    try:
        os.remove(SAVE_FILE)
    except OSError:
        pass


def blit_sprite(surf, spr, sp, angle=0.0, flash=False):
    """Blit a sprite centered at screen pos sp, optionally rotated / hit-flashed."""
    img = spr
    if flash:
        img = spr.copy()
        img.fill((150, 150, 150, 0), special_flags=pygame.BLEND_RGB_ADD)
    if angle:
        img = pygame.transform.rotate(img, angle)
    surf.blit(img, img.get_rect(center=(sp.x, sp.y)))

SAMPLE_RATE = 44100


# ---------------------------------------------------------------------------
# Audio — every sound is synthesized at runtime. No audio files, so it adds
# nothing to the build and is inherently copyright-free (no DMCA risk).
# ---------------------------------------------------------------------------
class Audio:
    def __init__(self, music=True):
        self.enabled = False
        self.sounds = {}
        self.music = None
        self.music_on = music
        self.sfx_vol = 0.6
        self.music_vol = 0.30
        try:
            pygame.mixer.init()
            pygame.mixer.set_num_channels(24)
            pygame.mixer.set_reserved(1)
            self.music_chan = pygame.mixer.Channel(0)
        except pygame.error:
            return                      # no audio device -> silent, game still runs
        try:
            self._build()
            self.enabled = True
        except Exception:               # e.g. web sandbox can't synth -> stay silent
            self.enabled = False

    def _wave(self, frac, kind):
        if kind == 'sine':
            return math.sin(2 * math.pi * frac)
        if kind == 'square':
            return 1.0 if frac < 0.5 else -1.0
        if kind == 'saw':
            return 2.0 * frac - 1.0
        if kind == 'tri':
            return 2.0 * abs(2.0 * frac - 1.0) - 1.0
        if kind == 'noise':
            return random.uniform(-1.0, 1.0)
        return 0.0

    def _tone(self, freq, dur, kind='sine', vol=0.4, fenv=0.0, attack=0.005):
        """One note; fenv sweeps frequency over the note (e.g. -0.45 = drop)."""
        n = int(SAMPLE_RATE * dur)
        buf = array.array('h')
        amp = int(32767 * vol)
        phase = 0.0
        for i in range(n):
            t = i / SAMPLE_RATE
            f = freq * (1.0 + fenv * (t / dur))
            phase += f / SAMPLE_RATE
            s = self._wave(phase % 1.0, kind)
            a = min(1.0, t / attack) if attack > 0 else 1.0
            d = 1.0 - t / dur
            buf.append(int(max(-1.0, min(1.0, s * a * d)) * amp))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _noise(self, dur, vol=0.3, tone=0.0):
        n = int(SAMPLE_RATE * dur)
        buf = array.array('h')
        amp = int(32767 * vol)
        phase = 0.0
        for i in range(n):
            t = i / SAMPLE_RATE
            s = random.uniform(-1.0, 1.0)
            if tone > 0:
                phase += tone / SAMPLE_RATE
                s = 0.5 * s + 0.5 * math.sin(2 * math.pi * (phase % 1.0))
            d = 1.0 - t / dur
            buf.append(int(max(-1.0, min(1.0, s * d)) * amp))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _seq(self, notes, vol=0.4, kind='sine'):
        """A little arpeggio: list of (freq, dur)."""
        buf = array.array('h')
        amp = int(32767 * vol)
        for freq, dur in notes:
            n = int(SAMPLE_RATE * dur)
            phase = 0.0
            for i in range(n):
                t = i / SAMPLE_RATE
                phase += freq / SAMPLE_RATE
                s = self._wave(phase % 1.0, kind)
                a = min(1.0, t / 0.005)
                d = 1.0 - t / dur
                buf.append(int(max(-1.0, min(1.0, s * a * d)) * amp))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _horror(self, dur=1.9):
        """A terrifying arrival sting: a descending dissonant (tritone) drone
        with detuned sub-bass beating, slow tremolo, and a noise rumble."""
        n = int(SAMPLE_RATE * dur)
        buf = array.array('h')
        amp = 32767
        for i in range(n):
            t = i / SAMPLE_RATE
            prog = t / dur
            f1 = 200.0 * (1.0 - prog) + 45.0        # slow descent into dread
            f2 = f1 * 1.414                          # tritone = dissonance
            trem = 0.7 + 0.3 * math.sin(2 * math.pi * 5.0 * t)
            s = (0.45 * math.sin(2 * math.pi * f1 * t)
                 + 0.32 * math.sin(2 * math.pi * f2 * t)
                 + 0.40 * math.sin(2 * math.pi * 48.0 * t)
                 + 0.25 * math.sin(2 * math.pi * 50.5 * t)     # beats against 48Hz
                 + 0.15 * random.uniform(-1.0, 1.0) * (1.0 - prog))
            env = min(1.0, t / 0.06) * (1.0 - prog * 0.5)
            buf.append(int(max(-1.0, min(1.0, s * trem * env * 0.5)) * amp))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _boom(self, dur=0.55):
        """Deep sub-bass impact for the Omega's slam."""
        n = int(SAMPLE_RATE * dur)
        buf = array.array('h')
        amp = int(32767 * 0.7)
        for i in range(n):
            t = i / SAMPLE_RATE
            prog = t / dur
            f = 130.0 * (1.0 - prog) + 28.0
            s = 0.7 * math.sin(2 * math.pi * f * t) + 0.3 * random.uniform(-1.0, 1.0) * (1.0 - prog)
            env = min(1.0, t / 0.004) * (1.0 - prog)
            buf.append(int(max(-1.0, min(1.0, s * env)) * amp))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _build(self):
        self.sounds = {
            'shoot':       self._tone(680, 0.06, 'square', 0.16, fenv=-0.45),
            'enemy_death': self._noise(0.10, 0.22, tone=180),
            'pickup':      self._tone(560, 0.10, 'sine', 0.35, fenv=0.7),
            'shield':      self._tone(380, 0.18, 'sine', 0.40, fenv=0.5),
            'speed':       self._tone(520, 0.12, 'square', 0.28, fenv=0.8),
            'heal':        self._seq([(523, 0.08), (659, 0.13)], 0.35, 'sine'),
            'magnet':      self._tone(300, 0.18, 'saw', 0.28, fenv=1.2),
            'damage':      self._tone(160, 0.14, 'square', 0.30, fenv=0.3),
            'weapon':      self._seq([(523, 0.07), (659, 0.07), (784, 0.13)], 0.40, 'square'),
            'level_up':    self._seq([(523, 0.09), (659, 0.09), (784, 0.09), (1047, 0.17)], 0.38, 'sine'),
            'boss_spawn':  self._tone(110, 0.60, 'saw', 0.42, fenv=0.08),
            'boss_death':  self._seq([(440, 0.12), (330, 0.12), (220, 0.28)], 0.42, 'saw'),
            'hurt':        self._noise(0.12, 0.30, tone=140),
            'nova':        self._tone(900, 0.25, 'sine', 0.30, fenv=-0.8),
            'wave_clear':  self._seq([(659, 0.10), (880, 0.16)], 0.32, 'sine'),
            'omega':       self._horror(1.9),       # OMEGA arrival — horror-space sting
            'omega_slam':  self._boom(0.55),        # OMEGA ground slam
        }
        try:
            self.music = self._build_music()
            self.music.set_volume(self.music_vol)
            if self.music_on:
                self.music_chan.play(self.music, loops=-1)
        except pygame.error:
            self.music = None

    def _build_music(self):
        """A short looping chiptune: triangle arpeggio over a square bass."""
        roots = [220.0, 174.61, 261.63, 196.0]   # Am - F - C - G
        pattern = [0, 3, 7, 12, 7, 3, 0, 5]       # minor-ish arpeggio steps
        eighth = 0.22
        buf = array.array('h')
        amp = int(32767 * 0.9)
        for root in roots:
            bass_f = root / 2.0
            for step in pattern:
                mel_f = root * (2.0 ** (step / 12.0))
                n = int(SAMPLE_RATE * eighth)
                mp = bp = 0.0
                for i in range(n):
                    t = i / SAMPLE_RATE
                    mp += mel_f / SAMPLE_RATE
                    bp += bass_f / SAMPLE_RATE
                    mel = 2.0 * abs(2.0 * (mp % 1.0) - 1.0) - 1.0
                    bass = 1.0 if (bp % 1.0) < 0.5 else -1.0
                    env = min(1.0, t / 0.01) * (1.0 - 0.5 * t / eighth)
                    v = (mel * 0.45 + bass * 0.28) * env * 0.5
                    buf.append(int(max(-1.0, min(1.0, v)) * amp))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def play(self, name, vol=1.0):
        if not self.enabled:
            return
        snd = self.sounds.get(name)
        if snd is not None:
            snd.set_volume(self.sfx_vol * vol)
            snd.play()

    def toggle_music(self):
        if not self.enabled or self.music is None:
            return
        self.music_on = not self.music_on
        if self.music_on:
            self.music_chan.play(self.music, loops=-1)
        else:
            self.music_chan.stop()

    def set_sfx_vol(self, v):
        self.sfx_vol = max(0.0, min(1.0, round(v, 2)))

    def set_music_vol(self, v):
        self.music_vol = max(0.0, min(1.0, round(v, 2)))
        if self.music is not None:
            self.music.set_volume(self.music_vol)


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------
class Player:
    def __init__(self):
        self.pos = Vector2(0, 0)       # world coordinates (camera follows)
        self.radius = 13
        self.speed = 3.5

        self.max_hp = 100.0
        self.hp = 100.0
        self.max_shield = 40.0         # absorbs damage, regenerates
        self.shield = 40.0
        self.shield_regen = 12.0       # per second
        self.regen_delay = 2.5         # seconds after a hit before regen
        self._since_hit = 99.0

        # Primary "Bolt" weapon stats (improved via upgrades)
        self.damage = 6.0
        self.damage_mult = 1.0         # global multiplier for ALL weapons
        self.fire_cooldown = 0.45
        self.proj_speed = 7.0
        self.proj_count = 1
        self.pierce = 0
        self.bolt_radius = 5
        self.pickup_radius = 22.0       # ~touch range; Magnetism grows the vacuum
        self.hp_regen = 0.0            # HP per second (from upgrades)
        self.xp_mult = 1.0
        self.upgrade_counts = {}       # upgrade id -> times taken (for caps)

        self.weapons = []              # extra auto-weapons

        self.level = 1
        self.xp = 0
        self.xp_to_next = 5

        self._fire_timer = 0.0
        self._hurt_flash = 0.0
        self.angle = 0.0               # facing, for the ship sprite

    def get_weapon(self, cls):
        for w in self.weapons:
            if isinstance(w, cls):
                return w
        return None

    def add_xp(self, amount):
        self.xp += max(1, int(amount * self.xp_mult))
        leveled = False
        while self.xp >= self.xp_to_next:
            self.xp -= self.xp_to_next
            self.level += 1
            self.xp_to_next = int(self.xp_to_next * 1.35) + 2
            leveled = True
        return leveled

    def update(self, dt, mx, my):
        self.speed = min(self.speed, MAX_SPEED)        # cap so upgrades can't make you light-speed
        move = Vector2(mx, my)
        if move.length_squared() > 0:
            self.pos += move.normalize() * self.speed * dt * FPS   # no clamping: endless map
            self.angle = math.degrees(math.atan2(-move.y, move.x)) - 90

        self._fire_timer -= dt
        self._hurt_flash = max(0.0, self._hurt_flash - dt)

        if self.hp_regen > 0 and self.hp < self.max_hp:
            self.hp = min(self.max_hp, self.hp + self.hp_regen * dt)

        # Shield regen after a quiet moment
        self._since_hit += dt
        if self._since_hit >= self.regen_delay and self.shield < self.max_shield:
            self.shield = min(self.max_shield, self.shield + self.shield_regen * dt)

    def try_fire(self, enemies):
        if self._fire_timer > 0 or not enemies:
            return []
        target = min(enemies, key=lambda e: (e.pos - self.pos).length_squared())
        aim = target.pos - self.pos
        if aim.length_squared() == 0:
            aim = Vector2(1, 0)
        aim = aim.normalize()
        base_angle = math.atan2(aim.y, aim.x)

        shots = []
        spread = math.radians(12)
        for i in range(self.proj_count):
            offset = (i - (self.proj_count - 1) / 2) * spread
            ang = base_angle + offset
            vel = Vector2(math.cos(ang), math.sin(ang)) * self.proj_speed
            shots.append(Projectile(self.pos.copy(), vel, self.damage * self.damage_mult, self.pierce,
                                    radius=self.bolt_radius))
        self._fire_timer = self.fire_cooldown
        return shots

    def hurt(self, amount):
        self._since_hit = 0.0
        if self.shield > 0:
            absorbed = min(self.shield, amount)
            self.shield -= absorbed
            amount -= absorbed
        if amount > 0:
            self.hp -= amount
        self._hurt_flash = 0.25

    def draw(self, surf, cam):
        sp = self.pos - cam
        # Vacuum window: only drawn once Magnetism opens it; very transparent fill + thin rim.
        if self.pickup_radius > 30:
            r = int(self.pickup_radius)
            ring = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(ring, (90, 170, 255, 12), (r + 1, r + 1), r)
            pygame.draw.circle(ring, (120, 200, 255, 70), (r + 1, r + 1), r, 1)
            surf.blit(ring, (sp.x - r - 1, sp.y - r - 1))

        spr = ART.get("player_ship") if ART else None
        if spr:
            blit_sprite(surf, spr, sp, angle=self.angle, flash=self._hurt_flash > 0)
        else:
            col = WHITE if self._hurt_flash > 0 else PLAYER_COL
            pygame.draw.circle(surf, col, sp, self.radius)
            pygame.draw.circle(surf, (20, 30, 50), sp, self.radius, 2)
        if self.shield > 0:
            pygame.draw.circle(surf, SHIELD_COL, sp, self.radius + 5, 2)


# ---------------------------------------------------------------------------
# Enemies
# ---------------------------------------------------------------------------
class Enemy:
    def __init__(self, pos, radius, hp, speed, damage, xp, color, is_boss=False, name=""):
        self.pos = pos
        self.radius = radius
        self.max_hp = hp
        self.hp = hp
        self.speed = speed
        self.damage = damage
        self.xp_value = xp
        self.color = color
        self.is_boss = is_boss
        self.name = name
        self.kind = ""
        self.sprite = None
        self.face_angle = 0.0
        self.elite = False
        self.is_omega = False
        self._hit_flash = 0.0
        # Boss behavior state (unused by normal enemies)
        self.behavior = "chase"
        self.atk_t = 0.0
        self.state = "chase"
        self.state_t = 0.0
        self.charge_dir = Vector2(1, 0)

    @classmethod
    def normal(cls, pos, kind, hp_scale, speed_scale):
        radius, base_hp, speed, dmg, xp, color = ENEMY_TYPES[kind]
        e = cls(pos, radius, base_hp * hp_scale, speed * speed_scale, dmg, xp, color)
        e.kind = kind
        e.sprite = "enemy_" + kind
        return e

    @classmethod
    def make_boss(cls, pos, index, rnd):
        spec = BOSS_TYPES[index % len(BOSS_TYPES)]
        cycle = index // len(BOSS_TYPES)                  # 0, 1, 2... tougher each cycle
        hp = (500 + rnd * 450) * spec["hp"] * (1 + cycle * 0.6)
        speed = spec["speed"] + cycle * 0.2
        dmg = (22 + rnd * 2) * spec["dmg"]
        xp = 40 + index * 25
        b = cls(pos, spec["radius"], hp, speed, dmg, xp, spec["color"], is_boss=True, name=spec["name"])
        b.behavior = spec["behavior"]
        b.sprite = spec["sprite"]
        b.atk_t = 2.0
        return b

    @classmethod
    def make_omega(cls, pos, rnd):
        """THE OMEGA — a single mega-boss that combines every boss's tricks:
        5x size, huge HP/defence/damage, and it chases + slams + shoots."""
        hp = 6000 + rnd * 600
        b = cls(pos, 200, hp, 1.9, 60 + rnd, 1000, (255, 60, 90), is_boss=True, name="THE OMEGA")
        b.behavior = "omega"
        b.sprite = "boss_omega"
        b.atk_t = 1.2          # shoot timer
        b.state_t = 4.0        # slam timer
        b.is_omega = True
        return b

    def update(self, dt, player):
        direction = player.pos - self.pos
        if direction.length_squared() > 1:
            self.pos += direction.normalize() * self.speed * dt * FPS
        self._hit_flash = max(0.0, self._hit_flash - dt)

    def hurt(self, amount):
        self.hp -= amount
        self._hit_flash = 0.08

    def draw(self, surf, cam):
        sp = self.pos - cam
        if self.elite:
            pygame.draw.circle(surf, (255, 240, 120), sp, self.radius + 5, 2)
        spr = ART.get(self.sprite) if (ART and self.sprite) else None
        if spr:
            angle = self.face_angle if self.is_boss else 0.0
            blit_sprite(surf, spr, sp, angle=angle, flash=self._hit_flash > 0)
        else:
            col = WHITE if self._hit_flash > 0 else self.color
            pygame.draw.circle(surf, col, sp, self.radius)
            pygame.draw.circle(surf, (10, 12, 20), sp, self.radius, 2)
            if self.is_boss:
                pygame.draw.circle(surf, GOLD, sp, self.radius + 4, 2)
        if not self.is_boss and self.hp < self.max_hp:
            w = self.radius * 2
            frac = max(0.0, self.hp / self.max_hp)
            x = sp.x - self.radius
            y = sp.y - self.radius - 6
            pygame.draw.rect(surf, (40, 40, 50), (x, y, w, 3))
            pygame.draw.rect(surf, HP_COL, (x, y, w * frac, 3))


# ---------------------------------------------------------------------------
# Projectiles / pickups / fx
# ---------------------------------------------------------------------------
class Projectile:
    def __init__(self, pos, vel, damage, pierce, life=1.6, radius=5, color=PROJ_COL):
        self.pos = pos
        self.vel = vel
        self.damage = damage
        self.pierce = pierce
        self.life = life
        self.radius = radius
        self.color = color
        self._hit = set()

    def update(self, dt):
        self.pos += self.vel * dt * FPS
        self.life -= dt

    @property
    def dead(self):
        return self.life <= 0 or self.pierce < 0

    def draw(self, surf, cam):
        pygame.draw.circle(surf, self.color, self.pos - cam, self.radius)


class EnemyBullet:
    """Projectile fired BY a boss, damages the player."""
    def __init__(self, pos, vel, damage, radius=7, color=(255, 90, 90), life=4.0):
        self.pos = pos
        self.vel = vel
        self.damage = damage
        self.radius = radius
        self.color = color
        self.life = life

    def update(self, dt):
        self.pos += self.vel * dt * FPS
        self.life -= dt

    @property
    def dead(self):
        return self.life <= 0

    def draw(self, surf, cam):
        pygame.draw.circle(surf, self.color, self.pos - cam, self.radius)
        pygame.draw.circle(surf, (40, 10, 10), self.pos - cam, self.radius, 1)


class Gem:
    def __init__(self, pos, value):
        self.pos = pos
        self.value = value
        self.radius = 4

    def update(self, dt, player):
        d = player.pos - self.pos
        dist = d.length()
        if dist < player.pickup_radius and dist > 0:
            pull = (1 - dist / player.pickup_radius) * 9 + 1
            self.pos += d.normalize() * pull * dt * FPS
        return dist <= player.radius + self.radius

    def draw(self, surf, cam):
        sp = self.pos - cam
        spr = ART.get("gem") if ART else None
        if spr:
            surf.blit(spr, spr.get_rect(center=(sp.x, sp.y)))
        else:
            pygame.draw.circle(surf, GEM_COL, sp, self.radius)


class Particle:
    def __init__(self, pos, color):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(1.5, 4.0)
        self.pos = Vector2(pos)
        self.vel = Vector2(math.cos(ang), math.sin(ang)) * spd
        self.color = color
        self.life = random.uniform(0.2, 0.45)
        self.max_life = self.life

    def update(self, dt):
        self.pos += self.vel * dt * FPS
        self.vel *= 0.9
        self.life -= dt

    def draw(self, surf, cam):
        if self.life <= 0:
            return
        r = max(1, int(3 * self.life / self.max_life))
        pygame.draw.circle(surf, self.color, self.pos - cam, r)


class Ring:
    """Expanding shockwave / blast visual. `filled` makes it a translucent
    gas pulse with a bright icy rim (used by Frost Nova)."""
    def __init__(self, pos, max_r, color, filled=False, life=0.35):
        self.pos = pos
        self.max_r = max_r
        self.color = color
        self.filled = filled
        self.life = life
        self.max_life = life

    def update(self, dt):
        self.life -= dt

    @property
    def dead(self):
        return self.life <= 0

    def draw(self, surf, cam):
        t = 1 - self.life / self.max_life
        r = int(self.max_r * t)
        if r <= 1:
            return
        fade = 1.0 - t
        size = r * 2 + 8
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        c = (size // 2, size // 2)
        if self.filled:                                   # gas cloud core
            pygame.draw.circle(s, (*self.color, int(75 * fade)), c, r)
            pygame.draw.circle(s, (*self.color, int(55 * fade)), c, int(r * 0.6))
        pygame.draw.circle(s, (*self.color, int(210 * fade)), c, r, 4)   # leading edge
        pygame.draw.circle(s, (235, 245, 255, int(160 * fade)), c, r, 2)  # icy rim highlight
        sp = self.pos - cam
        surf.blit(s, (sp.x - size // 2, sp.y - size // 2))


# ---------------------------------------------------------------------------
# Extra weapons (unlocked via level-up or weapon crates)
# ---------------------------------------------------------------------------
class OrbitWeapon:
    NAME = "Orbit Blades"
    PICKUP_DESC = "Blades that orbit you"
    MAX_LEVEL = 6

    def __init__(self):
        self.level = 1
        self.blades = 2
        self.damage = 5.0
        self.radius = 66.0
        self.blade_r = 9
        self.spin = 2.6
        self.hit_interval = 0.4
        self.angle = 0.0
        self._cd = {}

    def positions(self, player):
        return [player.pos + Vector2(math.cos(self.angle + i * math.tau / self.blades),
                                     math.sin(self.angle + i * math.tau / self.blades)) * self.radius
                for i in range(self.blades)]

    def update(self, dt, game):
        self.angle += self.spin * dt
        for k in list(self._cd):
            self._cd[k] -= dt
            if self._cd[k] <= 0:
                del self._cd[k]
        pts = self.positions(game.player)
        for e in game.enemies:
            if e.hp <= 0 or id(e) in self._cd:
                continue
            for bp in pts:
                rr = (e.radius + self.blade_r) ** 2
                if (e.pos - bp).length_squared() <= rr:
                    e.hurt(self.damage * game.player.damage_mult)
                    self._cd[id(e)] = self.hit_interval
                    break

    def apply_levelup(self):
        self.level += 1
        if self.level % 2 == 0:
            self.blades += 1
        else:
            self.damage *= 1.4
        self.radius += 4

    def next_desc(self):
        return "+1 blade" if (self.level + 1) % 2 == 0 else "+40% blade dmg"

    def draw(self, surf, player, cam):
        for bp in self.positions(player):
            pygame.draw.circle(surf, (210, 230, 255), bp - cam, self.blade_r)
            pygame.draw.circle(surf, (40, 60, 90), bp - cam, self.blade_r, 2)


class ScatterWeapon:
    NAME = "Scatter Shot"
    PICKUP_DESC = "Short-range shotgun burst"
    MAX_LEVEL = 6

    def __init__(self):
        self.level = 1
        self.pellets = 5
        self.damage = 4.0
        self.cooldown = 1.1
        self.spread = math.radians(64)
        self.speed = 8.5
        self.life = 0.32
        self._timer = 0.0

    def update(self, dt, game):
        self._timer -= dt
        if self._timer > 0 or not game.enemies:
            return
        player = game.player
        target = min(game.enemies, key=lambda e: (e.pos - player.pos).length_squared())
        aim = target.pos - player.pos
        if aim.length_squared() == 0:
            aim = Vector2(1, 0)
        base = math.atan2(aim.y, aim.x)
        for i in range(self.pellets):
            t = 0 if self.pellets == 1 else (i / (self.pellets - 1) - 0.5)
            ang = base + t * self.spread
            vel = Vector2(math.cos(ang), math.sin(ang)) * self.speed
            game.projectiles.append(
                Projectile(player.pos.copy(), vel, self.damage * player.damage_mult, 0,
                           life=self.life, radius=4, color=(255, 170, 120)))
        self._timer = self.cooldown

    def apply_levelup(self):
        self.level += 1
        if self.level % 2 == 0:
            self.pellets += 2
        else:
            self.damage *= 1.4
        self.cooldown = max(0.5, self.cooldown * 0.92)

    def next_desc(self):
        return "+2 pellets" if (self.level + 1) % 2 == 0 else "+40% pellet dmg"

    def draw(self, surf, player, cam):
        pass


class NovaWeapon:
    NAME = "Frost Nova"
    PICKUP_DESC = "AoE shockwave pulse"
    MAX_LEVEL = 6

    def __init__(self):
        self.level = 1
        self.damage = 14.0
        self.radius = 120.0
        self.cooldown = 2.4
        self._timer = 0.0

    def update(self, dt, game):
        self._timer -= dt
        if self._timer > 0:
            return
        self._timer = self.cooldown
        center = game.player.pos
        rr = self.radius ** 2
        for e in game.enemies:
            if e.hp > 0 and (e.pos - center).length_squared() <= rr:
                e.hurt(self.damage * game.player.damage_mult)
        if game.cosmetic:
            game.rings.append(Ring(center.copy(), self.radius, (140, 210, 255), filled=True, life=0.5))
            # Icy gas puff (cosmetic-only -> module random, keeps the sim deterministic)
            for _ in range(16):
                a = random.uniform(0, math.tau)
                rr = random.uniform(0, self.radius)
                col = random.choice([(170, 225, 255), (210, 240, 255), (140, 200, 255)])
                game.particles.append(Particle(center + Vector2(math.cos(a), math.sin(a)) * rr, col))
        game.sfx('nova', 0.6)

    def apply_levelup(self):
        self.level += 1
        if self.level % 2 == 0:
            self.radius += 24
        else:
            self.damage *= 1.4
        self.cooldown = max(1.2, self.cooldown * 0.93)

    def next_desc(self):
        return "+range" if (self.level + 1) % 2 == 0 else "+40% nova dmg"

    def draw(self, surf, player, cam):
        pass


WEAPON_REGISTRY = [OrbitWeapon, ScatterWeapon, NovaWeapon]


# ---------------------------------------------------------------------------
# Pickups (item clusters)
# ---------------------------------------------------------------------------
WEAPON_PICKUPS = {"w_orbit": OrbitWeapon, "w_scatter": ScatterWeapon, "w_nova": NovaWeapon}

PICKUP_DEFS = {
    "heal":      {"color": (120, 255, 150), "label": "+", "weight": 3},
    "shield":    {"color": SHIELD_COL,      "label": "S", "weight": 3},
    "speed":     {"color": (255, 230, 120), "label": ">", "weight": 2},
    "magnet":    {"color": (200, 150, 255), "label": "M", "weight": 1},
    "damage":    {"color": (255, 140, 120), "label": "!", "weight": 2},
    "w_orbit":   {"color": GOLD, "label": "O", "weight": 1, "crate": True},
    "w_scatter": {"color": GOLD, "label": "X", "weight": 1, "crate": True},
    "w_nova":    {"color": GOLD, "label": "*", "weight": 1, "crate": True},
}
_PK_KINDS = list(PICKUP_DEFS)
_PK_WEIGHTS = [PICKUP_DEFS[k]["weight"] for k in _PK_KINDS]


class Pickup:
    def __init__(self, pos, kind):
        d = PICKUP_DEFS[kind]
        self.pos = pos
        self.kind = kind
        self.color = d["color"]
        self.label = d["label"]
        self.crate = d.get("crate", False)
        self.radius = 13 if self.crate else 9
        self.sprite = "crate" if self.crate else "pickup_" + kind

    def draw(self, surf, cam, font):
        sp = self.pos - cam
        spr = ART.get(self.sprite) if ART else None
        if spr:
            surf.blit(spr, spr.get_rect(center=(sp.x, sp.y)))
            if self.crate:                       # show which weapon the crate holds
                t = font.render(self.label, True, (70, 50, 10))
                surf.blit(t, (sp.x - t.get_width() // 2, sp.y - t.get_height() // 2))
            return
        if self.crate:
            rect = pygame.Rect(sp.x - self.radius, sp.y - self.radius, self.radius * 2, self.radius * 2)
            pygame.draw.rect(surf, self.color, rect, border_radius=4)
            pygame.draw.rect(surf, (20, 20, 20), rect, 2, border_radius=4)
        else:
            pygame.draw.circle(surf, self.color, sp, self.radius)
            pygame.draw.circle(surf, (20, 20, 20), sp, self.radius, 2)
        t = font.render(self.label, True, (20, 20, 30))
        surf.blit(t, (sp.x - t.get_width() // 2, sp.y - t.get_height() // 2))


# ---------------------------------------------------------------------------
# Upgrades
# ---------------------------------------------------------------------------
def _grant_hp(p, amount):
    p.max_hp += amount
    p.hp = min(p.max_hp, p.hp + amount)


def _grant_shield(p, amount):
    p.max_shield += amount
    p.shield = p.max_shield


def _faster_regen(p):
    p.shield_regen *= 1.5
    p.regen_delay = max(0.8, p.regen_delay * 0.8)


# Each stat upgrade can be taken up to `cap` times; once maxed it stops being
# offered (so late level-ups always show fresh, useful choices).
STAT_UPGRADES = [
    {"id": "power",    "name": "Power Surge",   "desc": "+25% ALL damage",    "cap": 8, "fn": lambda p: setattr(p, "damage_mult", p.damage_mult * 1.25)},
    {"id": "sharp",    "name": "Sharper Shots", "desc": "+40% bolt damage",   "cap": 6, "fn": lambda p: setattr(p, "damage", p.damage * 1.4)},
    {"id": "rapid",    "name": "Rapid Fire",    "desc": "-15% bolt cooldown", "cap": 6, "fn": lambda p: setattr(p, "fire_cooldown", p.fire_cooldown * 0.85)},
    {"id": "multi",    "name": "Multi-Shot",    "desc": "+1 bolt",            "cap": 5, "fn": lambda p: setattr(p, "proj_count", p.proj_count + 1)},
    {"id": "pierce",   "name": "Piercing",      "desc": "+1 bolt pierce",     "cap": 5, "fn": lambda p: setattr(p, "pierce", p.pierce + 1)},
    {"id": "vel",      "name": "Velocity",      "desc": "+20% bolt speed",    "cap": 5, "fn": lambda p: setattr(p, "proj_speed", p.proj_speed * 1.2)},
    {"id": "bigshot",  "name": "Heavy Rounds",  "desc": "+2 bolt size",       "cap": 3, "fn": lambda p: setattr(p, "bolt_radius", p.bolt_radius + 2)},
    {"id": "boots",    "name": "Swift Speed Boost", "desc": "+14% move speed", "cap": 6,
     "avail": lambda p: p.speed < MAX_SPEED - 0.05, "fn": lambda p: setattr(p, "speed", p.speed * 1.14)},
    {"id": "vit",      "name": "Vitality",      "desc": "+25 max HP & heal",  "cap": 6, "fn": lambda p: _grant_hp(p, 25)},
    {"id": "regen",    "name": "Regeneration",  "desc": "+0.6 HP / sec",      "cap": 5, "fn": lambda p: setattr(p, "hp_regen", p.hp_regen + 0.6)},
    {"id": "shield",   "name": "Energy Shield", "desc": "+20 max shield",     "cap": 6, "fn": lambda p: _grant_shield(p, 20)},
    {"id": "recharge", "name": "Fast Recharge", "desc": "+50% shield regen",  "cap": 4, "fn": _faster_regen},
    {"id": "magnet",   "name": "Magnetism",     "desc": "+45 pickup vacuum",  "cap": 6, "fn": lambda p: setattr(p, "pickup_radius", p.pickup_radius + 45)},
    {"id": "fortune",  "name": "Fortune",       "desc": "+15% XP gain",       "cap": 5, "fn": lambda p: setattr(p, "xp_mult", p.xp_mult * 1.15)},
]


def _stat_apply(u):
    def apply(p):
        p.upgrade_counts[u["id"]] = p.upgrade_counts.get(u["id"], 0) + 1
        u["fn"](p)
    return apply


def _acquire_fn(cls):
    return lambda p: p.weapons.append(cls())


def _levelup_fn(weapon):
    return lambda p: weapon.apply_levelup()


# ---------------------------------------------------------------------------
# Parallax starfield (shared by the game and the title screen)
# ---------------------------------------------------------------------------
def build_star_tiles():
    tiles = []
    layers = [(256, 40, (70, 80, 115), 1, 0.25),
              (256, 26, (140, 150, 195), 1, 0.50),
              (256, 12, (215, 225, 255), 2, 0.85)]
    for size, count, col, r, par in layers:
        tile = pygame.Surface((size, size), pygame.SRCALPHA)
        rnd = random.Random(size * 31 + count)
        for _ in range(count):
            x, y = rnd.randint(0, size - 1), rnd.randint(0, size - 1)
            b = rnd.uniform(0.5, 1.0)
            pygame.draw.circle(tile, (int(col[0] * b), int(col[1] * b), int(col[2] * b)), (x, y), r)
        tiles.append((tile, par))
    return tiles


def _fullscreen():
    if sys.platform == "emscripten":
        # Browsers: ask the canvas itself to go fullscreen (toggle_fullscreen is a no-op).
        try:
            import platform as _pf
            doc = _pf.window.document
            cv = getattr(_pf.window, "canvas", None) or doc.getElementById("canvas") \
                or doc.querySelector("canvas")
            cv.requestFullscreen()
        except Exception:
            pass
        return
    try:
        pygame.display.toggle_fullscreen()
    except pygame.error:
        pass


def _touch_buttons():
    """On-screen buttons (top-right), tappable on mobile and clickable on desktop."""
    return {"pause": pygame.Rect(WIDTH - 86, 8, 34, 34),
            "fs": pygame.Rect(WIDTH - 44, 8, 34, 34)}


def _vol_buttons():
    """Tappable - / + buttons on the pause screen for music & sfx volume."""
    cx, cy = WIDTH // 2, HEIGHT // 2
    return {"music_dn": pygame.Rect(cx - 140, cy + 36, 30, 28),
            "music_up": pygame.Rect(cx + 110, cy + 36, 30, 28),
            "sfx_dn": pygame.Rect(cx - 140, cy + 76, 30, 28),
            "sfx_up": pygame.Rect(cx + 110, cy + 76, 30, 28)}


def _levelup_cards(n):
    card_w, card_h, gap = 240, 150, 30
    total = card_w * n + gap * (n - 1)
    x0 = WIDTH // 2 - total // 2
    return [pygame.Rect(x0 + i * (card_w + gap), 210, card_w, card_h) for i in range(n)]


def _hit_card(pos, n):
    for i, r in enumerate(_levelup_cards(n)):
        if r.collidepoint(pos):
            return i
    return None


def draw_starfield(surf, cam, tiles):
    surf.fill(BG)
    for tile, par in tiles:
        tw, th = tile.get_size()
        ox = int(cam.x * par) % tw
        oy = int(cam.y * par) % th
        for x in range(-ox, WIDTH, tw):
            for y in range(-oy, HEIGHT, th):
                surf.blit(tile, (x, y))


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, screen, font, big, small, audio=None, headless=False):
        self.screen = screen
        self.font = font
        self.big = big
        self.small = small
        self.audio = audio
        self.headless = headless
        self.cosmetic = not headless          # particles/rings only matter visually
        if not headless:
            self._build_stars()
        self.reset()

    def _build_stars(self):
        """Pre-render parallax star tiles once for a smooth, infinite space bg."""
        self.star_tiles = build_star_tiles()

    def sfx(self, name, vol=1.0):
        if self.audio:
            self.audio.play(name, vol)

    def reset(self, seed=None):
        if seed is None:
            try:
                seed = random.SystemRandom().getrandbits(31)   # fresh, unpredictable
            except Exception:
                seed = random.getrandbits(31)                  # web sandbox fallback
        self.seed = seed
        self.rng = random.Random(seed)
        self.replay = []                       # per-step input masks
        self.recording = not self.headless
        self.player = Player()
        self.enemies = []
        self.projectiles = []
        self.gems = []
        self.particles = []
        self.pickups = []
        self.rings = []
        self.ebullets = []
        self.elapsed = 0.0
        self.kills = 0
        self.score = 0
        self.name_input = ""
        self.scores = []
        self.last_entry = None
        self.global_scores = None
        self.paused = False
        self.spawn_timer = 0.0
        self.boss_index = 0
        self.round = 0
        self.round_budget = 0
        self.round_spawned = 0
        self.is_boss_round = False
        self.intermission = 0.0
        self.cluster_timer = 6.0
        self.hurt_sfx_t = 0.0
        self.banner = ""
        self.banner_t = 0.0
        self.state = "play"
        self.choices = []
        self.start_round(1)
        self.spawn_cluster()           # one to find right away

    # -- helpers ------------------------------------------------------------
    def _around_player(self, dist_min, dist_max):
        ang = self.rng.uniform(0, math.tau)
        d = self.rng.uniform(dist_min, dist_max)
        return self.player.pos + Vector2(math.cos(ang), math.sin(ang)) * d

    def _banner(self, text, t=1.8):
        self.banner = text
        self.banner_t = t

    # -- spawning -----------------------------------------------------------
    def start_round(self, n):
        """Begin a (silent) wave: a finite batch of enemies that won't respawn."""
        self.round = n
        self.is_boss_round = (n % 5 == 0)
        if n % 20 == 0:                      # every 20th round: the mega-boss
            self.round_budget = 10 + n
            self.spawn_omega()
        elif n % 10 == 0:                    # every 10th: ALL boss archetypes at once
            self.round_budget = 8 + n
            for _ in range(len(BOSS_TYPES)):
                self.spawn_boss()            # 4 consecutive indices -> one of each type
            self._banner("ALL-BOSS ASSAULT!", 3.2)
        elif self.is_boss_round:
            self.round_budget = 6 + n        # fewer adds — the boss is the threat
            for _ in range(1 + n // 15):     # extra bosses ramp slower now
                self.spawn_boss()
        else:
            self.round_budget = 8 + n * 4
        self.round_spawned = 0
        self.spawn_timer = 0.0

    def spawn_omega(self):
        omega = Enemy.make_omega(self._around_player(SPAWN_MIN, SPAWN_MAX), self.round)
        self.enemies.append(omega)
        self._banner("!!!  THE OMEGA  !!!", 3.5)
        self.sfx('omega')

    def spawn_enemy(self):
        n = self.round
        hp_scale = 1.0 + (n - 1) * 0.22                 # tankier each round
        speed_scale = min(2.2, 1.0 + (n - 1) * 0.04)    # noticeably faster over time
        dmg_scale = 1.0 + (n - 1) * 0.08                # and they hit harder
        roll = self.rng.random()
        if n >= 3 and roll < 0.10 + n * 0.012:
            kind = "brute"
        elif roll < 0.45:
            kind = "runner"
        else:
            kind = "grunt"
        e = Enemy.normal(self._around_player(SPAWN_MIN, SPAWN_MAX), kind, hp_scale, speed_scale)
        e.damage *= dmg_scale
        # Random "elite": small, fast, powerful glinting variant
        if self.rng.random() < min(0.20, 0.05 + n * 0.006):
            e.elite = True
            e.radius = max(7, int(e.radius * 0.8))
            e.max_hp *= 2.2
            e.hp = e.max_hp
            e.speed *= 1.55
            e.damage *= 1.7
            e.xp_value *= 3
        self.enemies.append(e)

    def spawn_boss(self):
        boss = Enemy.make_boss(self._around_player(SPAWN_MIN, SPAWN_MAX), self.boss_index, self.round)
        self.boss_index += 1
        self.enemies.append(boss)
        self._banner(f"{boss.name} APPROACHES!", 3.0)
        self.sfx('boss_spawn')

    def spawn_cluster(self):
        center = self._around_player(360, 700)
        for _ in range(self.rng.randint(3, 6)):
            kind = self.rng.choices(_PK_KINDS, weights=_PK_WEIGHTS)[0]
            off = Vector2(self.rng.uniform(-55, 55), self.rng.uniform(-55, 55))
            self.pickups.append(Pickup(center + off, kind))

    def spawn_interval(self):
        return max(0.08, 0.35 - self.round * 0.008)

    def grant_weapon(self, cls):
        w = self.player.get_weapon(cls)
        if w is None:
            self.player.weapons.append(cls())
            self._banner(f"Picked up {cls.NAME}!")
        elif w.level < cls.MAX_LEVEL:
            w.apply_levelup()
            self._banner(f"{cls.NAME} upgraded!")
        else:
            self._banner(f"{cls.NAME} maxed!")

    def apply_pickup(self, kind):
        p = self.player
        if kind == "heal":
            p.hp = min(p.max_hp, p.hp + 35)
            self._banner("+35 HP")
            self.sfx('heal')
        elif kind == "shield":
            _grant_shield(p, 8)
            self._banner("Shield restored!")
            self.sfx('shield')
        elif kind == "speed":
            if p.speed >= MAX_SPEED - 0.05:
                self.score += 150
                self._banner("Max speed! +150")
            else:
                p.speed *= 1.06
                self._banner("Speed up!")
            self.sfx('speed')
        elif kind == "damage":
            p.damage_mult *= 1.10
            self._banner("Damage up!")
            self.sfx('damage')
        elif kind == "magnet":
            for g in self.gems:
                g.pos = p.pos.copy()       # collected by normal gem logic this frame
            self._banner("Magnet!")
            self.sfx('magnet')
        elif kind in WEAPON_PICKUPS:
            self.grant_weapon(WEAPON_PICKUPS[kind])
            self.sfx('weapon')

    # -- main update --------------------------------------------------------
    def step(self, mask):
        """Advance the deterministic simulation one fixed tick for input `mask`."""
        state_before = self.state
        if state_before == "play":
            mx = (1 if mask & IN_RIGHT else 0) - (1 if mask & IN_LEFT else 0)
            my = (1 if mask & IN_DOWN else 0) - (1 if mask & IN_UP else 0)
            self._advance(SIM_DT, mx, my)
        elif state_before == "levelup":
            if mask & IN_C1:
                self.choose_upgrade(0)
            elif mask & IN_C2:
                self.choose_upgrade(1)
            elif mask & IN_C3:
                self.choose_upgrade(2)
        if self.recording and state_before in ("play", "levelup"):
            self.replay.append(mask)

    def _advance(self, dt, mx, my):
        self.elapsed += dt
        self.banner_t = max(0.0, self.banner_t - dt)
        self.player.update(dt, mx, my)

        # Silent round-based spawning: finite enemies, a lull, then a harder wave.
        if self.intermission > 0:
            self.intermission -= dt
            if self.intermission <= 0:
                self.start_round(self.round + 1)
        elif self.round_spawned < self.round_budget:
            self.spawn_timer -= dt
            while (self.spawn_timer <= 0 and self.round_spawned < self.round_budget
                   and len(self.enemies) < 300):
                self.spawn_enemy()
                self.round_spawned += 1
                self.spawn_timer += self.spawn_interval()
        elif not self.enemies:
            self.intermission = 2.5            # wave cleared -> brief calm
            self.score += self.round * 50
            self.sfx('wave_clear')

        self.cluster_timer -= dt
        if self.cluster_timer <= 0:
            self.spawn_cluster()
            self.cluster_timer = self.rng.uniform(9.0, 14.0)

        # Weapons
        shots = self.player.try_fire(self.enemies)
        if shots:
            self.projectiles.extend(shots)
            self.sfx('shoot', 0.4)         # bolt fires often — keep it gentle
        for w in self.player.weapons:
            w.update(dt, self)

        # Enemies move (bosses run their own behavior + attacks)
        for e in self.enemies:
            if e.is_boss:
                self._boss_behave(e, dt)
            else:
                e.update(dt, self.player)

        # Boss bullets
        for b in self.ebullets:
            b.update(dt)
        alive_b = []
        for b in self.ebullets:
            if b.dead:
                continue
            if (b.pos - self.player.pos).length_squared() <= (b.radius + self.player.radius) ** 2:
                self.player.hurt(b.damage)
                self.sfx('hurt', 0.5)
            else:
                alive_b.append(b)
        self.ebullets = alive_b

        # Projectiles + collisions (also clears dead enemies + drops loot)
        for p in self.projectiles:
            p.update(dt)
        self._resolve_hits()

        # Contact damage
        took_contact = False
        for e in self.enemies:
            rr = (e.radius + self.player.radius) ** 2
            if (e.pos - self.player.pos).length_squared() <= rr:
                self.player.hurt(e.damage * dt)
                took_contact = True
        self.hurt_sfx_t -= dt
        if took_contact and self.hurt_sfx_t <= 0:
            self.sfx('hurt', 0.6)
            self.hurt_sfx_t = 0.45

        # Pickups (before gems so 'magnet' collects this frame)
        kept = []
        for pk in self.pickups:
            rr = (pk.radius + self.player.radius) ** 2
            if (pk.pos - self.player.pos).length_squared() <= rr:
                self.apply_pickup(pk.kind)
            else:
                kept.append(pk)
        self.pickups = kept

        # Gems
        remaining = []
        leveled = False
        for g in self.gems:
            if g.update(dt, self.player):
                leveled = self.player.add_xp(g.value) or leveled
            else:
                remaining.append(g)
        self.gems = remaining

        # FX
        for pt in self.particles:
            pt.update(dt)
        self.particles = [pt for pt in self.particles if pt.life > 0]
        for r in self.rings:
            r.update(dt)
        self.rings = [r for r in self.rings if not r.dead]

        # You can't outrun a wave: enemies that fall too far behind re-appear around you.
        pp = self.player.pos
        for e in self.enemies:
            if (e.pos - pp).length_squared() > CULL_DIST2:
                e.pos = self._around_player(SPAWN_MIN, SPAWN_MAX)
        self.gems = [g for g in self.gems if (g.pos - pp).length_squared() < 1500 ** 2]
        self.pickups = [pk for pk in self.pickups if (pk.pos - pp).length_squared() < 1700 ** 2]

        if self.player.hp <= 0:
            self.player.hp = 0
            self.state = "enter_name"
            return

        if leveled:
            self._build_choices()
            if self.choices:
                self.state = "levelup"
                self.sfx('level_up')
            else:
                self.score += 200          # everything maxed -> bonus instead

    def _boss_behave(self, b, dt):
        """Per-archetype boss movement and attacks."""
        p = self.player
        b._hit_flash = max(0.0, b._hit_flash - dt)
        to_p = p.pos - b.pos
        dist = to_p.length() or 1.0
        d = to_p / dist
        b.face_angle = math.degrees(math.atan2(-d.y, d.x)) - 90
        step = b.speed * dt * FPS

        if b.behavior == "charger":
            b.atk_t -= dt
            if b.state == "chase":
                b.pos += d * step
                if b.atk_t <= 0:
                    b.state, b.state_t = "windup", 0.45
            elif b.state == "windup":
                b.state_t -= dt
                b.charge_dir = d                 # track aim while winding up
                b._hit_flash = 0.1               # flash = telegraph
                b.pos += d * step * 0.25
                if b.state_t <= 0:
                    b.state, b.state_t = "dash", 0.4
                    self.sfx('nova', 0.4)
            elif b.state == "dash":
                b.state_t -= dt
                b._hit_flash = 0.1
                b.pos += b.charge_dir * step * 5.0
                if b.state_t <= 0:
                    b.state, b.atk_t = "chase", 3.0

        elif b.behavior == "tank":
            b.pos += d * step
            b.atk_t -= dt
            if b.atk_t <= 0:
                b.atk_t = 3.5
                r = b.radius + 120
                self.rings.append(Ring(b.pos.copy(), r, (255, 160, 80)))
                self.sfx('nova', 0.6)
                if dist <= r:                    # ground slam hits if you're close
                    p.hurt(b.damage * 0.7)

        elif b.behavior == "shooter":
            # Hang back a bit, then fire a spread
            b.pos += d * step * (0.5 if dist < 260 else 1.0)
            b.atk_t -= dt
            if b.atk_t <= 0:
                b.atk_t = 1.6
                base = math.atan2(d.y, d.x)
                for off in (-0.26, 0.0, 0.26):
                    vel = Vector2(math.cos(base + off), math.sin(base + off)) * 5.2
                    self.ebullets.append(EnemyBullet(b.pos.copy(), vel, b.damage * 0.8))
                self.sfx('shoot', 0.5)

        elif b.behavior == "omega":
            b.pos += d * step * 0.8                       # steady advance
            b.atk_t -= dt                                  # rapid 5-way fire
            if b.atk_t <= 0:
                b.atk_t = 1.1
                base = math.atan2(d.y, d.x)
                for off in (-0.5, -0.25, 0.0, 0.25, 0.5):
                    vel = Vector2(math.cos(base + off), math.sin(base + off)) * 5.5
                    self.ebullets.append(EnemyBullet(b.pos.copy(), vel, b.damage * 0.6, radius=9))
                self.sfx('shoot', 0.6)
            b.state_t -= dt                                # giant ground slam
            if b.state_t <= 0:
                b.state_t = 3.5
                r = b.radius + 170
                if self.cosmetic:
                    self.rings.append(Ring(b.pos.copy(), r, (255, 120, 90)))
                self.sfx('omega_slam', 0.9)
                if dist <= r:
                    p.hurt(b.damage * 0.8)

        else:  # "fast" and default: relentless chase
            b.pos += d * step

    def _resolve_hits(self):
        alive_proj = []
        for p in self.projectiles:
            if p.dead:
                continue
            for e in self.enemies:
                if e.hp <= 0 or id(e) in p._hit:
                    continue
                rr = (e.radius + p.radius) ** 2
                if (e.pos - p.pos).length_squared() <= rr:
                    e.hurt(p.damage)
                    p._hit.add(id(e))
                    p.pierce -= 1
                    if p.pierce < 0:
                        break
            if not p.dead:
                alive_proj.append(p)
        self.projectiles = alive_proj

        survivors = []
        died = False
        boss_died = False
        for e in self.enemies:
            if e.hp > 0:
                survivors.append(e)
                continue
            self.kills += 1
            if e.is_boss:
                boss_died = True
                self.score += 500 + self.round * 100
                for _ in range(12):
                    ang = self.rng.uniform(0, math.tau)
                    off = Vector2(math.cos(ang), math.sin(ang)) * self.rng.uniform(5, 45)
                    self.gems.append(Gem(e.pos + off, max(1, e.xp_value // 12)))
                if self.cosmetic:
                    for _ in range(30):
                        self.particles.append(Particle(e.pos, e.color))
                self.player.hp = min(self.player.max_hp, self.player.hp + self.player.max_hp * 0.25)
                self._banner("BOSS DEFEATED!  +25% HP", 2.5)
            else:
                self.gems.append(Gem(e.pos.copy(), e.xp_value))
                if self.cosmetic:
                    for _ in range(6):
                        self.particles.append(Particle(e.pos, e.color))
                died = True
                self.score += e.xp_value * 10
        self.enemies = survivors
        if boss_died:
            self.sfx('boss_death')
        elif died:
            self.sfx('enemy_death', 0.5)

    def _build_choices(self):
        p = self.player
        pool = []
        for u in STAT_UPGRADES:
            if p.upgrade_counts.get(u["id"], 0) >= u["cap"]:   # hide maxed buffs
                continue
            avail = u.get("avail")
            if avail and not avail(p):                          # e.g. hide speed at max speed
                continue
            pool.append((u["name"], u["desc"], _stat_apply(u)))
        for cls in WEAPON_REGISTRY:
            w = p.get_weapon(cls)
            if w is None:
                pool.append((f"New: {cls.NAME}", cls.PICKUP_DESC, _acquire_fn(cls)))
            elif w.level < cls.MAX_LEVEL:                       # maxed weapons drop out too
                pool.append((f"{cls.NAME} Lv{w.level + 1}", w.next_desc(), _levelup_fn(w)))
        self.choices = self.rng.sample(pool, min(3, len(pool))) if pool else []

    def choose_upgrade(self, index):
        if 0 <= index < len(self.choices):
            self.choices[index][2](self.player)
            self.state = "play"
            self.choices = []

    def make_replay(self, name):
        return {"v": SIM_VERSION, "seed": self.seed, "name": name,
                "score": int(self.score), "round": self.round,
                "kills": self.kills, "time": int(self.elapsed),
                "date": time.strftime("%Y-%m-%d"), "steps": list(self.replay)}

    def submit_score(self):
        name = (self.name_input.strip() or "PLAYER")[:12]
        entry = {"name": name, "score": int(self.score), "round": self.round,
                 "kills": self.kills, "time": int(self.elapsed),
                 "date": time.strftime("%Y-%m-%d")}
        # Local leaderboard
        scores = load_scores()
        scores.append(entry)
        scores.sort(key=lambda e: e.get("score", 0), reverse=True)
        save_scores(scores[:50])
        self.scores = scores[:50]
        self.last_entry = entry
        clear_save()                       # run is over
        # Global leaderboard (best-effort; verified server-side via replay)
        self.global_scores = None
        if SERVER_URL:
            self.global_scores = submit_global(self.make_replay(name))
        self.state = "scores"

    # -- drawing ------------------------------------------------------------
    def draw(self):
        s = self.screen
        cam = self.player.pos - CENTER
        self._draw_bg(s, cam)

        for r in self.rings:
            r.draw(s, cam)
        for pk in self.pickups:
            pk.draw(s, cam, self.small)
        for g in self.gems:
            g.draw(s, cam)
        for pt in self.particles:
            pt.draw(s, cam)
        for e in self.enemies:
            e.draw(s, cam)
        for b in self.ebullets:
            b.draw(s, cam)
        for p in self.projectiles:
            p.draw(s, cam)
        self.player.draw(s, cam)
        for w in self.player.weapons:
            w.draw(s, self.player, cam)

        self._draw_hud(s)
        self._draw_panel(s)
        self._draw_controls(s)
        if self.state == "levelup":
            self._draw_levelup(s)
        elif self.state == "enter_name":
            self._draw_enter_name(s)
        elif self.state == "scores":
            self._draw_scores(s)
        elif self.paused:
            self._draw_pause(s)

    def _draw_bg(self, s, cam):
        draw_starfield(s, cam, self.star_tiles)

    def _draw_hud(self, s):
        # HP
        pygame.draw.rect(s, (40, 40, 50), (16, 16, 240, 16))
        pygame.draw.rect(s, HP_COL, (16, 16, 240 * max(0, self.player.hp) / self.player.max_hp, 16))
        pygame.draw.rect(s, (10, 12, 20), (16, 16, 240, 16), 2)
        s.blit(self.small.render(f"{int(self.player.hp)}/{int(self.player.max_hp)}", True, WHITE), (20, 17))
        # Shield
        if self.player.max_shield > 0:
            pygame.draw.rect(s, (40, 40, 50), (16, 35, 240, 8))
            pygame.draw.rect(s, SHIELD_COL, (16, 35, 240 * max(0, self.player.shield) / self.player.max_shield, 8))
            pygame.draw.rect(s, (10, 12, 20), (16, 35, 240, 8), 1)
        # XP
        pygame.draw.rect(s, (40, 40, 50), (16, 47, 240, 9))
        pygame.draw.rect(s, XP_COL, (16, 47, 240 * self.player.xp / self.player.xp_to_next, 9))
        pygame.draw.rect(s, (10, 12, 20), (16, 47, 240, 9), 1)

        mins = int(self.elapsed // 60)
        secs = int(self.elapsed % 60)
        s.blit(self.font.render(f"LV {self.player.level}", True, GOLD), (16, 62))
        s.blit(self.font.render(f"{mins:02d}:{secs:02d}", True, WHITE), (WIDTH // 2 - 28, 16))
        sc = self.big.render(f"{int(self.score)}", True, GOLD)
        s.blit(sc, (WIDTH // 2 - sc.get_width() // 2, 38))
        s.blit(self.font.render(f"Kills {self.kills}", True, WHITE), (WIDTH - 130, 50))

        # On-screen Pause / Fullscreen buttons (for touch; also clickable)
        btns = _touch_buttons()
        for key, r in btns.items():
            pygame.draw.rect(s, (30, 36, 52), r, border_radius=6)
            pygame.draw.rect(s, (90, 100, 130), r, 1, border_radius=6)
        pr = btns["pause"]
        if self.paused:
            pygame.draw.polygon(s, WHITE, [(pr.x + 12, pr.y + 9), (pr.x + 12, pr.y + 25), (pr.x + 26, pr.y + 17)])
        else:
            pygame.draw.rect(s, WHITE, (pr.x + 11, pr.y + 9, 4, 16))
            pygame.draw.rect(s, WHITE, (pr.x + 19, pr.y + 9, 4, 16))
        fr = btns["fs"]
        for cx, cy, dx, dy in [(11, 11, 1, 1), (23, 11, -1, 1), (11, 23, 1, -1), (23, 23, -1, -1)]:
            pygame.draw.line(s, WHITE, (fr.x + cx, fr.y + cy), (fr.x + cx + 6 * dx, fr.y + cy), 2)
            pygame.draw.line(s, WHITE, (fr.x + cx, fr.y + cy), (fr.x + cx, fr.y + cy + 6 * dy), 2)

        bosses = [e for e in self.enemies if e.is_boss and e.hp > 0]
        bw = 520
        x = WIDTH // 2 - bw // 2
        for i, b in enumerate(bosses[:4]):
            y = HEIGHT - 34 - i * 26
            pygame.draw.rect(s, (40, 40, 50), (x, y, bw, 16))
            pygame.draw.rect(s, b.color, (x, y, bw * max(0, b.hp) / b.max_hp, 16))
            pygame.draw.rect(s, GOLD, (x, y, bw, 16), 2)
            nm = self.small.render(b.name, True, WHITE)
            s.blit(nm, (WIDTH // 2 - nm.get_width() // 2, y - 14))

        if self.banner_t > 0 and self.state == "play":
            txt = self.big.render(self.banner, True, GOLD)
            s.blit(txt, (WIDTH // 2 - txt.get_width() // 2, 110))

    def _draw_panel(self, s):
        """Always-on loadout readout: weapons + damage + active buffs."""
        p = self.player
        mult = p.damage_mult
        lines = [("WEAPONS", GOLD),
                 (f"Bolt        dmg {p.damage * mult:.0f}", WHITE)]
        for w in p.weapons:
            lines.append((f"{w.NAME:<11} L{w.level} dmg {w.damage * mult:.0f}", WHITE))
        vacuum = f"ON {p.pickup_radius:.0f}" if p.pickup_radius > 30 else "off"
        lines += [("BUFFS", GOLD),
                  (f"Power   x{mult:.2f}", GEM_COL),
                  (f"Speed   {p.speed:.1f}", GEM_COL),
                  (f"Max HP  {p.max_hp:.0f}", GEM_COL),
                  (f"Shield  {p.max_shield:.0f}", GEM_COL),
                  (f"Vacuum  {vacuum}", GEM_COL)]

        lh = 16
        h = len(lines) * lh + 10
        y0 = HEIGHT - h - 8
        panel = pygame.Surface((210, h), pygame.SRCALPHA)
        panel.fill((10, 12, 20, 160))
        s.blit(panel, (8, y0))
        for i, (txt, col) in enumerate(lines):
            s.blit(self.small.render(txt, True, col), (16, y0 + 6 + i * lh))

    def _keycap(self, s, x, y, text):
        """Draw a small keycap and return its width."""
        t = self.small.render(text, True, WHITE)
        w = max(16, t.get_width() + 8)
        rect = pygame.Rect(x, y - 1, w, 17)
        pygame.draw.rect(s, (45, 50, 66), rect, border_radius=3)
        pygame.draw.rect(s, (90, 98, 120), rect, 1, border_radius=3)
        s.blit(t, (x + (w - t.get_width()) // 2, y))
        return w

    def _draw_controls(self, s):
        rows = [
            (["W", "A", "S", "D"], "Move"),
            (["1", "2", "3"], "Upgrade"),
            (["P"], "Pause"),
            (["F"], "Fullscreen"),
            (["M"], "Music"),
            (["[", "]"], "SFX vol"),
            (["-", "="], "Mus vol"),
            (["R"], "Restart"),
            (["Esc"], "Quit"),
        ]
        rowh = 22
        pw, ph = 196, len(rows) * rowh + 10
        px, py = WIDTH - pw - 8, HEIGHT - ph - 8
        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel.fill((10, 12, 20, 150))
        s.blit(panel, (px, py))
        for r, (keys, label) in enumerate(rows):
            y = py + 8 + r * rowh
            x = px + 8
            for k in keys:
                x += self._keycap(s, x, y, k) + 4
            s.blit(self.small.render(label, True, DIM), (px + 112, y + 1))

    def _draw_levelup(self, s):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 12, 20, 200))
        s.blit(overlay, (0, 0))
        title = self.big.render("LEVEL UP!", True, GOLD)
        s.blit(title, (WIDTH // 2 - title.get_width() // 2, 90))
        hint = self.small.render("press 1 / 2 / 3  —  or tap a card", True, DIM)
        s.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 150))

        for i, (rect, (name, desc, _)) in enumerate(zip(_levelup_cards(len(self.choices)), self.choices)):
            pygame.draw.rect(s, (30, 34, 50), rect, border_radius=10)
            pygame.draw.rect(s, GOLD, rect, 2, border_radius=10)
            s.blit(self.big.render(str(i + 1), True, GOLD), (rect.x + 16, rect.y + 12))
            nm = self.font.render(name, True, WHITE)
            s.blit(nm, (rect.centerx - nm.get_width() // 2, rect.y + 60))
            ds = self.small.render(desc, True, GEM_COL)
            s.blit(ds, (rect.centerx - ds.get_width() // 2, rect.y + 95))

    def _draw_enter_name(self, s):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((20, 8, 12, 215))
        s.blit(overlay, (0, 0))
        mins, secs = int(self.elapsed // 60), int(self.elapsed % 60)
        title = self.big.render("YOU DIED", True, HP_COL)
        s.blit(title, (WIDTH // 2 - title.get_width() // 2, 130))
        sc = self.big.render(f"SCORE  {int(self.score)}", True, GOLD)
        s.blit(sc, (WIDTH // 2 - sc.get_width() // 2, 195))
        stats = self.font.render(
            f"Round {self.round}  •  {mins:02d}:{secs:02d}  •  {self.kills} kills", True, WHITE)
        s.blit(stats, (WIDTH // 2 - stats.get_width() // 2, 255))

        prompt = self.font.render("Enter your name:", True, DIM)
        s.blit(prompt, (WIDTH // 2 - prompt.get_width() // 2, 320))
        cursor = "_" if int(self.elapsed * 2) % 2 == 0 else " "
        name = self.big.render((self.name_input or "") + cursor, True, WHITE)
        s.blit(name, (WIDTH // 2 - name.get_width() // 2, 350))
        hint = self.font.render("Press ENTER to save", True, DIM)
        s.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 410))

    def _draw_scores(self, s):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 12, 20, 225))
        s.blit(overlay, (0, 0))
        title = self.big.render("LEADERBOARD", True, GOLD)
        s.blit(title, (WIDTH // 2 - title.get_width() // 2, 50))

        is_global = self.global_scores is not None
        board = self.global_scores if is_global else self.scores
        label = "🌐 global (verified)" if is_global else "(local)"
        lab = self.small.render(label, True, GEM_COL if is_global else DIM)
        s.blit(lab, (WIDTH // 2 - lab.get_width() // 2, 100))

        x = WIDTH // 2 - 240
        y = 130
        for i, e in enumerate(board[:10]):
            col = GOLD if (not is_global and e is self.last_entry) else WHITE
            s.blit(self.font.render(f"{i + 1:2}.", True, col), (x, y))
            s.blit(self.font.render(str(e.get("name", "?"))[:12], True, col), (x + 40, y))
            s.blit(self.font.render(f"{e.get('score', 0):>8}", True, col), (x + 250, y))
            s.blit(self.small.render(f"R{e.get('round', 0)}", True, DIM), (x + 380, y + 3))
            y += 30
        if not board:
            none = self.font.render("No scores yet — be the first!", True, DIM)
            s.blit(none, (WIDTH // 2 - none.get_width() // 2, 160))
        hint = self.font.render("Press R to play again  •  Esc to quit", True, DIM)
        s.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 50))

    def _draw_pause(self, s):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 12, 20, 190))
        s.blit(overlay, (0, 0))
        cx, cy = WIDTH // 2, HEIGHT // 2
        title = self.big.render("PAUSED", True, WHITE)
        s.blit(title, (cx - title.get_width() // 2, cy - 120))
        s.blit(self.small.render("progress autosaved", True, DIM), (cx - 60, cy - 60))

        a = self.audio
        vb = _vol_buttons()
        rows = [("MUSIC", int((a.music_vol if a else 0) * 100), vb["music_dn"], vb["music_up"], cy + 36),
                ("SFX", int((a.sfx_vol if a else 0) * 100), vb["sfx_dn"], vb["sfx_up"], cy + 76)]
        for label, val, dn, up, y in rows:
            s.blit(self.font.render(label, True, WHITE), (cx - 210, y + 2))
            for r, sym in ((dn, "-"), (up, "+")):
                pygame.draw.rect(s, (40, 46, 64), r, border_radius=5)
                pygame.draw.rect(s, (100, 110, 140), r, 1, border_radius=5)
                g = self.font.render(sym, True, WHITE)
                s.blit(g, (r.centerx - g.get_width() // 2, r.y + 2))
            bx, bw = cx - 100, 200
            pygame.draw.rect(s, (40, 40, 50), (bx, y + 6, bw, 16))
            pygame.draw.rect(s, GEM_COL, (bx, y + 6, bw * val // 100, 16))
            pygame.draw.rect(s, (10, 12, 20), (bx, y + 6, bw, 16), 1)
            pct = self.small.render(f"{val}%", True, WHITE)
            s.blit(pct, (bx + bw // 2 - pct.get_width() // 2, y + 7))
        hint = self.font.render("P resume  •  Esc quit", True, DIM)
        s.blit(hint, (cx - hint.get_width() // 2, cy + 122))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def verify_replay(replay):
    """Re-run a replay headlessly and confirm its claimed score. This is what
    the server calls — a fabricated score won't reproduce, so it's rejected.
    Returns (ok, recomputed_score)."""
    if replay.get("v") != SIM_VERSION:
        return False, None
    steps = replay.get("steps") or []
    if not isinstance(steps, list) or len(steps) > 2_000_000:
        return False, None
    g = Game(None, None, None, None, audio=None, headless=True)
    g.reset(seed=int(replay["seed"]))
    g.recording = False
    for mask in steps:
        g.step(int(mask) & 0x7F)
        if g.state == "enter_name":     # player died — run ended
            break
    ok = (g.state == "enter_name") and (g.score == int(replay.get("score", -1)))
    return ok, g.score


def resume_game(game, save):
    """Rebuild an in-progress run by replaying its saved inputs (deterministic)."""
    game.reset(seed=int(save["seed"]))
    saved_audio, game.audio = game.audio, None      # stay quiet while fast-forwarding
    game.cosmetic = False
    game.recording = True
    game.replay = []
    for mask in save["steps"]:
        game.step(int(mask) & 0x7F)
        if game.state == "enter_name":
            break
    game.audio = saved_audio
    game.cosmetic = True


def submit_global(replay):
    """POST a replay to the leaderboard server and return the global top list.
    Best-effort: any failure just returns None (gameplay never blocks)."""
    import urllib.request
    try:
        data = json.dumps(replay).encode()
        req = urllib.request.Request(SERVER_URL + "/submit", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.load(r).get("leaderboard")
    except Exception:
        return None


def fetch_global():
    import urllib.request
    try:
        with urllib.request.urlopen(SERVER_URL + "/leaderboard", timeout=4) as r:
            return json.load(r).get("leaderboard")
    except Exception:
        return None


async def load_assets(screen, big, small):
    """Smoothly load every bitmap asset, drawing a progress bar as we go."""
    art = Assets()
    title = big.render("LOADING", True, WHITE)
    tx = WIDTH // 2 - title.get_width() // 2
    art.ensure()                       # generate PNGs on first run
    n = max(1, len(art.names))
    for i, name in enumerate(art.names):
        art.load_one(name)
        screen.fill(BG)
        screen.blit(title, (tx, HEIGHT // 2 - 70))
        bw, x, y = 380, WIDTH // 2 - 190, HEIGHT // 2
        pygame.draw.rect(screen, (40, 44, 60), (x, y, bw, 16))
        pygame.draw.rect(screen, PLAYER_COL, (x, y, bw * (i + 1) / n, 16))
        pygame.draw.rect(screen, (10, 12, 20), (x, y, bw, 16), 2)
        sub = small.render(f"{name}  ({i + 1}/{n})", True, DIM)
        screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, y + 26))
        pygame.event.pump()
        pygame.display.flip()
        await asyncio.sleep(0.025)     # yields to the browser; smooth load on desktop
    return art


CODEX = [
    ("player_ship", "Your Ship", "Last Vanguard pilot of the fallen Aurora Fleet."),
    ("enemy_grunt", "Krell Drone", "Expendable hive drone — slow, weak, endless."),
    ("enemy_runner", "Krell Stinger", "Darting scout. Low HP, but it runs you down."),
    ("enemy_brute", "Krell Mauler", "Armored heavy caste. Huge HP and damage."),
    (("enemy_runner", True), "Ascended", "A foe the hive reforged — fast, tough, 3x XP."),
    ("boss_warlord", "The Warlord", "Krell war-chief. Winds up, then charges."),
    ("boss_devourer", "The Devourer", "Voidkin predator. Fast, relentless hunter."),
    ("boss_colossus", "The Colossus", "Iron Synod war-cathedral. Slams the ground."),
    ("boss_reaper", "The Reaper", "Voidkin wraith. Snipes bullet spreads from afar."),
    ("boss_omega", "THE OMEGA", "The Convergence — every race fused into one."),
    ("gem", "XP Gem", "Crystallized essence. Collect it to grow stronger."),
    ("crate", "Weapon Crate", "Salvage — auto-equips or upgrades a weapon."),
    ("pickup_heal", "Heal", "Hull repair: restores +35 HP."),
    ("pickup_shield", "Shield", "Recharges and boosts your energy shield."),
    ("pickup_speed", "Speed", "Thruster boost: +move speed (capped)."),
    ("pickup_damage", "Damage", "Overcharge: +ALL weapon damage."),
    ("pickup_magnet", "Magnet", "Tractor pulse: pulls in every XP gem."),
]

LORE = [
    ("h", "THE LAST LIGHT"),
    ("p", "The Aurora Fleet is ash. When the Devouring Tide swept the core worlds, "
          "every beacon went dark — every beacon but yours."),
    ("p", "You are the last Vanguard pilot, adrift in the dead zones between the "
          "stars, your hull held together by salvage and spite."),
    ("p", "The Tide is not one enemy but many: a convergence of broken races, each "
          "consumed and remade by the hive-mind known only as THE OMEGA."),
    ("p", "There is no rescue. There is only how long you hold the line — and how "
          "many you take with you."),
    ("", ""),
    ("h", "RACES OF THE TIDE"),
    ("s", "THE KRELL"),
    ("p", "An insectoid hive that breeds faster than it can be burned. Expendable "
          "Drones, darting Stingers, and armored Maulers — led by brutal Warlords."),
    ("s", "THE VOIDKIN"),
    ("p", "Pale predators from the dark between galaxies. The Devourer runs prey "
          "down; the Reaper picks it off from range."),
    ("s", "THE IRON SYNOD"),
    ("p", "A machine theocracy of walking cathedrals. The Colossus is the smallest "
          "of their war-engines."),
    ("s", "THE ASCENDED"),
    ("p", "Any creature the hive deems worthy is reforged — smaller, faster, "
          "deadlier. You will know them by their golden glint."),
    ("s", "THE OMEGA"),
    ("p", "The Convergence itself. Every race, every weapon, fused into one "
          "impossible body. It comes only for those who last long enough."),
]


def _wrap(text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if fnt.size(test)[0] > maxw and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


async def lore_screen(screen, clock, font, big, small):
    """Scrollable story + alien races. Returns 'back'/'quit'."""
    tiles = build_star_tiles()
    cam = Vector2(0, 0)
    mid = pygame.font.SysFont("menlo,consolas,monospace", 26, bold=True)
    top, view_h, maxw = 120, HEIGHT - 144, WIDTH - 160

    entries = []        # (surface or None, height)
    for kind, text in LORE:
        if kind == "":
            entries.append((None, 16))
        elif kind == "h":
            entries.append((big.render(text, True, GOLD), big.get_height() + 10))
        elif kind == "s":
            entries.append((mid.render(text, True, (140, 200, 255)), mid.get_height() + 8))
        else:
            for line in _wrap(text, font, maxw):
                entries.append((font.render(line, True, (212, 218, 232)), font.get_height() + 4))
    content_h = sum(h for _, h in entries)
    maxoff = max(0, content_h - view_h)
    offset = 0.0

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.MOUSEWHEEL:
                offset = max(0, min(maxoff, offset - event.y * 44))
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_f, pygame.K_F11):
                    _fullscreen()
                if event.key in (pygame.K_ESCAPE, pygame.K_l, pygame.K_BACKSPACE, pygame.K_RETURN):
                    return "back"
                if event.key in (pygame.K_DOWN, pygame.K_s):
                    offset = min(maxoff, offset + 40)
                if event.key in (pygame.K_UP, pygame.K_w):
                    offset = max(0, offset - 40)

        cam += Vector2(16, 6) * dt
        draw_starfield(screen, cam, tiles)
        title = big.render("LORE", True, GOLD)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 40))
        screen.blit(small.render("scroll: wheel / up-down     Esc or L: back", True, DIM),
                    (WIDTH // 2 - 130, 92))

        prev_clip = screen.get_clip()
        screen.set_clip(pygame.Rect(0, top, WIDTH, view_h))
        y = top - int(offset)
        for surf, h in entries:
            if surf is not None and y + h > top and y < top + view_h:
                screen.blit(surf, (80, y))
            y += h
        screen.set_clip(prev_clip)
        pygame.display.flip()
        await asyncio.sleep(0)


async def codex_screen(screen, clock, font, big, small):
    """Scrollable menu: enlarged sprites with explanations. Returns 'back'/'quit'."""
    tiles = build_star_tiles()
    cam = Vector2(0, 0)
    box, rowh, top = 104, 120, 116
    view_h = HEIGHT - top - 24

    icons = []
    for ref, name, desc in CODEX:
        elite = False
        sprname = ref
        if isinstance(ref, tuple):
            sprname, elite = ref
        img = ART.get(sprname) if ART else None
        ic = None
        if img:
            sc = box / img.get_width()
            ic = pygame.transform.scale(img, (max(1, int(img.get_width() * sc)),
                                              max(1, int(img.get_height() * sc))))
        icons.append((ic, elite, name, desc))

    content_h = len(icons) * rowh
    maxoff = max(0, content_h - view_h)
    offset = 0.0

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.MOUSEWHEEL:
                offset = max(0, min(maxoff, offset - event.y * 44))
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_f, pygame.K_F11):
                    _fullscreen()
                if event.key in (pygame.K_ESCAPE, pygame.K_i, pygame.K_BACKSPACE, pygame.K_RETURN):
                    return "back"
                if event.key in (pygame.K_DOWN, pygame.K_s):
                    offset = min(maxoff, offset + rowh)
                if event.key in (pygame.K_UP, pygame.K_w):
                    offset = max(0, offset - rowh)

        cam += Vector2(18, 7) * dt
        draw_starfield(screen, cam, tiles)
        title = big.render("CODEX", True, GOLD)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 40))
        hint = small.render("scroll: wheel / up-down     Esc or I: back", True, DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 92))

        prev_clip = screen.get_clip()
        screen.set_clip(pygame.Rect(0, top, WIDTH, view_h))
        for i, (ic, elite, name, desc) in enumerate(icons):
            y = top + i * rowh - int(offset)
            if y + rowh < top or y > top + view_h:
                continue
            cy = y + rowh // 2
            if ic:
                screen.blit(ic, ic.get_rect(center=(100, cy)))
                if elite:
                    pygame.draw.circle(screen, (255, 240, 120), (100, cy), box // 2 - 2, 2)
            screen.blit(font.render(name, True, WHITE), (210, cy - 22))
            screen.blit(small.render(desc, True, GEM_COL), (210, cy + 4))
        screen.set_clip(prev_clip)
        pygame.display.flip()
        await asyncio.sleep(0)


async def leaderboard_screen(screen, clock, font, big, small):
    """Standalone leaderboard viewer for the main menu (local, or global if a
    server is configured). Returns 'back'/'quit'."""
    tiles = build_star_tiles()
    cam = Vector2(0, 0)
    gscores = fetch_global() if SERVER_URL else None
    is_global = gscores is not None
    board = gscores if is_global else load_scores()

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.MOUSEBUTTONDOWN:     # tap to go back (mobile)
                return "back"
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_f, pygame.K_F11):
                    _fullscreen()
                if event.key in (pygame.K_ESCAPE, pygame.K_b, pygame.K_BACKSPACE, pygame.K_RETURN):
                    return "back"

        cam += Vector2(16, 6) * dt
        draw_starfield(screen, cam, tiles)
        title = big.render("LEADERBOARD", True, GOLD)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 44))
        label = "global (verified)" if is_global else "local"
        lab = small.render(label, True, GEM_COL if is_global else DIM)
        screen.blit(lab, (WIDTH // 2 - lab.get_width() // 2, 96))

        x, y = WIDTH // 2 - 240, 130
        for i, e in enumerate(board[:14]):
            col = GOLD if i == 0 else WHITE
            screen.blit(font.render(f"{i + 1:2}.", True, col), (x, y))
            screen.blit(font.render(str(e.get("name", "?"))[:12], True, col), (x + 40, y))
            screen.blit(font.render(f"{e.get('score', 0):>8}", True, col), (x + 250, y))
            screen.blit(small.render(f"R{e.get('round', 0)}", True, DIM), (x + 380, y + 3))
            y += 30
        if not board:
            none = font.render("No scores yet — go set one!", True, DIM)
            screen.blit(none, (WIDTH // 2 - none.get_width() // 2, 170))
        hint = small.render("Esc or B: back", True, DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 56))
        pygame.display.flip()
        await asyncio.sleep(0)


async def title_screen(screen, clock, font, big, small, audio):
    """Animated title: a self-piloting ship weaves and dodges through space,
    auto-firing at drifting foes. Returns 'play' or 'quit'."""
    tiles = build_star_tiles()
    huge = pygame.font.SysFont("menlo,consolas,monospace", 72, bold=True)
    enemy_sprites = ["enemy_grunt", "enemy_runner", "enemy_brute"]

    cam = Vector2(0, 0)
    scroll = Vector2(70, 18)
    ship = Vector2(WIDTH * 0.35, HEIGHT * 0.55)
    vel = Vector2(200, 0)
    target = Vector2(WIDTH * 0.5, HEIGHT * 0.45)
    angle, fire_t, spawn_t, t = 0.0, 0.0, 0.0, 0.0
    enemies, bolts, parts = [], [], []

    def boom(pos):
        for _ in range(8):
            a = random.uniform(0, math.tau)
            sp = random.uniform(40, 170)
            parts.append([Vector2(pos), Vector2(math.cos(a), math.sin(a)) * sp, 0.4, 0.4])

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        t += dt
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.MOUSEBUTTONDOWN:
                return "play"
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_f, pygame.K_F11):
                    _fullscreen()
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    return "play"
                if event.key == pygame.K_ESCAPE:
                    return "quit"
                if event.key == pygame.K_i:
                    if await codex_screen(screen, clock, font, big, small) == "quit":
                        return "quit"
                if event.key == pygame.K_l:
                    if await lore_screen(screen, clock, font, big, small) == "quit":
                        return "quit"
                if event.key == pygame.K_b:
                    if await leaderboard_screen(screen, clock, font, big, small) == "quit":
                        return "quit"
                if event.key == pygame.K_m and audio:
                    audio.toggle_music()

        cam += scroll * dt

        # Spawn drifting foes
        spawn_t -= dt
        if spawn_t <= 0:
            spawn_t = random.uniform(0.45, 0.9)
            spr = random.choice(enemy_sprites)
            img = ART.get(spr) if ART else None
            r = img.get_width() // 2 if img else 10
            side = random.choice(("right", "right", "top", "bottom"))
            if side == "top":
                pos = Vector2(random.uniform(0, WIDTH), -30)
                ev = Vector2(random.uniform(-70, -20), random.uniform(90, 150))
            elif side == "bottom":
                pos = Vector2(random.uniform(0, WIDTH), HEIGHT + 30)
                ev = Vector2(random.uniform(-70, -20), random.uniform(-150, -90))
            else:
                pos = Vector2(WIDTH + 30, random.uniform(70, HEIGHT - 130))
                ev = Vector2(random.uniform(-180, -120), random.uniform(-25, 25))
            enemies.append([pos, ev, spr, r])

        # Ship AI: head to a waypoint, swerve away from nearby foes
        if (target - ship).length() < 60:
            target = Vector2(random.uniform(WIDTH * 0.2, WIDTH * 0.6),
                             random.uniform(120, HEIGHT - 160))
        desired = target - ship
        if desired.length() > 0:
            desired = desired.normalize() * 230
        for e in enemies:
            off = ship - e[0]
            d = off.length()
            if 0 < d < 120:
                desired += off.normalize() * (120 - d) * 3.2
        vel += (desired - vel) * min(1.0, dt * 3.0)
        if vel.length() > 270:
            vel.scale_to_length(270)
        ship += vel * dt
        ship.x = max(50, min(WIDTH - 50, ship.x))
        ship.y = max(120, min(HEIGHT - 130, ship.y))
        if vel.length() > 5:
            angle = math.degrees(math.atan2(-vel.y, vel.x)) - 90

        # Auto-fire
        fire_t -= dt
        if fire_t <= 0 and enemies:
            tgt = min(enemies, key=lambda e: (e[0] - ship).length_squared())
            aim = tgt[0] - ship
            if aim.length() > 0:
                bolts.append([Vector2(ship), aim.normalize() * 620])
            fire_t = 0.2

        for b in bolts:
            b[0] += b[1] * dt
        bolts = [b for b in bolts if -20 < b[0].x < WIDTH + 20 and -20 < b[0].y < HEIGHT + 20]
        for b in list(bolts):
            for e in list(enemies):
                if (b[0] - e[0]).length_squared() <= (e[3] + 5) ** 2:
                    boom(e[0])
                    if e in enemies:
                        enemies.remove(e)
                    if b in bolts:
                        bolts.remove(b)
                    break

        for e in enemies:
            e[0] += e[1] * dt
        enemies = [e for e in enemies if -70 < e[0].x < WIDTH + 70 and -70 < e[0].y < HEIGHT + 70]
        for p in parts:
            p[0] += p[1] * dt
            p[1] *= 0.92
            p[2] -= dt
        parts = [p for p in parts if p[2] > 0]

        # ---- draw ----
        draw_starfield(screen, cam, tiles)
        for p in parts:
            r = max(1, int(3 * p[2] / p[3]))
            pygame.draw.circle(screen, (255, 200, 120), p[0], r)
        for e in enemies:
            img = ART.get(e[2]) if ART else None
            if img:
                screen.blit(img, img.get_rect(center=e[0]))
            else:
                pygame.draw.circle(screen, (235, 110, 110), e[0], e[3])
        for b in bolts:
            pygame.draw.circle(screen, PROJ_COL, b[0], 5)
        if vel.length() > 5:
            pygame.draw.circle(screen, (255, 180, 80), ship - vel.normalize() * 16, 4)
        shipimg = ART.get("player_ship") if ART else None
        if shipimg:
            blit_sprite(screen, shipimg, ship, angle=angle)
        else:
            pygame.draw.circle(screen, PLAYER_COL, ship, 13)

        title = huge.render("SWARMADA", True, WHITE)
        tx = WIDTH // 2 - title.get_width() // 2
        screen.blit(huge.render("SWARMADA", True, (18, 26, 44)), (tx + 3, 93))
        screen.blit(title, (tx, 90))
        sub = font.render("hold the line against the alien swarm", True, GOLD)
        screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, 172))
        if int(t * 2) % 2 == 0:
            pr = big.render("TAP  or  ENTER  to  PLAY", True, GOLD)
            screen.blit(pr, (WIDTH // 2 - pr.get_width() // 2, HEIGHT - 156))
        hint = small.render("ENTER play  •  B scores  •  I codex  •  L lore  •  F fullscreen  •  M music", True, DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 64))
        touch = small.render("touch: drag to move  •  tap cards to upgrade  •  ⏸ / ⛶ buttons", True, (95, 105, 128))
        screen.blit(touch, (WIDTH // 2 - touch.get_width() // 2, HEIGHT - 44))
        cred = small.render("made with pygame (LGPL) + SDL", True, (70, 78, 96))
        screen.blit(cred, (WIDTH // 2 - cred.get_width() // 2, HEIGHT - 24))
        pygame.display.flip()
        await asyncio.sleep(0)


async def main():
    global ART
    pygame.mixer.pre_init(SAMPLE_RATE, -16, 1, 512)
    pygame.init()
    # SCALED lets desktop fullscreen scale the 960x600 layout (letterboxed),
    # but pygame-web doesn't support it — use a plain surface in the browser.
    flags = 0 if sys.platform == "emscripten" else pygame.SCALED
    screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)
    pygame.display.set_caption(TITLE)
    clock = pygame.time.Clock()

    font = pygame.font.SysFont("menlo,consolas,monospace", 20)
    big = pygame.font.SysFont("menlo,consolas,monospace", 44, bold=True)
    small = pygame.font.SysFont("menlo,consolas,monospace", 15)

    ART = await load_assets(screen, big, small)
    if ART.get("icon"):
        try:
            pygame.display.set_icon(ART.get("icon"))
        except pygame.error:
            pass
    audio = Audio(music=True)

    if await title_screen(screen, clock, font, big, small, audio) == "quit":
        pygame.quit()
        return

    game = Game(screen, font, big, small, audio)

    # Offer to continue an autosaved run
    save = load_save()
    if save and await resume_prompt(screen, big, font):
        msg = font.render("Restoring run...", True, WHITE)
        screen.fill(BG)
        screen.blit(msg, (WIDTH // 2 - msg.get_width() // 2, HEIGHT // 2))
        pygame.display.flip()
        resume_game(game, save)
    else:
        clear_save()

    def input_mask(keys):
        m = 0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            m |= IN_UP
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            m |= IN_DOWN
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            m |= IN_LEFT
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            m |= IN_RIGHT
        if keys[pygame.K_1] or keys[pygame.K_KP1]:
            m |= IN_C1
        if keys[pygame.K_2] or keys[pygame.K_KP2]:
            m |= IN_C2
        if keys[pygame.K_3] or keys[pygame.K_KP3]:
            m |= IN_C3
        return m

    fade = 255.0
    acc = 0.0
    ptr_down = False
    ptr_origin = Vector2(0, 0)
    ptr_pos = Vector2(0, 0)
    tap_choice = 0
    running = True
    while running:
        frame_dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F11:
                    _fullscreen()
                elif event.key == pygame.K_ESCAPE:
                    if game.state in ("play", "levelup"):
                        save_game(game)            # keep progress so you can resume
                    running = False
                elif game.state == "enter_name":
                    if event.key == pygame.K_RETURN:
                        game.submit_score()
                    elif event.key == pygame.K_BACKSPACE:
                        game.name_input = game.name_input[:-1]
                    elif event.unicode and len(game.name_input) < 12 and (
                            event.unicode.isalnum() or event.unicode == " "):
                        game.name_input += event.unicode.upper()
                elif event.key == pygame.K_f:
                    _fullscreen()
                elif event.key == pygame.K_p and game.state == "play":
                    game.paused = not game.paused
                    if game.paused:
                        save_game(game)            # autosave on pause
                elif event.key == pygame.K_m:
                    audio.toggle_music()
                elif event.key == pygame.K_LEFTBRACKET:
                    audio.set_sfx_vol(audio.sfx_vol - 0.1)
                elif event.key == pygame.K_RIGHTBRACKET:
                    audio.set_sfx_vol(audio.sfx_vol + 0.1)
                elif event.key == pygame.K_MINUS:
                    audio.set_music_vol(audio.music_vol - 0.1)
                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                    audio.set_music_vol(audio.music_vol + 0.1)
                elif event.key == pygame.K_r and game.state == "scores":
                    clear_save()
                    game.reset()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                p = Vector2(event.pos)
                if game.state == "enter_name":
                    game.submit_score()                 # tap to submit (mobile: no keyboard)
                elif game.state == "scores":
                    clear_save()
                    game.reset()
                elif game.state == "levelup":
                    idx = _hit_card(p, len(game.choices))
                    if idx is not None:
                        tap_choice = (IN_C1, IN_C2, IN_C3)[idx]
                elif game.state == "play":
                    b = _touch_buttons()
                    if b["fs"].collidepoint(p):
                        _fullscreen()
                    elif b["pause"].collidepoint(p):
                        game.paused = not game.paused
                        if game.paused:
                            save_game(game)
                    elif game.paused:
                        vb = _vol_buttons()
                        if vb["music_dn"].collidepoint(p):
                            audio.set_music_vol(audio.music_vol - 0.1)
                        elif vb["music_up"].collidepoint(p):
                            audio.set_music_vol(audio.music_vol + 0.1)
                        elif vb["sfx_dn"].collidepoint(p):
                            audio.set_sfx_vol(audio.sfx_vol - 0.1)
                        elif vb["sfx_up"].collidepoint(p):
                            audio.set_sfx_vol(audio.sfx_vol + 0.1)
                        else:
                            game.paused = False          # tap elsewhere resumes
                    else:                                # start virtual joystick
                        ptr_down, ptr_origin, ptr_pos = True, p, p
            elif event.type == pygame.MOUSEMOTION:
                ptr_pos = Vector2(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP:
                ptr_down = False

        # Fixed-timestep deterministic simulation. Cap catch-up steps so a slow
        # frame (esp. in the browser) can't spiral into more steps -> slower.
        acc = min(acc + frame_dt, 0.25)
        mask = input_mask(pygame.key.get_pressed())
        if ptr_down and game.state == "play" and not game.paused:
            d = ptr_pos - ptr_origin                    # drag = virtual joystick (8-way)
            if d.x > 14:
                mask |= IN_RIGHT
            elif d.x < -14:
                mask |= IN_LEFT
            if d.y > 14:
                mask |= IN_DOWN
            elif d.y < -14:
                mask |= IN_UP
        mask |= tap_choice
        steps = 0
        while acc >= SIM_DT and steps < 6:
            if not game.paused and game.state in ("play", "levelup"):
                game.step(mask)
            acc -= SIM_DT
            steps += 1
            if game.state == "enter_name":
                break
        if acc > SIM_DT:
            acc = SIM_DT            # drop backlog -> graceful slow-mo, never a death spiral
        tap_choice = 0

        game.draw()
        if fade > 0:
            fade = max(0.0, fade - 430 * frame_dt)
            ov = pygame.Surface((WIDTH, HEIGHT))
            ov.set_alpha(int(fade))
            screen.blit(ov, (0, 0))
        pygame.display.flip()
        await asyncio.sleep(0)

    pygame.quit()


async def resume_prompt(screen, big, font):
    """Tiny C/N prompt at startup when an autosave exists."""
    title = big.render("CONTINUE RUN?", True, GOLD)
    hint = font.render("C / tap = continue       N = new game", True, WHITE)
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.MOUSEBUTTONDOWN:     # tap = continue (mobile)
                return True
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_f, pygame.K_F11):
                    _fullscreen()
                if event.key == pygame.K_c:
                    return True
                if event.key in (pygame.K_n, pygame.K_ESCAPE):
                    return False
        screen.fill(BG)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, HEIGHT // 2 - 50))
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT // 2 + 20))
        pygame.display.flip()
        await asyncio.sleep(0)


if __name__ == "__main__":
    asyncio.run(main())
