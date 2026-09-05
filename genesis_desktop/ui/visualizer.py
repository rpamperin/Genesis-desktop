"""The face of the assistant: a widget that moves with sound.

Three styles share one animation model. A level (0..1) arrives from the
microphone while listening and from the speaker while talking; it is
smoothed with fast attack and slow release so the picture reacts instantly
but never flickers. The state decides colour and behaviour:

    listening   a slow breathing pulse in the persona's colour
    hearing     the ring/orb opens in green and follows your voice
    thinking    orbiting particles, a rotating dashed ring
    tool        amber, a spinning working indicator
    confirm     red pulse: it is waiting for you
    speaking    the accent colour, bars/blob driven by the audio level
    muted       grey, still
    offline     dim grey, slow fade
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from . import theme


def _alpha(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, max(0.0, min(1.0, a)))))
    return c

N_BARS = 48
N_PARTICLES = 28


class Visualizer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.state = "offline"
        self.style = "orb"
        self.accent = theme.accent_for("alfred")
        self.theme_name = "dark"
        self._target = 0.0
        self._level = 0.0
        self._smooth = 0.0
        self._bars = [0.0] * N_BARS
        self._phase = 0.0
        self._spin = 0.0
        self._t0 = time.monotonic()
        self._particles = [self._new_particle(i) for i in range(N_PARTICLES)]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        self._last = time.monotonic()
        self._flash = 0.0

    # ------------------------------------------------------------------
    def set_level(self, v: float):
        self._target = max(0.0, min(1.0, v * 6.0))     # mic rms is small

    def set_state(self, s: str):
        if s != self.state:
            self._flash = 1.0
        self.state = s
        if s in ("listening", "muted", "offline", "thinking"):
            self._target = 0.0

    def set_accent(self, c: QColor):
        self.accent = QColor(c)

    def set_style(self, style: str):
        self.style = style

    def set_theme(self, name: str):
        self.theme_name = name

    # ------------------------------------------------------------------
    def _new_particle(self, i):
        return {"a": random.random() * math.tau, "r": 0.55 + random.random() * 0.45,
                "s": 0.3 + random.random() * 0.9, "sz": 1.5 + random.random() * 3,
                "ph": random.random() * math.tau}

    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        # attack fast, release slow
        if self._target > self._level:
            self._level += (self._target - self._level) * min(1.0, dt * 28)
        else:
            self._level += (self._target - self._level) * min(1.0, dt * 6)
        self._smooth += (self._level - self._smooth) * min(1.0, dt * 10)
        self._phase += dt * (1.2 if self.state in ("listening", "offline") else 3.0)
        spin_rate = {"thinking": 2.2, "tool": 3.5, "hearing": 0.6, "speaking": 0.9}.get(self.state, 0.25)
        self._spin += dt * spin_rate
        self._flash = max(0.0, self._flash - dt * 2.5)
        # bars get individual jitter around the level so they look alive
        lvl = self._level
        for i in range(N_BARS):
            centre = 1.0 - abs(i - N_BARS / 2) / (N_BARS / 2)
            want = lvl * (0.35 + 0.65 * centre) * (0.6 + 0.4 * math.sin(self._phase * 3 + i * 0.7) ** 2)
            if self.state == "speaking":
                want *= 0.8 + 0.5 * random.random()
            self._bars[i] += (want - self._bars[i]) * min(1.0, dt * (30 if want > self._bars[i] else 8))
        for p in self._particles:
            p["a"] += dt * p["s"] * (1.0 if self.state != "thinking" else 2.5)
        self.update()

    # ------------------------------------------------------------------
    def _colour(self) -> QColor:
        c = theme.STATE_COLORS.get(self.state)
        return QColor(c) if c else QColor(self.accent)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        base = min(w, h) * 0.30
        col = self._colour()
        dim = self.state in ("offline", "muted")
        if dim:
            col = QColor(col)
        alpha_scale = 0.45 if dim else 1.0

        # background glow, follows the level
        glow = QRadialGradient(QPointF(cx, cy), base * (1.9 + self._smooth * 0.9))
        g0 = QColor(col)
        g0.setAlphaF(max(0.0, min(1.0, (0.16 + 0.32 * self._smooth + 0.2 * self._flash) * alpha_scale)))
        g1 = QColor(col)
        g1.setAlphaF(max(0.0, min(1.0, 0.0)))
        glow.setColorAt(0.0, g0)
        glow.setColorAt(1.0, g1)
        p.fillRect(self.rect(), QBrush(glow))

        if self.style == "bars":
            self._paint_bars(p, cx, cy, base, col, alpha_scale)
        elif self.style == "ring":
            self._paint_ring(p, cx, cy, base, col, alpha_scale)
        else:
            self._paint_orb(p, cx, cy, base, col, alpha_scale)

        if self.state in ("thinking", "tool"):
            self._paint_working(p, cx, cy, base, col)
        p.end()

    # --- orb ------------------------------------------------------------
    def _paint_orb(self, p, cx, cy, base, col, alpha_scale):
        breathe = 0.04 * math.sin(self._phase) if self.state in ("listening", "offline", "muted") else 0.0
        r = base * (0.72 + breathe + self._smooth * 0.35)
        # wobbly blob outline
        path = QPainterPath()
        pts = 90
        lvl = self._level
        for i in range(pts + 1):
            a = i / pts * math.tau
            wob = 1.0
            if self.state == "speaking":
                wob += 0.10 * lvl * math.sin(a * 5 + self._phase * 4) + 0.08 * lvl * math.sin(a * 9 - self._phase * 6)
            elif self.state == "hearing":
                wob += 0.12 * lvl * math.sin(a * 7 + self._phase * 5)
            elif self.state == "thinking":
                wob += 0.03 * math.sin(a * 3 + self._spin * 3)
            elif self.state == "confirm":
                wob += 0.05 * abs(math.sin(self._phase * 2))
            x = cx + math.cos(a) * r * wob
            y = cy + math.sin(a) * r * wob
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        grad = QRadialGradient(QPointF(cx - r * 0.3, cy - r * 0.3), r * 1.6)
        c0 = QColor(col).lighter(150)
        c0.setAlphaF(max(0.0, min(1.0, 0.95 * alpha_scale)))
        c1 = QColor(col)
        c1.setAlphaF(max(0.0, min(1.0, 0.85 * alpha_scale)))
        c2 = QColor(col).darker(180)
        c2.setAlphaF(max(0.0, min(1.0, 0.9 * alpha_scale)))
        grad.setColorAt(0.0, c0)
        grad.setColorAt(0.55, c1)
        grad.setColorAt(1.0, c2)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPath(path)
        # rings around it
        for k in range(3):
            rr = r * (1.18 + k * 0.16 + self._smooth * 0.25 * (k + 1))
            pen = QPen(col)
            a = (0.35 - k * 0.1) * alpha_scale * (0.5 + self._smooth)
            c = QColor(col)
            c.setAlphaF(max(0.0, min(1.0, max(0.03, a))))
            pen.setColor(c)
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), rr, rr)
        # particles
        for q in self._particles:
            rr = r * (1.25 + q["r"] * 0.6 + self._smooth * 0.4)
            x = cx + math.cos(q["a"]) * rr
            y = cy + math.sin(q["a"]) * rr * 0.92
            c = QColor(col)
            c.setAlphaF(max(0.0, min(1.0, (0.25 + 0.5 * abs(math.sin(q["ph"] + self._phase))) * alpha_scale)))
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            sz = q["sz"] * (0.8 + self._smooth)
            p.drawEllipse(QPointF(x, y), sz, sz)

    # --- bars -------------------------------------------------------------
    def _paint_bars(self, p, cx, cy, base, col, alpha_scale):
        w = self.width()
        span = min(w * 0.8, base * 4.2)
        bw = span / N_BARS
        maxh = base * 1.6
        grad = QLinearGradient(0, cy - maxh, 0, cy + maxh)
        c0 = QColor(col).lighter(140)
        c0.setAlphaF(max(0.0, min(1.0, 0.95 * alpha_scale)))
        c1 = QColor(col)
        c1.setAlphaF(max(0.0, min(1.0, 0.9 * alpha_scale)))
        grad.setColorAt(0, c0)
        grad.setColorAt(0.5, c1)
        grad.setColorAt(1, c0)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        idle = 0.05 + 0.03 * math.sin(self._phase)
        for i, v in enumerate(self._bars):
            hh = maxh * max(idle * (1 - abs(i - N_BARS / 2) / (N_BARS / 2) * 0.6), v)
            x = cx - span / 2 + i * bw + bw * 0.2
            p.drawRoundedRect(QRectF(x, cy - hh, bw * 0.6, hh * 2), bw * 0.3, bw * 0.3)

    # --- ring -------------------------------------------------------------
    def _paint_ring(self, p, cx, cy, base, col, alpha_scale):
        r = base * (0.9 + self._smooth * 0.25)
        n = 72
        for i in range(n):
            a = i / n * math.tau - math.pi / 2
            v = self._bars[i % N_BARS]
            length = base * 0.15 + base * 0.7 * v
            x0, y0 = cx + math.cos(a) * r, cy + math.sin(a) * r
            x1, y1 = cx + math.cos(a) * (r + length), cy + math.sin(a) * (r + length)
            c = QColor(col)
            c.setAlphaF(max(0.0, min(1.0, (0.35 + 0.6 * v) * alpha_scale)))
            pen = QPen(c)
            pen.setWidthF(max(2.0, base * 0.03))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        c = QColor(col)
        c.setAlphaF(max(0.0, min(1.0, 0.9 * alpha_scale)))
        pen = QPen(c)
        pen.setWidthF(3)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r * 0.96, r * 0.96)
        inner = QRadialGradient(QPointF(cx, cy), r * 0.9)
        c0 = QColor(col)
        c0.setAlphaF(max(0.0, min(1.0, (0.15 + 0.5 * self._smooth) * alpha_scale)))
        c1 = QColor(col)
        c1.setAlphaF(max(0.0, min(1.0, 0)))
        inner.setColorAt(0, c0)
        inner.setColorAt(1, c1)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(inner))
        p.drawEllipse(QPointF(cx, cy), r * 0.9, r * 0.9)

    # --- working indicator ---------------------------------------------------
    def _paint_working(self, p, cx, cy, base, col):
        r = base * 1.55
        pen = QPen(col)
        pen.setWidthF(3)
        pen.setCapStyle(Qt.RoundCap)
        c = QColor(col)
        c.setAlphaF(max(0.0, min(1.0, 0.85)))
        pen.setColor(c)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        start = int(-self._spin * 360 * 16) % (360 * 16)
        for k in range(3):
            p.drawArc(rect, start + k * 120 * 16, 60 * 16)
