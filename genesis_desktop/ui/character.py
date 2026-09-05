"""A character with a face, instead of an abstract blob.

The point of this view is that you can tell what the assistant is doing
without reading anything: it looks at you while it listens, leans in when it
hears you, glances away while it thinks, and its mouth actually moves with
the sound of its own voice rather than flapping on a timer.

There is no 3D model file to ship. The head is drawn every frame with a
painter, but it is built like a 3D thing: a yaw/pitch pair rotates it, every
feature is placed by projecting a point on a sphere through that rotation,
and the shading (a light from the upper left, a darker rim, an occlusion
shadow under the chin and brow) is what sells the roundness. That means it
costs nothing to download, scales to any size, and each persona can be
described in a handful of numbers.

Lip sync is amplitude-driven. Real visemes need phoneme timings that neither
Piper nor the backend hands us, but a mouth that opens on the loud parts and
closes on the quiet ones reads correctly to anybody watching, and it is
driven by the same level the speaker is playing, so it cannot drift.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainterPath, QPen,
                           QRadialGradient)

# ----------------------------------------------------------------------
# per-persona looks. Everything is a ratio of head size, so it scales.
# ----------------------------------------------------------------------
DEFAULT_LOOK = {
    "skin": "#e8b58f", "skin_shadow": "#b07a55", "hair": "#3a2d28",
    "eye": "#4a3b32", "brow": "#3a2d28", "mouth": "#7d3b3b",
    "hair_style": "short", "brow_weight": 1.0, "eye_size": 1.0,
    "stubble": 0.0, "accessory": "", "jaw": 1.0, "age": 0.0,
}

LOOKS = {
    "alfred": {
        "skin": "#edc3a0", "skin_shadow": "#b8875f", "hair": "#8d8f96",
        "eye": "#3f5a7a", "brow": "#77797f", "mouth": "#8a4a4a",
        "hair_style": "receding", "brow_weight": 1.0, "eye_size": 0.92,
        "accessory": "bowtie", "jaw": 1.06, "age": 0.55,
    },
    "yui": {
        "skin": "#f7d3b8", "skin_shadow": "#cf9a78", "hair": "#4a2f2a",
        "eye": "#6b4a8f", "brow": "#5a3c34", "mouth": "#c96b74",
        "hair_style": "long", "brow_weight": 0.75, "eye_size": 1.25,
        "accessory": "", "jaw": 0.9, "age": 0.0,
    },
    "house": {
        "skin": "#dfb191", "skin_shadow": "#a87556", "hair": "#6d5f52",
        "eye": "#4f7ea8", "brow": "#5d5046", "mouth": "#8a4f4a",
        "hair_style": "short", "brow_weight": 1.35, "eye_size": 0.95,
        "stubble": 0.75, "accessory": "", "jaw": 1.1, "age": 0.45,
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
        self._yaw_t = 0.0
        self._pitch_t = 0.0
        self._sway = random.random() * math.tau
        # face
        self.mouth = 0.0            # 0 closed .. 1 wide
        self._mouth_t = 0.0
        self.blink = 0.0            # 0 open .. 1 shut
        self._next_blink = time.monotonic() + 2.0
        self._blink_phase = 0.0
        self.brow = 0.0             # -1 furrowed .. 1 raised
        self._brow_t = 0.0
        self.brow_skew = 0.0        # one brow up, the other down
        self._skew_t = 0.0
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

    # ------------------------------------------------------------------
    def advance(self, dt: float):
        """Move every animated quantity toward its target for this state."""
        self._t += dt
        now = time.monotonic()
        st = self.state
        speaking = st == "speaking"
        lvl = max(0.0, min(1.0, self.level))

        # ---- where is it looking -------------------------------------
        if now >= self._next_gaze:
            if st == "thinking":
                # eyes up and away, the way people do when recalling
                self._gaze_t = [random.uniform(-0.8, 0.8), random.uniform(-0.9, -0.4)]
                self._next_gaze = now + random.uniform(0.7, 1.6)
            elif st in ("hearing", "confirm"):
                self._gaze_t = [random.uniform(-0.12, 0.12), random.uniform(-0.08, 0.08)]
                self._next_gaze = now + random.uniform(0.8, 2.0)
            elif st in ("listening", "speaking"):
                self._gaze_t = [random.uniform(-0.3, 0.3), random.uniform(-0.2, 0.15)]
                self._next_gaze = now + random.uniform(1.4, 3.4)
            else:
                self._gaze_t = [0.0, 0.25]
                self._next_gaze = now + 2.0
        for i in (0, 1):
            self._gaze[i] += (self._gaze_t[i] - self._gaze[i]) * min(1.0, dt * 7)

        # ---- head pose ------------------------------------------------
        self._sway += dt * (0.9 if st in ("listening", "muted", "offline") else 1.6)
        sway = math.sin(self._sway) * 0.05 + math.sin(self._sway * 0.37) * 0.03
        if st == "thinking":
            self._yaw_t = self._gaze[0] * 0.35 + sway
            self._pitch_t = -0.22 + sway * 0.4
        elif st == "hearing":
            self._yaw_t = self._gaze[0] * 0.12
            self._pitch_t = 0.10 + sway * 0.3          # leaning in
        elif st == "tool":
            self._yaw_t = -0.28 + sway                  # glancing at the work
            self._pitch_t = 0.18
        elif st == "confirm":
            self._yaw_t = sway * 0.5
            self._pitch_t = -0.06
        elif st == "speaking":
            self._yaw_t = self._gaze[0] * 0.22 + sway + lvl * 0.04 * math.sin(self._t * 9)
            self._pitch_t = sway * 0.5 + lvl * 0.05
        elif st in ("muted", "offline"):
            self._yaw_t = sway * 0.6
            self._pitch_t = 0.30                        # head down
        else:                                            # listening
            self._yaw_t = self._gaze[0] * 0.30 + sway
            self._pitch_t = self._gaze[1] * 0.18 + sway * 0.5
        self.yaw += (self._yaw_t - self.yaw) * min(1.0, dt * 4.5)
        self.pitch += (self._pitch_t - self.pitch) * min(1.0, dt * 4.5)

        # ---- mouth ----------------------------------------------------
        if speaking:
            # amplitude drives it, with a floor so quiet syllables still show
            self._mouth_t = min(1.0, 0.05 + lvl * 1.7)
        elif st == "confirm":
            self._mouth_t = 0.06
        elif st == "thinking":
            self._mouth_t = 0.02
        else:
            self._mouth_t = 0.0
        # opening is quick, closing is slower -- a mouth cannot snap shut
        rate = 30 if self._mouth_t > self.mouth else 13
        self.mouth += (self._mouth_t - self.mouth) * min(1.0, dt * rate)

        # ---- eyes -----------------------------------------------------
        if st in ("muted", "offline"):
            self._eye_t = 0.12
        elif st == "hearing":
            self._eye_t = 1.22
        elif st == "confirm":
            self._eye_t = 1.3
        elif st == "thinking":
            self._eye_t = 0.82
        else:
            self._eye_t = 1.0
        self.eye_open += (self._eye_t - self.eye_open) * min(1.0, dt * 6)

        if st in ("muted", "offline"):
            self.blink = 0.0
        else:
            if self._blink_phase > 0:
                self._blink_phase = max(0.0, self._blink_phase - dt / 0.09)
                self.blink = math.sin(min(1.0, 1 - self._blink_phase) * math.pi)
            elif now >= self._next_blink:
                self._blink_phase = 1.0
                self._next_blink = now + random.uniform(2.4, 6.5)
            else:
                self.blink = 0.0

        # ---- brow -----------------------------------------------------
        self._brow_t = {"thinking": -0.10, "confirm": 0.75, "hearing": 0.45,
                        "tool": -0.35, "offline": -0.15, "muted": -0.1}.get(st, 0.0)
        # one brow up is "pondering"; both down is "angry", which is not
        # what thinking should look like
        self._skew_t = {"thinking": 0.9, "confirm": 0.35, "tool": 0.5}.get(st, 0.0)
        if speaking:
            self._brow_t = 0.12 + lvl * 0.5
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

        yaw_px = self.yaw * r * 0.30
        pitch_px = self.pitch * r * 0.22
        hx, hy = cx + yaw_px * 0.5, cy + pitch_px * 0.5

        self._draw_glow(p, hx, hy, r, dim)
        if look.get("hair_style") == "long":
            self._draw_long_hair(p, hx, hy, r, look, dim, back=True)
        self._draw_neck_and_shoulders(p, cx, cy, r, skin, shadow, look, dim)
        self._draw_head(p, hx, hy, r, skin, shadow, look)
        self._draw_hair(p, hx, hy, r, look, dim)
        self._draw_brows(p, hx, hy, r, look, dim)
        self._draw_eyes(p, hx, hy, r, look, dim)
        self._draw_nose(p, hx, hy, r, shadow)
        if look.get("stubble"):
            self._draw_stubble(p, hx, hy, r, look)
        self._draw_mouth(p, hx, hy, r, look, skin, shadow, dim)
        self._draw_shading(p, hx, hy, r, dim)
        if self.state in ("thinking", "tool"):
            self._draw_busy(p, hx, hy, r)
        if self.state == "hearing":
            self._draw_listening_rings(p, hx, hy, r)

    # ------------------------------------------------------------------
    def _draw_glow(self, p, cx, cy, r, dim):
        col = QColor(self.accent)
        if self.state == "hearing":
            col = QColor("#4fd1a1")
        elif self.state == "thinking":
            col = QColor("#c98cff")
        elif self.state == "tool":
            col = QColor("#ffb84f")
        elif self.state == "confirm":
            col = QColor("#ff6b6b")
        g = QRadialGradient(QPointF(cx, cy), r * 2.6)
        a = 0.10 + (0.0 if dim else self.level * 0.30)
        c0 = QColor(col)
        c0.setAlphaF(max(0.0, min(1.0, a * (0.4 if dim else 1.0))))
        c1 = QColor(col)
        c1.setAlphaF(0.0)
        g.setColorAt(0.0, c0)
        g.setColorAt(1.0, c1)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), r * 2.6, r * 2.6)

    def _draw_neck_and_shoulders(self, p, cx, cy, r, skin, shadow, look, dim):
        neck = QColor(shadow).lighter(112)
        p.setPen(Qt.NoPen)
        p.setBrush(neck)
        nw = r * 0.34
        p.drawRoundedRect(QRectF(cx - nw + self.yaw * r * 0.14, cy + r * 0.62,
                                 nw * 2, r * 0.62), nw * 0.5, nw * 0.5)
        # shoulders / collar
        body = QColor(self.accent).darker(230) if not dim else QColor("#4a4d55")
        grad = QLinearGradient(cx, cy + r * 1.0, cx, cy + r * 1.9)
        grad.setColorAt(0.0, body.lighter(120))
        grad.setColorAt(1.0, body)
        p.setBrush(QBrush(grad))
        path = QPainterPath()
        path.moveTo(cx - r * 1.55, cy + r * 2.0)
        path.cubicTo(cx - r * 1.35, cy + r * 1.05, cx - r * 0.62, cy + r * 1.02,
                     cx - r * 0.30, cy + r * 1.14)
        path.lineTo(cx + r * 0.30, cy + r * 1.14)
        path.cubicTo(cx + r * 0.62, cy + r * 1.02, cx + r * 1.35, cy + r * 1.05,
                     cx + r * 1.55, cy + r * 2.0)
        path.closeSubpath()
        p.drawPath(path)
        if look.get("accessory") == "bowtie":
            self._draw_bowtie(p, cx, cy + r * 1.20, r * 0.30, dim)

    def _draw_bowtie(self, p, cx, cy, s, dim):
        col = QColor("#8d8f96") if dim else QColor("#2b2f3a")
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        left = QPainterPath()
        left.moveTo(cx - s * 0.12, cy)
        left.lineTo(cx - s * 1.0, cy - s * 0.55)
        left.lineTo(cx - s * 1.0, cy + s * 0.55)
        left.closeSubpath()
        right = QPainterPath()
        right.moveTo(cx + s * 0.12, cy)
        right.lineTo(cx + s * 1.0, cy - s * 0.55)
        right.lineTo(cx + s * 1.0, cy + s * 0.55)
        right.closeSubpath()
        p.drawPath(left)
        p.drawPath(right)
        p.setBrush(col.lighter(130))
        p.drawRoundedRect(QRectF(cx - s * 0.16, cy - s * 0.26, s * 0.32, s * 0.52),
                          s * 0.1, s * 0.1)

    def _draw_head(self, p, cx, cy, r, skin, shadow, look):
        jaw = look.get("jaw", 1.0)
        path = QPainterPath()
        # a rounded skull narrowing to a jaw, drawn as one closed curve
        top = cy - r * 1.02
        path.moveTo(cx - r * 0.86, cy - r * 0.10)
        path.cubicTo(cx - r * 0.92, top, cx + r * 0.92, top, cx + r * 0.86, cy - r * 0.10)
        path.cubicTo(cx + r * 0.82, cy + r * 0.48 * jaw,
                     cx + r * 0.40, cy + r * 0.92 * jaw,
                     cx, cy + r * 0.96 * jaw)
        path.cubicTo(cx - r * 0.40, cy + r * 0.92 * jaw,
                     cx - r * 0.82, cy + r * 0.48 * jaw,
                     cx - r * 0.86, cy - r * 0.10)
        path.closeSubpath()

        lx = cx - r * 0.45 + self.yaw * r * 0.25
        ly = cy - r * 0.55 + self.pitch * r * 0.2
        g = QRadialGradient(QPointF(lx, ly), r * 2.1)
        g.setColorAt(0.0, skin.lighter(122))
        g.setColorAt(0.45, skin)
        g.setColorAt(1.0, shadow)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(path)
        self._head_path = path

        # ears, behind the jaw line, shifted by the yaw
        for side in (-1, 1):
            ex = cx + side * r * 0.88 - self.yaw * r * 0.22 * side
            vis = 1.0 - max(0.0, self.yaw * side * 1.1)
            if vis <= 0.05:
                continue
            p.setBrush(_mix(skin, shadow, 0.35))
            p.drawEllipse(QPointF(ex, cy + r * 0.08 + self.pitch * r * 0.1),
                          r * 0.13 * vis, r * 0.20)

    HAIRLINES = {
        # (temple height, centre height) as multiples of r above centre
        "short": (0.24, 0.56),
        "receding": (0.62, 0.44),
        "long": (0.10, 0.50),
    }

    def _draw_hair(self, p, cx, cy, r, look, dim):
        """Hair is everything on the skull above the hairline. Building it
        that way -- a region clipped to the head path -- means it always
        follows the skull exactly instead of being a band that floats near
        the crown at some sizes and misses it at others."""
        if not hasattr(self, "_head_path"):
            return
        hair = QColor(look["hair"])
        if dim:
            hair = _mix(hair, QColor("#8d8f96"), 0.5)
        style = look.get("hair_style", "short")
        temple, centre = self.HAIRLINES.get(style, self.HAIRLINES["short"])

        region = QPainterPath()
        region.moveTo(cx - r * 2.0, cy + r * temple)
        region.lineTo(cx - r * 2.0, cy - r * 2.0)
        region.lineTo(cx + r * 2.0, cy - r * 2.0)
        region.lineTo(cx + r * 2.0, cy + r * temple)
        # back across the hairline, right temple to left temple
        region.cubicTo(cx + r * 0.55, cy - r * (centre - 0.14),
                       cx + r * 0.30, cy - r * centre,
                       cx, cy - r * centre)
        region.cubicTo(cx - r * 0.30, cy - r * centre,
                       cx - r * 0.55, cy - r * (centre - 0.14),
                       cx - r * 2.0, cy + r * temple)
        region.closeSubpath()
        path = region.intersected(self._head_path)
        if path.isEmpty():
            return

        p.setPen(Qt.NoPen)
        g = QLinearGradient(cx - r * 0.7, cy - r * 1.05, cx + r * 0.7, cy - r * 0.2)
        g.setColorAt(0.0, hair.lighter(135))
        g.setColorAt(0.55, hair)
        g.setColorAt(1.0, hair.darker(122))
        p.setBrush(QBrush(g))
        p.drawPath(path)

        age = look.get("age", 0.0)
        if age > 0.25:                       # grey coming in at the temples
            grey = QLinearGradient(cx - r, cy, cx + r, cy)
            w = QColor(235, 235, 238, int(120 * age))
            clear = QColor(235, 235, 238, 0)
            grey.setColorAt(0.0, w)
            grey.setColorAt(0.35, clear)
            grey.setColorAt(0.65, clear)
            grey.setColorAt(1.0, w)
            p.setBrush(QBrush(grey))
            p.drawPath(path)

        # a shine across the top, which is what makes it read as hair
        p.save()
        p.setClipPath(path)
        shine = QRadialGradient(QPointF(cx - r * 0.30 + self.yaw * r * 0.3,
                                        cy - r * 0.78), r * 0.85)
        shine.setColorAt(0.0, QColor(255, 255, 255, 0 if dim else 46))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(shine))
        p.drawPath(path)
        p.restore()

    def _draw_long_hair(self, p, cx, cy, r, look, dim, back=False):
        hair = QColor(look["hair"])
        if dim:
            hair = _mix(hair, QColor("#8d8f96"), 0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(hair.darker(118))
        path = QPainterPath()
        path.moveTo(cx - r * 1.02, cy + r * 1.20)
        path.cubicTo(cx - r * 1.22, cy - r * 0.60, cx + r * 1.22, cy - r * 0.60,
                     cx + r * 1.02, cy + r * 1.20)
        path.cubicTo(cx + r * 0.60, cy + r * 0.85, cx - r * 0.60, cy + r * 0.85,
                     cx - r * 1.02, cy + r * 1.20)
        path.closeSubpath()
        p.drawPath(path)

    def _draw_brows(self, p, cx, cy, r, look, dim):
        col = QColor(look["brow"])
        if dim:
            col = _mix(col, QColor("#8d8f96"), 0.5)
        weight = look.get("brow_weight", 1.0)
        base = self.brow * r * 0.09
        for side in (-1, 1):
            raise_ = base + self.brow_skew * r * 0.075 * (1 if side < 0 else -0.45)
            a, da = self._project(side * 0.36, -0.30, cx, cy, r)
            b, db = self._project(side * 0.10, -0.28, cx, cy, r)
            if da < 0.28:
                continue
            inner_drop = -self.brow * r * 0.05 * (1 if self.brow < 0 else 0.4)
            if side > 0:
                inner_drop += self.brow_skew * r * 0.035
            pen = QPen(col)
            pen.setWidthF(max(1.5, r * 0.075 * weight * da))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(a.x(), a.y() - raise_)
            mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2 - raise_ - r * 0.05)
            path.quadTo(mid, QPointF(b.x(), b.y() - raise_ + inner_drop))
            p.drawPath(path)

    def _draw_eyes(self, p, cx, cy, r, look, dim):
        size = look.get("eye_size", 1.0) * self.eye_open
        iris_col = QColor(look["eye"])
        if dim:
            iris_col = _mix(iris_col, QColor("#8d8f96"), 0.6)
        lid = 1.0 - self.blink
        for side in (-1, 1):
            c, depth = self._project(side * 0.30, -0.08, cx, cy, r)
            if depth < 0.25:
                continue
            ew = r * 0.20 * size * depth
            eh = r * 0.125 * size * max(0.06, lid)

            socket = QRadialGradient(QPointF(c.x(), c.y() - eh * 0.6), ew * 2.2)
            socket.setColorAt(0.0, QColor(0, 0, 0, 40))
            socket.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(socket))
            p.drawEllipse(c, ew * 1.9, eh * 2.4)

            white = QPainterPath()
            white.addEllipse(c, ew, eh)
            p.setBrush(QColor("#f6f2ee") if not dim else QColor("#d8d8dc"))
            p.drawPath(white)

            if lid > 0.12:
                p.save()
                p.setClipPath(white)
                gx = c.x() + self._gaze[0] * ew * 0.42
                gy = c.y() + self._gaze[1] * eh * 0.5
                ir = min(ew * 0.62, eh * 1.25)
                ig = QRadialGradient(QPointF(gx - ir * 0.2, gy - ir * 0.25), ir * 1.6)
                ig.setColorAt(0.0, iris_col.lighter(150))
                ig.setColorAt(0.7, iris_col)
                ig.setColorAt(1.0, iris_col.darker(165))
                p.setBrush(QBrush(ig))
                p.drawEllipse(QPointF(gx, gy), ir, ir)
                p.setBrush(QColor(15, 12, 10))
                p.drawEllipse(QPointF(gx, gy), ir * 0.44, ir * 0.44)
                p.setBrush(QColor(255, 255, 255, 205))
                p.drawEllipse(QPointF(gx - ir * 0.30, gy - ir * 0.34), ir * 0.20, ir * 0.20)
                # upper lid shadow
                p.setBrush(QColor(0, 0, 0, 46))
                p.drawEllipse(QPointF(c.x(), c.y() - eh * 1.5), ew * 1.1, eh * 1.0)
                p.restore()

            pen = QPen(QColor(look["brow"]).darker(120))
            pen.setWidthF(max(1.0, r * 0.020))
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(white)

    def _draw_nose(self, p, cx, cy, r, shadow):
        a, da = self._project(0.0, -0.02, cx, cy, r)
        b, db = self._project(0.0, 0.20, cx, cy, r)
        if da < 0.25:
            return
        pen = QPen(QColor(shadow).darker(112))
        pen.setWidthF(max(1.2, r * 0.035))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(a)
        side = 1 if self.yaw >= 0 else -1
        path.quadTo(QPointF(b.x() + side * r * 0.09, b.y() - r * 0.04),
                    QPointF(b.x() + side * r * 0.02, b.y()))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 26))
        p.drawEllipse(QPointF(b.x(), b.y() + r * 0.02), r * 0.13, r * 0.05)

    def _draw_mouth(self, p, cx, cy, r, look, skin, shadow, dim):
        c, depth = self._project(0.0, 0.46, cx, cy, r)
        if depth < 0.22:
            return
        open_ = self.mouth
        col = QColor(look["mouth"])
        if dim:
            col = _mix(col, QColor("#8d8f96"), 0.5)
        w = r * 0.30 * depth * (1.0 + open_ * 0.16)
        h = r * 0.30 * open_

        if open_ < 0.045:
            pen = QPen(col.darker(125))
            pen.setWidthF(max(1.4, r * 0.032))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(c.x() - w, c.y())
            smile = -r * 0.03 if self.state in ("listening", "speaking") else r * 0.01
            path.quadTo(QPointF(c.x(), c.y() - smile), QPointF(c.x() + w, c.y()))
            p.drawPath(path)
            return

        # open mouth: dark cavity, teeth along the top, lips around it
        cavity = QPainterPath()
        cavity.addEllipse(QPointF(c.x(), c.y() + h * 0.12), w, h * 0.92)
        p.setPen(Qt.NoPen)
        g = QRadialGradient(QPointF(c.x(), c.y() + h * 0.4), w * 1.4)
        g.setColorAt(0.0, QColor(58, 20, 22))
        g.setColorAt(1.0, QColor(26, 8, 10))
        p.setBrush(QBrush(g))
        p.drawPath(cavity)

        p.save()
        p.setClipPath(cavity)
        p.setBrush(QColor("#f4efe9") if not dim else QColor("#d5d5d9"))
        p.drawRoundedRect(QRectF(c.x() - w, c.y() - h * 0.95, w * 2, h * 0.55),
                          r * 0.02, r * 0.02)
        if open_ > 0.5:
            p.setBrush(QColor(150, 60, 62))
            p.drawEllipse(QPointF(c.x(), c.y() + h * 0.85), w * 0.62, h * 0.42)
        p.restore()

        pen = QPen(_mix(col, shadow, 0.25))
        pen.setWidthF(max(1.3, r * 0.030))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(cavity)

    def _draw_stubble(self, p, cx, cy, r, look):
        """Beard shadow over the jaw and chin. Clipped to the head and left
        entirely to a gradient -- giving it an explicit outline puts a hard
        line across the cheeks wherever the outline and the fade disagree."""
        amount = look.get("stubble", 0.0)
        if amount <= 0 or not hasattr(self, "_head_path"):
            return
        base = QColor(look["hair"]).darker(115)
        strong = QColor(base)
        strong.setAlphaF(min(0.60, 0.46 * amount + 0.10))
        clear = QColor(base)
        clear.setAlphaF(0.0)
        p.save()
        p.setClipPath(self._head_path)
        p.setPen(Qt.NoPen)
        g = QRadialGradient(QPointF(cx, cy + r * 0.72), r * 1.05)
        g.setColorAt(0.0, strong)
        g.setColorAt(0.72, strong)
        g.setColorAt(1.0, clear)
        p.setBrush(QBrush(g))
        p.drawPath(self._head_path)
        p.restore()

    def _draw_shading(self, p, cx, cy, r, dim):
        """One pass of light and rim over everything, which is most of what
        makes it read as a solid object rather than flat shapes."""
        if not hasattr(self, "_head_path"):
            return
        p.save()
        p.setClipPath(self._head_path)
        lx = cx - r * 0.55 + self.yaw * r * 0.3
        ly = cy - r * 0.75 + self.pitch * r * 0.25
        g = QRadialGradient(QPointF(lx, ly), r * 2.3)
        g.setColorAt(0.0, QColor(255, 250, 240, 0 if dim else 60))
        g.setColorAt(0.5, QColor(255, 255, 255, 0))
        g.setColorAt(1.0, QColor(28, 18, 14, 96))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(self._head_path)
        # rim light on the far side, in the persona's colour
        rim = QColor(self.accent)
        rim.setAlphaF(0.0 if dim else 0.34)
        side = 1 if self.yaw <= 0 else -1
        rg = QLinearGradient(cx + side * r * 0.35, cy, cx + side * r * 1.05, cy)
        rg.setColorAt(0.0, QColor(255, 255, 255, 0))
        rg.setColorAt(1.0, rim)
        p.setBrush(QBrush(rg))
        p.drawPath(self._head_path)
        p.restore()

    def _draw_busy(self, p, cx, cy, r):
        col = QColor("#c98cff" if self.state == "thinking" else "#ffb84f")
        n = 3
        for i in range(n):
            ph = self._t * (2.6 if self.state == "thinking" else 4.0) - i * 0.5
            a = 0.35 + 0.45 * (math.sin(ph) * 0.5 + 0.5)
            c = QColor(col)
            c.setAlphaF(max(0.0, min(1.0, a)))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            rr = r * (0.07 + 0.02 * i)
            x = cx + r * (0.95 + i * 0.30)
            y = cy - r * (0.85 + i * 0.22) - math.sin(ph) * r * 0.06
            p.drawEllipse(QPointF(x, y), rr, rr)

    def _draw_listening_rings(self, p, cx, cy, r):
        col = QColor("#4fd1a1")
        for i in range(3):
            t = (self._t * 0.9 + i / 3.0) % 1.0
            c = QColor(col)
            c.setAlphaF(max(0.0, 0.45 * (1.0 - t)))
            pen = QPen(c)
            pen.setWidthF(max(1.5, r * 0.035))
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            rr = r * (1.15 + t * 0.9)
            for side in (-1, 1):
                p.drawArc(QRectF(cx - rr, cy - rr, rr * 2, rr * 2),
                          int((0 if side > 0 else 180) - 32) * 16, 64 * 16)
