"""A character with a face, instead of an abstract blob.

The point of this view is that you can tell what the assistant is doing
without reading anything: it looks at you while it listens, leans in when it
hears you, glances away while it thinks, and its mouth actually moves with
the sound of its own voice rather than flapping on a timer.

There is no 3D model file to ship. The head is drawn every frame with a
painter, but it is built like a 3D thing: a yaw/pitch pair rotates it, every
feature is placed by projecting a point on a sphere through that rotation,
and the shading -- a key light from the upper left, occlusion under the brow,
nose and lower lip, a warm bounce along the jaw, and a rim in the persona's
colour -- is what sells the roundness. That costs nothing to download, scales
to any size, and each persona is a handful of numbers.

The mouth is the part people actually watch, so it is not one ellipse. Upper
and lower lips are separate shapes with a cupid's bow and a fuller lower lip;
the jaw drops (which also lengthens the chin); the corners pull wide or purse
round; teeth appear behind the upper lip and the tongue shows on the wide
vowels. Amplitude drives how far it opens, and a separate slow shape channel
drives *how* -- so speech alternates between wide, round and narrow instead of
chewing. Real visemes need phoneme timings that neither Piper nor the backend
gives us, but shape variety at syllable rate is what reads as talking.
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainterPath, QPen,
                           QRadialGradient)

# ----------------------------------------------------------------------
# per-persona looks. Everything is a ratio of head size, so it scales.
# ----------------------------------------------------------------------
DEFAULT_LOOK = {
    "skin": "#e8b58f", "skin_shadow": "#b07a55", "hair": "#3a2d28",
    "eye": "#4a3b32", "brow": "#3a2d28", "lip": "#b5726b",
    "hair_style": "short", "brow_weight": 1.0, "eye_size": 1.0,
    "stubble": 0.0, "accessory": "", "jaw": 1.0, "age": 0.0,
    "lip_fullness": 1.0, "blush": 0.25, "nose": 1.0,
}

LOOKS = {
    "alfred": {
        "skin": "#e9bf9c", "skin_shadow": "#b0805a", "hair": "#8d8f96",
        "eye": "#41607f", "brow": "#8a8c92", "lip": "#a97a72",
        "hair_style": "receding", "brow_weight": 0.95, "eye_size": 0.90,
        "accessory": "bowtie", "jaw": 1.06, "age": 0.55,
        "lip_fullness": 0.85, "blush": 0.18, "nose": 1.08,
    },
    "yui": {
        "skin": "#f7d3b8", "skin_shadow": "#cf9a78", "hair": "#4a2f2a",
        "eye": "#6b4a8f", "brow": "#5a3c34", "lip": "#d3777d",
        "hair_style": "long", "brow_weight": 0.7, "eye_size": 1.28,
        "accessory": "", "jaw": 0.88, "age": 0.0,
        "lip_fullness": 1.25, "blush": 0.55, "nose": 0.85,
    },
    "house": {
        "skin": "#ddad8c", "skin_shadow": "#a06f50", "hair": "#6f6154",
        "eye": "#4f7ea8", "brow": "#57493f", "lip": "#a46a63",
        "hair_style": "short", "brow_weight": 1.4, "eye_size": 0.95,
        "stubble": 0.85, "accessory": "", "jaw": 1.12, "age": 0.5,
        "lip_fullness": 0.9, "blush": 0.14, "nose": 1.1,
    },
}


def look_for(persona: str, accent: QColor = None) -> dict:
    """A persona's look. Unknown personas get a neutral face tinted by the
    accent colour the backend gave them, so a new persona still looks like
    its own character rather than a clone."""
    look = dict(DEFAULT_LOOK)
    look.update(LOOKS.get(persona, {}))
    if persona not in LOOKS and accent is not None:
        h, s, _, _ = accent.getHslF()
        hair = QColor()
        hair.setHslF(h if h >= 0 else 0.08, min(0.55, max(0.2, s)), 0.24)
        look["hair"] = hair.name()
        look["eye"] = accent.darker(140).name()
    return look


# ----------------------------------------------------------------------
def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _alpha(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


# mouth shapes speech moves between. (width, roundness, openness scale)
VISEMES = [
    (1.28, 0.0, 1.00),    # "ah" -- wide and open
    (0.72, 1.0, 0.95),    # "oh"/"oo" -- pursed and round
    (1.35, 0.0, 0.55),    # "ee" -- spread and narrow
    (1.00, 0.35, 0.85),   # neutral
    (0.88, 0.6, 0.70),    # "uh"
]


class Character:
    """Draws the head. Owns its own animation state; the widget calls
    advance() once per frame and paint() to render."""

    def __init__(self):
        self.look = dict(DEFAULT_LOOK)
        self.accent = QColor("#4fa3ff")
        self.state = "offline"
        self.level = 0.0            # 0..1, mic while listening, speaker while talking
        # pose
        self.yaw = 0.0              # -1 .. 1, left/right
        self.pitch = 0.0            # -1 .. 1, up/down
        self.roll = 0.0             # head tilt
        self._yaw_t = 0.0
        self._pitch_t = 0.0
        self._roll_t = 0.0
        self._sway = random.random() * math.tau
        # mouth
        self.mouth = 0.0            # 0 closed .. 1 wide (jaw drop)
        self._mouth_t = 0.0
        self.mouth_wide = 1.0       # corner spread
        self.mouth_round = 0.0      # pursed
        self._wide_t = 1.0
        self._round_t = 0.0
        self._open_scale = 1.0
        self._next_viseme = 0.0
        self.smile = 0.0            # -1 down .. 1 up at the corners
        self._smile_t = 0.0
        # eyes and brows
        self.blink = 0.0            # 0 open .. 1 shut
        self._next_blink = 2.0
        self._blink_phase = 0.0
        self.brow = 0.0             # -1 furrowed .. 1 raised
        self._brow_t = 0.0
        self.brow_skew = 0.0        # one brow up, the other down
        self._skew_t = 0.0
        self.squint = 0.0           # lower lid raise
        self._squint_t = 0.0
        self.eye_open = 1.0
        self._eye_t = 1.0
        self._gaze = [0.0, 0.0]
        self._gaze_t = [0.0, 0.0]
        self._next_gaze = 0.0
        self._t = 0.0

    # ------------------------------------------------------------------
    def set_look(self, look: dict):
        self.look = dict(DEFAULT_LOOK)
        self.look.update(look or {})

    def set_state(self, state: str):
        self.state = state
        self._next_gaze = 0.0        # re-aim immediately on a state change
        self._next_viseme = 0.0

    # ------------------------------------------------------------------
    def advance(self, dt: float):
        """Move every animated quantity toward its target for this state."""
        self._t += dt
        # every timer runs on the animation clock, not the wall clock, so a
        # dropped frame cannot desynchronise the mouth from the voice
        now = self._t
        st = self.state
        speaking = st == "speaking"
        lvl = max(0.0, min(1.0, self.level))

        # ---- where is it looking -------------------------------------
        if now >= self._next_gaze:
            if st == "thinking":
                # eyes up and away, the way people do when recalling
                self._gaze_t = [random.uniform(-0.85, 0.85), random.uniform(-0.95, -0.45)]
                self._next_gaze = now + random.uniform(0.7, 1.6)
            elif st in ("hearing", "confirm"):
                self._gaze_t = [random.uniform(-0.12, 0.12), random.uniform(-0.08, 0.08)]
                self._next_gaze = now + random.uniform(0.8, 2.0)
            elif st in ("listening", "speaking"):
                self._gaze_t = [random.uniform(-0.32, 0.32), random.uniform(-0.2, 0.15)]
                self._next_gaze = now + random.uniform(1.3, 3.2)
            else:
                self._gaze_t = [0.0, 0.28]
                self._next_gaze = now + 2.0
        for i in (0, 1):
            self._gaze[i] += (self._gaze_t[i] - self._gaze[i]) * min(1.0, dt * 8)

        # ---- head pose ------------------------------------------------
        self._sway += dt * (0.9 if st in ("listening", "muted", "offline") else 1.6)
        sway = math.sin(self._sway) * 0.05 + math.sin(self._sway * 0.37) * 0.03
        self._roll_t = math.sin(self._sway * 0.53) * 0.04
        if st == "thinking":
            self._yaw_t = self._gaze[0] * 0.38 + sway
            self._pitch_t = -0.24 + sway * 0.4
            self._roll_t += 0.10                        # head cocked
        elif st == "hearing":
            self._yaw_t = self._gaze[0] * 0.12
            self._pitch_t = 0.12 + sway * 0.3           # leaning in
            self._roll_t += 0.05
        elif st == "tool":
            self._yaw_t = -0.30 + sway                  # glancing at the work
            self._pitch_t = 0.20
        elif st == "confirm":
            self._yaw_t = sway * 0.5
            self._pitch_t = -0.07
        elif speaking:
            # a nod on the loud syllables, which is most of what makes
            # talking read as talking from across the room
            self._yaw_t = self._gaze[0] * 0.22 + sway
            self._pitch_t = sway * 0.5 + lvl * 0.10
            self._roll_t += lvl * 0.05 * math.sin(self._t * 7.3)
        elif st in ("muted", "offline"):
            self._yaw_t = sway * 0.6
            self._pitch_t = 0.32                        # head down
        else:                                            # listening
            self._yaw_t = self._gaze[0] * 0.30 + sway
            self._pitch_t = self._gaze[1] * 0.18 + sway * 0.5
        self.yaw += (self._yaw_t - self.yaw) * min(1.0, dt * 4.5)
        self.pitch += (self._pitch_t - self.pitch) * min(1.0, dt * 4.5)
        self.roll += (self._roll_t - self.roll) * min(1.0, dt * 3.5)

        # ---- mouth ----------------------------------------------------
        if speaking:
            # pick a new mouth shape at roughly syllable rate, so the jaw
            # is not the only thing moving
            if now >= self._next_viseme:
                w, rnd, sc = random.choice(VISEMES)
                self._wide_t, self._round_t, self._open_scale = w, rnd, sc
                self._next_viseme = now + random.uniform(0.11, 0.26)
            self._mouth_t = min(1.0, (0.05 + lvl * 1.75) * self._open_scale)
            self._smile_t = 0.12
        elif st == "confirm":
            self._mouth_t, self._wide_t, self._round_t = 0.10, 0.95, 0.25
            self._smile_t = 0.0
        elif st == "thinking":
            self._mouth_t, self._wide_t, self._round_t = 0.02, 0.80, 0.45
            self._smile_t = -0.25                        # slight pursed frown
        elif st == "hearing":
            self._mouth_t, self._wide_t, self._round_t = 0.03, 1.05, 0.0
            self._smile_t = 0.35
        elif st == "listening":
            self._mouth_t, self._wide_t, self._round_t = 0.0, 1.0, 0.0
            self._smile_t = 0.3
        elif st == "tool":
            self._mouth_t, self._wide_t, self._round_t = 0.0, 0.9, 0.3
            self._smile_t = 0.0
        else:
            self._mouth_t, self._wide_t, self._round_t = 0.0, 0.95, 0.0
            self._smile_t = -0.1
        # opening is quick, closing slower -- a jaw cannot snap shut
        rate = 34 if self._mouth_t > self.mouth else 15
        self.mouth += (self._mouth_t - self.mouth) * min(1.0, dt * rate)
        self.mouth_wide += (self._wide_t - self.mouth_wide) * min(1.0, dt * 16)
        self.mouth_round += (self._round_t - self.mouth_round) * min(1.0, dt * 16)
        self.smile += (self._smile_t - self.smile) * min(1.0, dt * 5)

        # ---- eyes -----------------------------------------------------
        if st in ("muted", "offline"):
            self._eye_t, self._squint_t = 0.10, 0.0
        elif st == "hearing":
            self._eye_t, self._squint_t = 1.24, 0.0
        elif st == "confirm":
            self._eye_t, self._squint_t = 1.32, 0.0
        elif st == "thinking":
            self._eye_t, self._squint_t = 0.80, 0.45     # narrowed, concentrating
        elif st == "tool":
            self._eye_t, self._squint_t = 0.88, 0.3
        elif speaking:
            self._eye_t, self._squint_t = 1.0, 0.12 + self.smile * 0.25
        else:
            self._eye_t, self._squint_t = 1.0, self.smile * 0.30
        self.eye_open += (self._eye_t - self.eye_open) * min(1.0, dt * 6)
        self.squint += (self._squint_t - self.squint) * min(1.0, dt * 5)

        if st in ("muted", "offline"):
            self.blink = 0.0
        else:
            if self._blink_phase > 0:
                self._blink_phase = max(0.0, self._blink_phase - dt / 0.085)
                self.blink = math.sin(min(1.0, 1 - self._blink_phase) * math.pi)
            elif now >= self._next_blink:
                self._blink_phase = 1.0
                self._next_blink = now + random.uniform(2.2, 6.0)
            else:
                self.blink = 0.0

        # ---- brow -----------------------------------------------------
        self._brow_t = {"thinking": -0.15, "confirm": 0.8, "hearing": 0.5,
                        "tool": -0.35, "offline": -0.15, "muted": -0.1}.get(st, 0.05)
        # one brow up is "pondering"; both down is "angry", which is not
        # what thinking should look like
        self._skew_t = {"thinking": 0.95, "confirm": 0.3, "tool": 0.55}.get(st, 0.0)
        if speaking:
            self._brow_t = 0.10 + lvl * 0.55
        self.brow += (self._brow_t - self.brow) * min(1.0, dt * 6)
        self.brow_skew += (self._skew_t - self.brow_skew) * min(1.0, dt * 5)

    # ------------------------------------------------------------------
    # projection: a point on the head's sphere, through the current pose
    # ------------------------------------------------------------------
    def _project(self, u, v, cx, cy, r):
        """(u, v) in -1..1 across the face -> screen point, plus a depth
        factor used to shrink features as they rotate away."""
        ay, ap = self.yaw * 0.85, self.pitch * 0.7
        w = math.sqrt(max(0.0, 1.0 - min(1.0, u * u * 0.55 + v * v * 0.55)))
        x = u * math.cos(ay) + w * math.sin(ay) * 0.42
        y = v * math.cos(ap) - w * math.sin(ap) * 0.42
        # head roll
        ca, sa = math.cos(self.roll), math.sin(self.roll)
        x, y = x * ca - y * sa, x * sa + y * ca
        depth = math.cos(ay - u * 0.7) * math.cos(ap - v * 0.5)
        return QPointF(cx + x * r, cy + y * r), max(0.25, depth)

    # ------------------------------------------------------------------
    def paint(self, p, cx, cy, size, dim=False):
        """size: the head's radius in pixels."""
        r = size
        look = self.look
        skin = QColor(look["skin"])
        shadow = QColor(look["skin_shadow"])
        if dim:
            grey = QColor("#8d8f96")
            skin = _mix(skin, grey, 0.62)
            shadow = _mix(shadow, grey, 0.55)

        hx = cx + self.yaw * r * 0.15
        hy = cy + self.pitch * r * 0.11

        self._draw_glow(p, hx, hy, r, dim)
        if look.get("hair_style") == "long":
            self._draw_long_hair(p, hx, hy, r, look, dim)
        self._draw_neck_and_shoulders(p, cx, cy, r, skin, shadow, look, dim)
        self._draw_ears(p, hx, hy, r, skin, shadow)
        self._draw_head(p, hx, hy, r, skin, shadow, look)
        self._draw_face_shading(p, hx, hy, r, skin, shadow, look, dim)
        if look.get("stubble"):
            self._draw_stubble(p, hx, hy, r, look)
        self._draw_hair(p, hx, hy, r, look, dim)
        self._draw_brows(p, hx, hy, r, look, dim)
        self._draw_eyes(p, hx, hy, r, look, skin, shadow, dim)
        self._draw_nose(p, hx, hy, r, skin, shadow, look)
        self._draw_mouth(p, hx, hy, r, look, skin, shadow, dim)
        self._draw_key_light(p, hx, hy, r, dim)
        if self.state in ("thinking", "tool"):
            self._draw_busy(p, hx, hy, r)
        if self.state == "hearing":
            self._draw_listening_rings(p, hx, hy, r)

    # ------------------------------------------------------------------
    def _state_colour(self) -> QColor:
        return QColor({
            "hearing": "#4fd1a1", "thinking": "#c98cff",
            "tool": "#ffb84f", "confirm": "#ff6b6b",
        }.get(self.state, self.accent.name()))

    def _draw_glow(self, p, cx, cy, r, dim):
        col = self._state_colour()
        g = QRadialGradient(QPointF(cx, cy), r * 2.6)
        a = 0.10 + (0.0 if dim else self.level * 0.30)
        g.setColorAt(0.0, _alpha(col, a * (0.4 if dim else 1.0)))
        g.setColorAt(1.0, _alpha(col, 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), r * 2.6, r * 2.6)

    # --- head ------------------------------------------------------------
    def _head_outline(self, cx, cy, r, jaw, drop):
        """Skull, cheekbones, jaw, chin. `drop` lengthens the chin as the
        mouth opens, which is what a real jaw does."""
        path = QPainterPath()
        top = cy - r * 1.04
        chin = cy + r * (0.97 * jaw + drop)
        path.moveTo(cx - r * 0.87, cy - r * 0.06)
        # skull
        path.cubicTo(cx - r * 0.95, top, cx + r * 0.95, top, cx + r * 0.87, cy - r * 0.06)
        # cheekbone -> jaw corner
        path.cubicTo(cx + r * 0.86, cy + r * 0.22, cx + r * 0.74, cy + r * 0.44 * jaw,
                     cx + r * 0.60, cy + r * 0.58 * jaw)
        # jaw -> chin
        path.cubicTo(cx + r * 0.44, cy + r * 0.82 * jaw, cx + r * 0.24, chin, cx, chin)
        path.cubicTo(cx - r * 0.24, chin, cx - r * 0.44, cy + r * 0.82 * jaw,
                     cx - r * 0.60, cy + r * 0.58 * jaw)
        path.cubicTo(cx - r * 0.74, cy + r * 0.44 * jaw, cx - r * 0.86, cy + r * 0.22,
                     cx - r * 0.87, cy - r * 0.06)
        path.closeSubpath()
        return path

    def _draw_head(self, p, cx, cy, r, skin, shadow, look):
        jaw = look.get("jaw", 1.0)
        self._jaw_drop = self.mouth * 0.11
        path = self._head_outline(cx, cy, r, jaw, self._jaw_drop)
        self._head_path = path

        lx = cx - r * 0.44 + self.yaw * r * 0.26
        ly = cy - r * 0.56 + self.pitch * r * 0.2
        g = QRadialGradient(QPointF(lx, ly), r * 2.15)
        g.setColorAt(0.0, skin.lighter(124))
        g.setColorAt(0.42, skin)
        g.setColorAt(0.82, _mix(skin, shadow, 0.7))
        g.setColorAt(1.0, shadow.darker(108))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(path)

    def _draw_ears(self, p, cx, cy, r, skin, shadow):
        for side in (-1, 1):
            vis = 1.0 - max(0.0, self.yaw * side * 1.15)
            if vis <= 0.06:
                continue
            ex = cx + side * r * 0.86 - self.yaw * r * 0.20 * side
            ey = cy + r * 0.10 + self.pitch * r * 0.12
            p.setPen(Qt.NoPen)
            p.setBrush(_mix(skin, shadow, 0.30))
            p.drawEllipse(QPointF(ex, ey), r * 0.15 * vis, r * 0.22)
            p.setBrush(_mix(skin, shadow, 0.62))
            p.drawEllipse(QPointF(ex + side * r * 0.02, ey), r * 0.075 * vis, r * 0.13)

    def _draw_face_shading(self, p, cx, cy, r, skin, shadow, look, dim):
        """Cheekbones, temples, the hollow under the cheek and the warm
        bounce along the jaw. This is where most of the realism lives."""
        if not hasattr(self, "_head_path"):
            return
        p.save()
        p.setClipPath(self._head_path)
        p.setPen(Qt.NoPen)
        deep = _mix(shadow, QColor("#4a2a1c"), 0.35)

        # temples
        for side in (-1, 1):
            g = QRadialGradient(QPointF(cx + side * r * 0.78, cy - r * 0.42), r * 0.55)
            g.setColorAt(0.0, _alpha(deep, 0.20))
            g.setColorAt(1.0, _alpha(deep, 0.0))
            p.setBrush(QBrush(g))
            p.drawRect(QRectF(cx - r * 1.2, cy - r * 1.2, r * 2.4, r * 2.4))

        # hollow under the cheekbones
        for side in (-1, 1):
            g = QRadialGradient(QPointF(cx + side * r * 0.52, cy + r * 0.34), r * 0.44)
            g.setColorAt(0.0, _alpha(deep, 0.22))
            g.setColorAt(1.0, _alpha(deep, 0.0))
            p.setBrush(QBrush(g))
            p.drawRect(QRectF(cx - r * 1.2, cy - r * 1.2, r * 2.4, r * 2.4))

        # cheek colour, lifted when smiling
        blush = look.get("blush", 0.25) * (0.3 if dim else 1.0)
        if blush > 0:
            for side in (-1, 1):
                pt, _d = self._project(side * 0.52, 0.20 - self.smile * 0.05, cx, cy, r)
                g = QRadialGradient(pt, r * 0.36)
                warm = _mix(QColor(look["lip"]), skin, 0.45)
                g.setColorAt(0.0, _alpha(warm, 0.30 * blush + self.smile * 0.06))
                g.setColorAt(1.0, _alpha(warm, 0.0))
                p.setBrush(QBrush(g))
                p.drawRect(QRectF(cx - r * 1.2, cy - r * 1.2, r * 2.4, r * 2.4))

        # warm bounce along the jaw
        g = QLinearGradient(cx, cy + r * 0.55, cx, cy + r * 1.05)
        g.setColorAt(0.0, _alpha(skin, 0.0))
        g.setColorAt(1.0, _alpha(_mix(skin, QColor("#ffceac"), 0.5), 0.22 if not dim else 0.0))
        p.setBrush(QBrush(g))
        p.drawRect(QRectF(cx - r * 1.2, cy, r * 2.4, r * 1.4))

        # brow ridge shadow. The gradient has to reach zero at BOTH ends of
        # the rectangle it fills; a stop short of the edge is clamped, and
        # the clamp shows up as a hard line straight across the forehead.
        g = QLinearGradient(cx, cy - r * 0.44, cx, cy - r * 0.04)
        g.setColorAt(0.0, _alpha(deep, 0.0))
        g.setColorAt(0.45, _alpha(deep, 0.17))
        g.setColorAt(1.0, _alpha(deep, 0.0))
        p.setBrush(QBrush(g))
        p.drawRect(QRectF(cx - r * 1.2, cy - r * 0.44, r * 2.4, r * 0.40))
        p.restore()

    def _draw_key_light(self, p, cx, cy, r, dim):
        """One pass of light and rim over everything, last, so the whole
        face sits under the same lamp."""
        if not hasattr(self, "_head_path"):
            return
        p.save()
        p.setClipPath(self._head_path)
        p.setPen(Qt.NoPen)
        lx = cx - r * 0.52 + self.yaw * r * 0.3
        ly = cy - r * 0.72 + self.pitch * r * 0.25
        g = QRadialGradient(QPointF(lx, ly), r * 2.25)
        g.setColorAt(0.0, QColor(255, 249, 238, 0 if dim else 52))
        g.setColorAt(0.5, QColor(255, 255, 255, 0))
        g.setColorAt(1.0, QColor(30, 18, 12, 88))
        p.setBrush(QBrush(g))
        p.drawPath(self._head_path)
        # rim light on the far side, in the persona's colour
        side = 1 if self.yaw <= 0 else -1
        rg = QLinearGradient(cx + side * r * 0.30, cy, cx + side * r * 1.02, cy)
        rg.setColorAt(0.0, QColor(255, 255, 255, 0))
        rg.setColorAt(1.0, _alpha(self._state_colour(), 0.0 if dim else 0.30))
        p.setBrush(QBrush(rg))
        p.drawPath(self._head_path)
        p.restore()

    # --- hair -------------------------------------------------------------
    HAIRLINES = {
        # (temple height, centre height) as multiples of r above centre
        "short": (0.30, 0.52),
        "receding": (0.60, 0.54),
        "long": (0.12, 0.52),
        "bald": (-0.30, -0.55),      # only a horseshoe low on the sides
    }

    def _draw_hair(self, p, cx, cy, r, look, dim):
        """Hair is everything on the skull above the hairline, clipped to
        the head so it always follows the skull."""
        if not hasattr(self, "_head_path"):
            return
        hair = QColor(look["hair"])
        if dim:
            hair = _mix(hair, QColor("#8d8f96"), 0.5)
        style = look.get("hair_style", "short")

        if style == "bald":
            # a horseshoe low around the sides and back, bare on top. This
            # cannot be expressed as "everything above a hairline", so it is
            # a rim: the head minus an inset copy of itself, kept below the
            # crown.
            outer = QPainterPath()
            outer.addEllipse(QPointF(cx, cy - r * 0.06), r * 0.93, r * 1.00)
            inner = QPainterPath()
            inner.addEllipse(QPointF(cx, cy - r * 0.10), r * 0.855, r * 0.93)
            # keep the rim only over the temples and above the ears. Clipping
            # it with a rectangle instead would draw a straight line across
            # the forehead, which looks like a visor.
            lobes = QPainterPath()
            for side in (-1, 1):
                lobe = QPainterPath()
                lobe.addEllipse(QPointF(cx + side * r * 0.62, cy - r * 0.06),
                                r * 0.44, r * 0.50)
                lobes = lobes.united(lobe)
            path = outer.subtracted(inner).intersected(lobes).intersected(self._head_path)
            if path.isEmpty():
                return
            p.setPen(Qt.NoPen)
            g = QLinearGradient(cx - r * 0.8, cy - r * 0.3, cx + r * 0.8, cy + r * 0.3)
            g.setColorAt(0.0, hair.lighter(132))
            g.setColorAt(0.5, hair)
            g.setColorAt(1.0, hair.darker(124))
            p.setBrush(QBrush(g))
            p.drawPath(path)
            return

        temple, centre = self.HAIRLINES.get(style, self.HAIRLINES["short"])

        region = QPainterPath()
        region.moveTo(cx - r * 2.0, cy + r * temple)
        region.lineTo(cx - r * 2.0, cy - r * 2.0)
        region.lineTo(cx + r * 2.0, cy - r * 2.0)
        region.lineTo(cx + r * 2.0, cy + r * temple)
        region.cubicTo(cx + r * 0.58, cy - r * (centre - 0.16),
                       cx + r * 0.30, cy - r * centre, cx, cy - r * centre)
        region.cubicTo(cx - r * 0.30, cy - r * centre,
                       cx - r * 0.58, cy - r * (centre - 0.16),
                       cx - r * 2.0, cy + r * temple)
        region.closeSubpath()
        path = region.intersected(self._head_path)
        if path.isEmpty():
            return

        p.setPen(Qt.NoPen)
        g = QLinearGradient(cx - r * 0.7, cy - r * 1.05, cx + r * 0.7, cy - r * 0.15)
        g.setColorAt(0.0, hair.lighter(138))
        g.setColorAt(0.5, hair)
        g.setColorAt(1.0, hair.darker(126))
        p.setBrush(QBrush(g))
        p.drawPath(path)

        p.save()
        p.setClipPath(path)
        # strands, so it is not a flat cap
        # a few soft strands. Strong evenly-spaced lines read as a knitted
        # cap, so these stay faint and unevenly spaced.
        pen = QPen(_alpha(hair.darker(128), 0.16))
        pen.setWidthF(max(0.7, r * 0.010))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for u in (-0.82, -0.55, -0.24, 0.05, 0.34, 0.61, 0.86):
            sp = QPainterPath()
            sp.moveTo(cx + u * r * 0.78, cy - r * 1.02)
            sp.quadTo(cx + (u + 0.10) * r * 1.00, cy - r * 0.58,
                      cx + (u + 0.06) * r * 0.92, cy + r * 0.05)
            p.drawPath(sp)
        p.setPen(Qt.NoPen)
        age = look.get("age", 0.0)
        if age > 0.25:                       # grey coming in at the temples
            grey = QLinearGradient(cx - r, cy, cx + r, cy)
            w = QColor(238, 238, 240, int(110 * age))
            grey.setColorAt(0.0, w)
            grey.setColorAt(0.35, QColor(238, 238, 240, 0))
            grey.setColorAt(0.65, QColor(238, 238, 240, 0))
            grey.setColorAt(1.0, w)
            p.setBrush(QBrush(grey))
            p.drawPath(path)
        shine = QRadialGradient(QPointF(cx - r * 0.28 + self.yaw * r * 0.3,
                                        cy - r * 0.80), r * 0.8)
        shine.setColorAt(0.0, QColor(255, 255, 255, 0 if dim else 44))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(shine))
        p.drawPath(path)
        p.restore()

    def _draw_long_hair(self, p, cx, cy, r, look, dim):
        hair = QColor(look["hair"])
        if dim:
            hair = _mix(hair, QColor("#8d8f96"), 0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(hair.darker(120))
        path = QPainterPath()
        path.moveTo(cx - r * 1.04, cy + r * 1.24)
        path.cubicTo(cx - r * 1.26, cy - r * 0.62, cx + r * 1.26, cy - r * 0.62,
                     cx + r * 1.04, cy + r * 1.24)
        path.cubicTo(cx + r * 0.60, cy + r * 0.86, cx - r * 0.60, cy + r * 0.86,
                     cx - r * 1.04, cy + r * 1.24)
        path.closeSubpath()
        p.drawPath(path)

    # --- brows ------------------------------------------------------------
    def _draw_brows(self, p, cx, cy, r, look, dim):
        col = QColor(look["brow"])
        if dim:
            col = _mix(col, QColor("#8d8f96"), 0.5)
        weight = look.get("brow_weight", 1.0)
        base = self.brow * r * 0.10
        for side in (-1, 1):
            raise_ = base + self.brow_skew * r * 0.085 * (1 if side < 0 else -0.45)
            outer, do = self._project(side * 0.40, -0.30, cx, cy, r)
            inner, di = self._project(side * 0.09, -0.28, cx, cy, r)
            if do < 0.26:
                continue
            drop = -self.brow * r * 0.05 * (1 if self.brow < 0 else 0.4)
            if side > 0:
                drop += self.brow_skew * r * 0.04
            o = QPointF(outer.x(), outer.y() - raise_)
            i = QPointF(inner.x(), inner.y() - raise_ + drop)
            thick = r * 0.075 * weight * do
            # a filled, tapered shape reads as hair; a stroked line reads
            # as a drawn-on line
            path = QPainterPath()
            mid_y = (o.y() + i.y()) / 2 - r * 0.055
            path.moveTo(i)
            path.quadTo(QPointF((o.x() + i.x()) / 2, mid_y), o)
            path.quadTo(QPointF((o.x() + i.x()) / 2, mid_y + thick * 0.9),
                        QPointF(i.x(), i.y() + thick * 0.55))
            path.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawPath(path)

    # --- eyes -------------------------------------------------------------
    def _eye_path(self, c, ew, eh, lid, squint, side):
        """An almond, not an ellipse: a tall upper lid arc and a shallower
        lower one, meeting at the corners."""
        path = QPainterPath()
        left = QPointF(c.x() - ew, c.y() + eh * 0.10)
        right = QPointF(c.x() + ew, c.y() - eh * 0.06 * side)
        upper = c.y() - eh * lid
        lower = c.y() + eh * (1.0 - squint * 0.55)
        path.moveTo(left)
        path.cubicTo(QPointF(c.x() - ew * 0.55, upper),
                     QPointF(c.x() + ew * 0.55, upper), right)
        path.cubicTo(QPointF(c.x() + ew * 0.50, lower),
                     QPointF(c.x() - ew * 0.50, lower), left)
        path.closeSubpath()
        return path

    def _draw_eyes(self, p, cx, cy, r, look, skin, shadow, dim):
        size = look.get("eye_size", 1.0)
        iris_col = QColor(look["eye"])
        if dim:
            iris_col = _mix(iris_col, QColor("#8d8f96"), 0.6)
        lid = max(0.06, (1.0 - self.blink) * self.eye_open)
        for side in (-1, 1):
            c, depth = self._project(side * 0.31, -0.07, cx, cy, r)
            if depth < 0.24:
                continue
            ew = r * 0.215 * size * depth
            eh = r * 0.135 * size

            # socket
            p.setPen(Qt.NoPen)
            g = QRadialGradient(QPointF(c.x(), c.y() - eh * 0.5), ew * 2.1)
            g.setColorAt(0.0, _alpha(_mix(shadow, QColor("#4a2a1c"), 0.4), 0.26))
            g.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(g))
            p.drawEllipse(c, ew * 1.85, eh * 2.3)

            eye = self._eye_path(c, ew, eh, lid, self.squint, side)
            p.setBrush(QColor("#f3ede6") if not dim else QColor("#d6d6da"))
            p.drawPath(eye)

            if lid > 0.14:
                p.save()
                p.setClipPath(eye)
                gx = c.x() + self._gaze[0] * ew * 0.44
                gy = c.y() + self._gaze[1] * eh * 0.55
                ir = min(ew * 0.60, eh * 1.20)
                # iris with a limbal ring and radial fibres
                ig = QRadialGradient(QPointF(gx - ir * 0.18, gy - ir * 0.22), ir * 1.5)
                ig.setColorAt(0.0, iris_col.lighter(165))
                ig.setColorAt(0.55, iris_col)
                ig.setColorAt(1.0, iris_col.darker(175))
                p.setBrush(QBrush(ig))
                p.drawEllipse(QPointF(gx, gy), ir, ir)
                pen = QPen(_alpha(iris_col.darker(190), 0.55))
                pen.setWidthF(max(0.6, ir * 0.10))
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(gx, gy), ir * 0.96, ir * 0.96)
                pen.setWidthF(max(0.4, ir * 0.05))
                pen.setColor(_alpha(iris_col.lighter(150), 0.35))
                p.setPen(pen)
                for k in range(10):
                    a = k / 10 * math.tau
                    p.drawLine(QPointF(gx + math.cos(a) * ir * 0.38, gy + math.sin(a) * ir * 0.38),
                               QPointF(gx + math.cos(a) * ir * 0.88, gy + math.sin(a) * ir * 0.88))
                p.setPen(Qt.NoPen)
                # pupil widens a little in the dark states
                pr = ir * (0.46 - self.squint * 0.05)
                p.setBrush(QColor(12, 10, 9))
                p.drawEllipse(QPointF(gx, gy), pr, pr)
                p.setBrush(QColor(255, 255, 255, 215))
                p.drawEllipse(QPointF(gx - ir * 0.30, gy - ir * 0.36), ir * 0.19, ir * 0.19)
                p.setBrush(QColor(255, 255, 255, 90))
                p.drawEllipse(QPointF(gx + ir * 0.26, gy + ir * 0.28), ir * 0.10, ir * 0.10)
                # shadow cast by the upper lid
                sg = QLinearGradient(c.x(), c.y() - eh * lid, c.x(), c.y() + eh * 0.2)
                sg.setColorAt(0.0, QColor(0, 0, 0, 78))
                sg.setColorAt(1.0, QColor(0, 0, 0, 0))
                p.setBrush(QBrush(sg))
                p.drawPath(eye)
                p.restore()

            # lash line along the upper lid
            lash = QPainterPath()
            lash.moveTo(c.x() - ew, c.y() + eh * 0.10)
            lash.cubicTo(QPointF(c.x() - ew * 0.55, c.y() - eh * lid),
                         QPointF(c.x() + ew * 0.55, c.y() - eh * lid),
                         QPointF(c.x() + ew, c.y() - eh * 0.06 * side))
            pen = QPen(_alpha(QColor(look["brow"]).darker(140), 0.9))
            pen.setWidthF(max(1.0, r * 0.020 * (1.4 if size > 1.1 else 1.0)))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(lash)
            # lower lid, lighter
            pen.setColor(_alpha(shadow.darker(115), 0.5))
            pen.setWidthF(max(0.7, r * 0.011))
            p.setPen(pen)
            low = QPainterPath()
            low.moveTo(c.x() - ew, c.y() + eh * 0.10)
            low.cubicTo(QPointF(c.x() - ew * 0.50, c.y() + eh * (1.0 - self.squint * 0.55)),
                        QPointF(c.x() + ew * 0.50, c.y() + eh * (1.0 - self.squint * 0.55)),
                        QPointF(c.x() + ew, c.y() - eh * 0.06 * side))
            p.drawPath(low)
            p.setPen(Qt.NoPen)

    # --- nose -------------------------------------------------------------
    def _draw_nose(self, p, cx, cy, r, skin, shadow, look):
        scale = look.get("nose", 1.0)
        bridge, db = self._project(0.0, -0.06, cx, cy, r)
        tip, dt = self._project(0.0, 0.22, cx, cy, r)
        if db < 0.24:
            return
        side = 1 if self.yaw >= 0 else -1
        w = r * 0.115 * scale

        p.save()
        if hasattr(self, "_head_path"):
            p.setClipPath(self._head_path)
        p.setPen(Qt.NoPen)
        # shadow down the far side of the bridge
        sg = QLinearGradient(bridge.x() - side * w * 1.5, 0, bridge.x() + side * w * 1.6, 0)
        deep = _mix(shadow, QColor("#5a3020"), 0.35)
        sg.setColorAt(0.0, _alpha(deep, 0.0))
        sg.setColorAt(1.0, _alpha(deep, 0.30))
        p.setBrush(QBrush(sg))
        path = QPainterPath()
        path.moveTo(bridge.x() - side * w * 0.2, bridge.y() - r * 0.05)
        path.quadTo(QPointF(tip.x() + side * w * 1.1, tip.y() - r * 0.10),
                    QPointF(tip.x() + side * w * 0.9, tip.y() + r * 0.03))
        path.quadTo(QPointF(tip.x(), tip.y() + r * 0.06),
                    QPointF(bridge.x() - side * w * 0.2, bridge.y() - r * 0.05))
        p.drawPath(path)

        # ball of the nose: a lit bump
        bg = QRadialGradient(QPointF(tip.x() - r * 0.03, tip.y() - r * 0.03), w * 1.9)
        bg.setColorAt(0.0, _alpha(skin.lighter(126), 0.85))
        bg.setColorAt(1.0, _alpha(skin, 0.0))
        p.setBrush(QBrush(bg))
        p.drawEllipse(tip, w * 1.5, w * 1.15)

        # under-nose shadow and nostrils
        p.setBrush(_alpha(deep, 0.34))
        p.drawEllipse(QPointF(tip.x(), tip.y() + r * 0.045), w * 1.35, w * 0.42)
        p.setBrush(_alpha(QColor(40, 22, 16), 0.72))
        for s in (-1, 1):
            p.drawEllipse(QPointF(tip.x() + s * w * 0.72, tip.y() + r * 0.028),
                          w * 0.32, w * 0.22)
        p.restore()

    # --- mouth ------------------------------------------------------------
    def _draw_mouth(self, p, cx, cy, r, look, skin, shadow, dim):
        c, depth = self._project(0.0, 0.47 + self._jaw_drop * 0.55, cx, cy, r)
        if depth < 0.20:
            return
        lip_col = QColor(look["lip"])
        if dim:
            lip_col = _mix(lip_col, QColor("#8d8f96"), 0.55)
        full = look.get("lip_fullness", 1.0)

        open_ = self.mouth
        wide = self.mouth_wide * (1.0 - self.mouth_round * 0.34)
        w = r * 0.245 * depth * wide
        # rounder mouths are taller for the same jaw drop
        h = r * 0.30 * open_ * (1.0 + self.mouth_round * 0.30)
        corner_lift = self.smile * r * 0.055
        upper_h = r * 0.055 * full
        lower_h = r * 0.075 * full

        left = QPointF(c.x() - w, c.y() - corner_lift)
        right = QPointF(c.x() + w, c.y() - corner_lift)
        # inner edges of the lips (the opening)
        in_up = c.y() - h * 0.42
        in_lo = c.y() + h * 0.58

        p.setPen(Qt.NoPen)

        # --- cavity -----------------------------------------------------
        if open_ > 0.035:
            cavity = QPainterPath()
            cavity.moveTo(left)
            cavity.cubicTo(QPointF(c.x() - w * 0.5, in_up), QPointF(c.x() + w * 0.5, in_up), right)
            cavity.cubicTo(QPointF(c.x() + w * 0.55, in_lo), QPointF(c.x() - w * 0.55, in_lo), left)
            cavity.closeSubpath()
            g = QRadialGradient(QPointF(c.x(), c.y() + h * 0.35), max(1.0, w * 1.5))
            g.setColorAt(0.0, QColor(64, 22, 24))
            g.setColorAt(1.0, QColor(24, 8, 10))
            p.setBrush(QBrush(g))
            p.drawPath(cavity)

            p.save()
            p.setClipPath(cavity)
            # upper teeth, tucked just under the top lip
            teeth_h = min(h * 0.42, r * 0.075)
            if teeth_h > r * 0.012:
                p.setBrush(QColor("#f6f2ec") if not dim else QColor("#d8d8dc"))
                tp = QPainterPath()
                tp.moveTo(c.x() - w * 0.86, in_up - r * 0.01)
                tp.cubicTo(QPointF(c.x() - w * 0.45, in_up + teeth_h * 0.9),
                           QPointF(c.x() + w * 0.45, in_up + teeth_h * 0.9),
                           QPointF(c.x() + w * 0.86, in_up - r * 0.01))
                tp.closeSubpath()
                p.drawPath(tp)
                pen = QPen(_alpha(QColor(120, 110, 105), 0.35))
                pen.setWidthF(max(0.5, r * 0.006))
                p.setPen(pen)
                for k in (-0.5, 0.0, 0.5):
                    p.drawLine(QPointF(c.x() + k * w * 0.62, in_up),
                               QPointF(c.x() + k * w * 0.62, in_up + teeth_h * 0.8))
                p.setPen(Qt.NoPen)
            # lower teeth on a wide drop
            if open_ > 0.55:
                p.setBrush(QColor(226, 219, 210, 210))
                bp = QPainterPath()
                bp.moveTo(c.x() - w * 0.7, in_lo + r * 0.01)
                bp.cubicTo(QPointF(c.x() - w * 0.4, in_lo - h * 0.22),
                           QPointF(c.x() + w * 0.4, in_lo - h * 0.22),
                           QPointF(c.x() + w * 0.7, in_lo + r * 0.01))
                bp.closeSubpath()
                p.drawPath(bp)
            # tongue
            if open_ > 0.42:
                tg = QRadialGradient(QPointF(c.x(), in_lo - h * 0.05), w)
                tg.setColorAt(0.0, QColor(178, 84, 88))
                tg.setColorAt(1.0, QColor(132, 52, 58))
                p.setBrush(QBrush(tg))
                p.drawEllipse(QPointF(c.x(), in_lo - h * 0.02), w * 0.62, h * 0.30)
            p.restore()

        # --- lips -------------------------------------------------------
        lip_light = _mix(lip_col, QColor("#ffffff"), 0.28)
        lip_dark = lip_col.darker(140)

        # upper lip: cupid's bow above, inner edge below
        up = QPainterPath()
        up.moveTo(left)
        up.cubicTo(QPointF(c.x() - w * 0.62, c.y() - upper_h * 1.5 - corner_lift * 0.4),
                   QPointF(c.x() - w * 0.22, c.y() - upper_h * 1.15),
                   QPointF(c.x(), c.y() - upper_h * 0.72))          # dip of the bow
        up.cubicTo(QPointF(c.x() + w * 0.22, c.y() - upper_h * 1.15),
                   QPointF(c.x() + w * 0.62, c.y() - upper_h * 1.5 - corner_lift * 0.4),
                   right)
        up.cubicTo(QPointF(c.x() + w * 0.5, in_up), QPointF(c.x() - w * 0.5, in_up), left)
        up.closeSubpath()
        ug = QLinearGradient(c.x(), c.y() - upper_h * 1.6, c.x(), in_up)
        ug.setColorAt(0.0, lip_dark)
        ug.setColorAt(1.0, lip_col)
        p.setBrush(QBrush(ug))
        p.drawPath(up)

        # lower lip: inner edge above, full curve below
        lo = QPainterPath()
        lo.moveTo(left)
        lo.cubicTo(QPointF(c.x() - w * 0.55, in_lo), QPointF(c.x() + w * 0.55, in_lo), right)
        lo.cubicTo(QPointF(c.x() + w * 0.60, in_lo + lower_h * 1.5),
                   QPointF(c.x() - w * 0.60, in_lo + lower_h * 1.5), left)
        lo.closeSubpath()
        lg = QLinearGradient(c.x(), in_lo, c.x(), in_lo + lower_h * 1.6)
        lg.setColorAt(0.0, lip_col)
        lg.setColorAt(0.45, lip_light)
        lg.setColorAt(1.0, lip_dark)
        p.setBrush(QBrush(lg))
        p.drawPath(lo)

        # shadow under the lower lip, and the philtrum above the upper
        p.save()
        if hasattr(self, "_head_path"):
            p.setClipPath(self._head_path)
        deep = _mix(shadow, QColor("#5a3020"), 0.4)
        # radial, not a rectangle with a linear gradient: a linear one that
        # does not reach zero at the edges leaves a visible pale box on the
        # chin, which is exactly what it looks like
        sg = QRadialGradient(QPointF(c.x(), in_lo + lower_h * 1.5), max(1.0, w * 1.15))
        sg.setColorAt(0.0, _alpha(deep, 0.34))
        sg.setColorAt(0.55, _alpha(deep, 0.18))
        sg.setColorAt(1.0, _alpha(deep, 0.0))
        p.setBrush(QBrush(sg))
        p.drawEllipse(QPointF(c.x(), in_lo + lower_h * 1.5), w * 1.15, lower_h * 2.0)
        # philtrum: the groove between nose and upper lip
        pg = QRadialGradient(QPointF(c.x(), c.y() - r * 0.10), max(1.0, r * 0.10))
        pg.setColorAt(0.0, _alpha(deep, 0.20))
        pg.setColorAt(1.0, _alpha(deep, 0.0))
        p.setBrush(QBrush(pg))
        p.drawEllipse(QPointF(c.x(), c.y() - r * 0.10), r * 0.055, r * 0.10)
        p.restore()

        # corner creases, which is what makes a smile read as a smile
        if abs(self.smile) > 0.12:
            pen = QPen(_alpha(shadow.darker(120), 0.35 * abs(self.smile)))
            pen.setWidthF(max(0.8, r * 0.014))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            for side in (-1, 1):
                cr = QPainterPath()
                cr.moveTo(c.x() + side * w * 0.98, c.y() - corner_lift)
                cr.quadTo(QPointF(c.x() + side * w * 1.24, c.y() - corner_lift - self.smile * r * 0.05),
                          QPointF(c.x() + side * w * 1.30, c.y() - corner_lift + r * 0.03))
                p.drawPath(cr)
            p.setPen(Qt.NoPen)

    # --- stubble ----------------------------------------------------------
    def _draw_stubble(self, p, cx, cy, r, look):
        """Beard shadow over the jaw and chin, left entirely to a gradient:
        an explicit outline puts a hard line across the cheeks."""
        amount = look.get("stubble", 0.0)
        if amount <= 0 or not hasattr(self, "_head_path"):
            return
        base = QColor(look["hair"]).darker(118)
        strong = _alpha(base, min(0.58, 0.44 * amount + 0.10))
        p.save()
        p.setClipPath(self._head_path)
        p.setPen(Qt.NoPen)
        g = QRadialGradient(QPointF(cx, cy + r * 0.74), r * 1.02)
        g.setColorAt(0.0, strong)
        g.setColorAt(0.70, strong)
        g.setColorAt(1.0, _alpha(base, 0.0))
        p.setBrush(QBrush(g))
        p.drawPath(self._head_path)
        p.restore()

    # --- neck, shoulders, accessories ------------------------------------
    def _draw_neck_and_shoulders(self, p, cx, cy, r, skin, shadow, look, dim):
        p.setPen(Qt.NoPen)
        # neck: a tapered column, not a rectangle -- a box edge under the
        # chin is the first thing that gives the drawing away
        lean = self.yaw * r * 0.12
        neck = QPainterPath()
        neck.moveTo(cx - r * 0.27 + lean, cy + r * 0.42)
        neck.cubicTo(cx - r * 0.29 + lean, cy + r * 0.78,
                     cx - r * 0.34, cy + r * 0.96, cx - r * 0.44, cy + r * 1.26)
        neck.lineTo(cx + r * 0.44, cy + r * 1.26)
        neck.cubicTo(cx + r * 0.34, cy + r * 0.96,
                     cx + r * 0.29 + lean, cy + r * 0.78,
                     cx + r * 0.27 + lean, cy + r * 0.42)
        neck.closeSubpath()
        # a neck sits in the jaw's shadow, so it is darker than the face all
        # the way down -- lighting it evenly is what makes it read as a box
        g = QLinearGradient(cx, cy + r * 0.45, cx, cy + r * 1.25)
        g.setColorAt(0.0, _mix(skin, shadow, 0.88).darker(112))
        g.setColorAt(0.6, _mix(skin, shadow, 0.68))
        g.setColorAt(1.0, _mix(skin, shadow, 0.80).darker(108))
        p.setBrush(QBrush(g))
        p.drawPath(neck)
        # the two tendons, which stop it reading as a cylinder
        p.save()
        p.setClipPath(neck)
        for side in (-1, 1):
            tg = QLinearGradient(cx + side * r * 0.06, 0, cx + side * r * 0.26, 0)
            tg.setColorAt(0.0, _alpha(_mix(skin, shadow, 0.35), 0.0))
            tg.setColorAt(1.0, _alpha(_mix(skin, shadow, 0.35), 0.30))
            p.setBrush(QBrush(tg))
            p.drawRect(QRectF(cx - r * 0.5, cy + r * 0.7, r, r * 0.6))
        p.restore()

        # the jaw's shadow falling on the neck
        p.save()
        p.setClipPath(neck)
        sg = QRadialGradient(QPointF(cx, cy + r * 0.58), r * 0.80)
        sg.setColorAt(0.0, _alpha(_mix(shadow, QColor("#4a2a1c"), 0.5), 0.62))
        sg.setColorAt(1.0, _alpha(shadow, 0.0))
        p.setBrush(QBrush(sg))
        p.drawPath(neck)
        p.restore()

        body = QColor(self.accent).darker(235) if not dim else QColor("#4a4d55")
        grad = QLinearGradient(cx, cy + r * 0.95, cx, cy + r * 1.9)
        grad.setColorAt(0.0, body.lighter(124))
        grad.setColorAt(1.0, body)
        p.setBrush(QBrush(grad))
        path = QPainterPath()
        path.moveTo(cx - r * 1.58, cy + r * 2.0)
        path.cubicTo(cx - r * 1.34, cy + r * 1.02, cx - r * 0.66, cy + r * 0.98,
                     cx - r * 0.40, cy + r * 1.16)
        path.cubicTo(cx - r * 0.20, cy + r * 1.30, cx + r * 0.20, cy + r * 1.30,
                     cx + r * 0.40, cy + r * 1.16)
        path.cubicTo(cx + r * 0.66, cy + r * 0.98, cx + r * 1.34, cy + r * 1.02,
                     cx + r * 1.58, cy + r * 2.0)
        path.closeSubpath()
        p.drawPath(path)
        if look.get("accessory") == "bowtie":
            self._draw_bowtie(p, cx, cy + r * 1.26, r * 0.28, dim)

    def _draw_bowtie(self, p, cx, cy, s, dim):
        col = QColor("#8d8f96") if dim else QColor("#23262f")
        p.setPen(Qt.NoPen)
        for side in (-1, 1):
            wing = QPainterPath()
            wing.moveTo(cx + side * s * 0.12, cy)
            wing.cubicTo(cx + side * s * 0.7, cy - s * 0.62,
                         cx + side * s * 1.05, cy - s * 0.5,
                         cx + side * s * 1.02, cy)
            wing.cubicTo(cx + side * s * 1.05, cy + s * 0.5,
                         cx + side * s * 0.7, cy + s * 0.62,
                         cx + side * s * 0.12, cy)
            wing.closeSubpath()
            g = QLinearGradient(cx, cy - s * 0.5, cx, cy + s * 0.5)
            g.setColorAt(0.0, col.lighter(160))
            g.setColorAt(1.0, col)
            p.setBrush(QBrush(g))
            p.drawPath(wing)
        p.setBrush(col.lighter(125))
        p.drawRoundedRect(QRectF(cx - s * 0.15, cy - s * 0.24, s * 0.30, s * 0.48),
                          s * 0.09, s * 0.09)

    # --- state cues -------------------------------------------------------
    def _draw_busy(self, p, cx, cy, r):
        col = QColor("#c98cff" if self.state == "thinking" else "#ffb84f")
        for i in range(3):
            ph = self._t * (2.6 if self.state == "thinking" else 4.0) - i * 0.5
            a = 0.35 + 0.45 * (math.sin(ph) * 0.5 + 0.5)
            p.setPen(Qt.NoPen)
            p.setBrush(_alpha(col, a))
            rr = r * (0.07 + 0.02 * i)
            x = cx + r * (0.95 + i * 0.30)
            y = cy - r * (0.85 + i * 0.22) - math.sin(ph) * r * 0.06
            p.drawEllipse(QPointF(x, y), rr, rr)

    def _draw_listening_rings(self, p, cx, cy, r):
        col = QColor("#4fd1a1")
        for i in range(3):
            t = (self._t * 0.9 + i / 3.0) % 1.0
            pen = QPen(_alpha(col, 0.45 * (1.0 - t)))
            pen.setWidthF(max(1.5, r * 0.035))
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            rr = r * (1.15 + t * 0.9)
            for side in (-1, 1):
                p.drawArc(QRectF(cx - rr, cy - rr, rr * 2, rr * 2),
                          int((0 if side > 0 else 180) - 32) * 16, 64 * 16)
