"""Colours and the application stylesheet.

Each persona gets an accent so you can tell at a glance who is talking:
Alfred is a cool blue, Yui a warm coral, anything else falls back to a
violet. The visualizer, status pill and chat bubbles all follow it.
"""
from PySide6.QtGui import QColor

PERSONA_ACCENTS = {
    "alfred": "#4fa3ff",
    "yui": "#ff7a90",
}
FALLBACK_ACCENTS = ["#b07cff", "#4fd1a1", "#ffb84f", "#4fe0ff"]

STATE_COLORS = {
    "offline": "#7a7f8a",
    "muted": "#8d8f96",
    "listening": None,          # accent, dim
    "hearing": "#4fd1a1",
    "thinking": "#c98cff",
    "tool": "#ffb84f",
    "confirm": "#ff6b6b",
    "speaking": None,           # accent, bright
}

DARK = {
    "bg": "#0e1016", "panel": "#161923", "panel2": "#1d2130", "border": "#262b3b",
    "text": "#e6e8ef", "muted": "#8b91a3", "input": "#12151d",
}
LIGHT = {
    "bg": "#f3f4f8", "panel": "#ffffff", "panel2": "#eceef5", "border": "#d5d9e6",
    "text": "#1b1e28", "muted": "#5f6577", "input": "#ffffff",
}


def accent_for(persona: str) -> QColor:
    if persona in PERSONA_ACCENTS:
        return QColor(PERSONA_ACCENTS[persona])
    idx = sum(ord(c) for c in persona) % len(FALLBACK_ACCENTS)
    return QColor(FALLBACK_ACCENTS[idx])


def palette(theme: str) -> dict:
    return DARK if theme == "dark" else LIGHT


def rgba(c: QColor, alpha: float) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(alpha * 255)})"


def stylesheet(theme: str, accent: QColor) -> str:
    p = palette(theme)
    a = accent.name()
    a22, a26, a33, a44, a55, a66 = (rgba(accent, x) for x in (0.13, 0.15, 0.2, 0.27, 0.33, 0.4))
    return f"""
    QMainWindow, QDialog, QWidget#root {{ background: {p['bg']}; color: {p['text']}; }}
    QWidget {{ color: {p['text']}; font-size: 13px; }}
    QDockWidget {{ color: {p['muted']}; font-weight: 600; titlebar-close-icon: none; }}
    QDockWidget::title {{ background: {p['panel']}; padding: 6px 10px; border-bottom: 1px solid {p['border']}; }}
    QToolBar {{ background: {p['panel']}; border: none; border-bottom: 1px solid {p['border']}; spacing: 6px; padding: 4px 8px; }}
    QToolBar QToolButton {{ background: transparent; color: {p['text']}; border: 1px solid transparent; border-radius: 8px; padding: 5px 10px; }}
    QToolBar QToolButton:hover {{ background: {p['panel2']}; border-color: {p['border']}; }}
    QToolBar QToolButton:checked {{ background: {a22}; border-color: {a}; color: {a}; }}
    QToolButton#ptt {{ background: {a}; color: #0b0d12; font-weight: 700; padding: 6px 16px; border-radius: 12px; }}
    QToolButton#ptt:pressed, QToolButton#ptt:checked {{ background: #4fd1a1; }}
    QStatusBar {{ background: {p['panel']}; border-top: 1px solid {p['border']}; color: {p['muted']}; }}
    QStatusBar::item {{ border: none; }}
    QLabel#pill {{ background: {p['panel2']}; border: 1px solid {p['border']}; border-radius: 9px; padding: 2px 9px; color: {p['muted']}; }}
    QLabel#pill[live="true"] {{ color: {a}; border-color: {a66}; }}
    QLabel#caption {{ color: {p['muted']}; font-size: 13px; }}
    QLabel#persona {{ color: {p['text']}; font-size: 22px; font-weight: 600; letter-spacing: 1px; }}
    QLabel#state {{ color: {a}; font-size: 12px; font-weight: 700; letter-spacing: 3px; }}
    QLabel#transcript {{ color: {p['text']}; font-size: 17px; }}
    QLabel#spoken {{ color: {p['muted']}; font-size: 15px; font-style: italic; }}
    QTextEdit, QPlainTextEdit, QLineEdit, QListWidget, QTreeWidget, QTableWidget {{
        background: {p['input']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px; selection-background-color: {a66}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {a}; }}
    QPushButton {{ background: {p['panel2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 14px; }}
    QPushButton:hover {{ border-color: {a}; }}
    QPushButton:default, QPushButton#primary {{ background: {a}; color: #0b0d12; font-weight: 600; border-color: {a}; }}
    QPushButton#danger {{ background: rgba(255,107,107,51); border-color: #ff6b6b; }}
    QComboBox, QSpinBox, QDoubleSpinBox {{ background: {p['input']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 4px 8px; min-height: 22px; }}
    QComboBox QAbstractItemView {{ background: {p['panel']}; border: 1px solid {p['border']}; selection-background-color: {a44}; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {p['border']}; background: {p['input']}; }}
    QCheckBox::indicator:checked {{ background: {a}; border-color: {a}; }}
    QSlider::groove:horizontal {{ height: 4px; background: {p['border']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; background: {a}; border-radius: 7px; }}
    QListWidget#nav {{ background: {p['panel']}; border: none; border-right: 1px solid {p['border']}; border-radius: 0; padding: 8px 0; font-size: 14px; }}
    QListWidget#nav::item {{ padding: 9px 16px; border-radius: 0; }}
    QListWidget#nav::item:selected {{ background: {a22}; color: {a}; border-left: 3px solid {a}; }}
    QLabel#h1 {{ font-size: 20px; font-weight: 600; }}
    QLabel#h2 {{ font-size: 14px; font-weight: 600; color: {p['muted']}; margin-top: 10px; }}
    QLabel#hint {{ color: {p['muted']}; font-size: 12px; }}
    QGroupBox {{ border: 1px solid {p['border']}; border-radius: 10px; margin-top: 12px; padding: 12px 8px 8px 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {p['muted']}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QFrame#bubbleUser {{ background: {a26}; border: 1px solid {a55}; border-radius: 12px; }}
    QFrame#bubbleAssistant {{ background: {p['panel2']}; border: 1px solid {p['border']}; border-radius: 12px; }}
    QFrame#bubbleSystem {{ background: transparent; }}
    QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 8px; }}
    QTabBar::tab {{ background: {p['panel']}; padding: 6px 12px; border: 1px solid {p['border']}; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }}
    QTabBar::tab:selected {{ color: {a}; }}
    QHeaderView::section {{ background: {p['panel2']}; color: {p['muted']}; border: none; border-bottom: 1px solid {p['border']}; padding: 4px 6px; }}
    QToolTip {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['border']}; }}
    QMenu {{ background: {p['panel']}; border: 1px solid {p['border']}; }}
    QMenu::item:selected {{ background: {a33}; }}
    QProgressBar {{ border: 1px solid {p['border']}; border-radius: 6px; text-align: center; background: {p['input']}; }}
    QProgressBar::chunk {{ background: {a}; border-radius: 5px; }}
    """
