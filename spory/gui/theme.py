"""Night-charge theme: warm graphite, film grain, amber accent, one mono family."""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPixmap

FONT_DIR = Path(__file__).with_name("fonts")

INK_BG = "#13120F"
SURFACE = "#1A1915"
RAISED = "#23211C"
LINE = "#2F2C26"
INK = "#EEE7D7"
MUTED = "#958D7E"
FAINT = "#5C574D"
AMBER = "#F3A83B"
AMBER_DEEP = "#8A5A1C"
CORAL = "#E5674B"
SAGE = "#9CB59A"

MONO = "JetBrains Mono"


def color(hex_value: str, alpha: int = 255) -> QColor:
    c = QColor(hex_value)
    c.setAlpha(alpha)
    return c


def load_fonts() -> None:
    for path in sorted(FONT_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def font(family: str, size: float, weight: QFont.Weight = QFont.Weight.Normal, italic: bool = False) -> QFont:
    f = QFont(family)
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setItalic(italic)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def grain_tile(size: int = 160, strength: int = 14, seed: int = 7) -> QPixmap:
    """A tileable speckle of light and dark dots, like film grain."""
    rng = random.Random(seed)
    data = bytearray(size * size * 4)
    for i in range(0, len(data), 4):
        v = 255 if rng.random() < 0.5 else 0
        a = rng.randrange(strength)
        data[i : i + 4] = bytes((v, v, v, a))  # BGRA, premultiplied below by Qt
    image = QImage(bytes(data), size, size, QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(image.copy())


STYLESHEET = f"""
* {{
    color: {INK};
    selection-background-color: {AMBER};
    selection-color: {INK_BG};
}}
QToolTip {{
    background: {RAISED}; color: {INK}; border: 1px solid {LINE}; padding: 6px 8px;
}}
QLabel[role="key"] {{ color: {MUTED}; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="section"] {{ color: {MUTED}; }}
QFrame[role="rule"] {{ background: {LINE}; max-height: 1px; border: none; }}
QPushButton {{
    background: transparent;
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {MUTED}; background: rgba(238, 231, 215, 0.04); }}
QPushButton:pressed {{ background: rgba(238, 231, 215, 0.08); }}
QPushButton[kind="primary"] {{
    background: {AMBER}; color: {INK_BG}; border: 1px solid {AMBER}; font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{ background: #F7B95A; border-color: #F7B95A; }}
QPushButton[kind="primary"]:pressed {{ background: #D99230; }}
QPushButton[kind="solid"] {{ background: {INK}; color: {INK_BG}; border: 1px solid {INK}; font-weight: 600; }}
QPushButton[kind="solid"]:hover {{ background: #FFF8E8; border-color: #FFF8E8; }}
QPushButton[kind="solid"]:pressed {{ background: {MUTED}; }}
QPushButton[kind="ghost"] {{ border: none; color: {MUTED}; padding: 0; }}
QPushButton[kind="ghost"]:hover {{ color: {CORAL}; background: transparent; }}
QPushButton[kind="update"] {{
    border: 1px solid {MUTED}; border-radius: 12px; padding: 3px 10px; color: {INK};
}}
QPushButton[kind="update"]:hover {{ border-color: {INK}; background: rgba(238, 231, 215, 0.06); }}
QPushButton[kind="win"], QPushButton[kind="win-close"] {{
    border: none; border-radius: 4px; padding: 0; color: {MUTED}; font-size: 12pt;
}}
QPushButton[kind="win"]:hover {{ color: {INK}; background: rgba(238, 231, 215, 0.06); }}
QPushButton[kind="win-close"]:hover {{ color: {INK}; background: {CORAL}; }}
QPushButton[kind="tab"] {{
    border: none; border-radius: 0; padding: 4px 0; color: {MUTED};
    border-bottom: 2px solid transparent;
}}
QPushButton[kind="tab"]:hover {{ color: {INK}; background: transparent; }}
QPushButton[kind="tab"][active="true"] {{ color: {INK}; border-bottom: 2px solid {INK}; }}
QPushButton[kind="field"] {{
    background: {INK_BG}; border: 1px solid {LINE}; border-radius: 6px; padding: 0 8px; color: {INK};
}}
QPushButton[kind="field"]:hover {{ border-color: {MUTED}; background: {INK_BG}; }}
QPushButton[kind="field"][active="true"] {{ border-color: {INK}; }}
QFrame[role="field"] {{ background: {INK_BG}; border: 1px solid {LINE}; border-radius: 6px; }}
QFrame[role="field"]:hover {{ border-color: {MUTED}; }}
QFrame[role="field"][active="true"] {{ border-color: {INK}; }}
QLineEdit[kind="bare"] {{ background: transparent; border: none; padding: 0; }}
QPushButton[kind="step"] {{ border: none; border-radius: 4px; padding: 0; color: {MUTED}; font-size: 12pt; }}
QPushButton[kind="step"]:hover {{ color: {INK}; background: rgba(238, 231, 215, 0.06); }}
QPushButton[kind="step"]:disabled {{ color: {FAINT}; background: transparent; }}
QFrame[role="popup"] {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 10px; }}
QPushButton[kind="chip"] {{
    border: none; border-radius: 6px; padding: 0 6px; color: {INK}; background: transparent;
}}
QPushButton[kind="chip"]:hover {{ background: rgba(238, 231, 215, 0.08); }}
QPushButton[kind="chip"][active="true"] {{ background: {INK}; color: {INK_BG}; font-weight: 600; }}
QLineEdit, QTimeEdit, QSpinBox, QComboBox {{
    background: {INK_BG};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 5px 8px;
}}
QLineEdit:focus, QTimeEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {AMBER}; }}
QTimeEdit::up-button, QTimeEdit::down-button, QSpinBox::up-button, QSpinBox::down-button {{
    width: 0; border: none;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {RAISED}; border: 1px solid {LINE}; selection-background-color: {AMBER_DEEP};
    selection-color: {INK}; outline: none;
}}
QSlider::groove:horizontal {{ height: 2px; background: {LINE}; }}
QSlider::sub-page:horizontal {{ background: {SAGE}; }}
QSlider::handle:horizontal {{
    background: {INK}; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{ background: {AMBER}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMenu {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 16px; border-radius: 4px; }}
QMenu::item:selected {{ background: rgba(243, 168, 59, 0.16); }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 5px 8px; }}
"""


def dark_title_bar(widget) -> None:
    """Ask DWM for a dark caption on Windows 10/11."""
    if sys.platform != "win32":
        return
    import ctypes

    hwnd = int(widget.winId())
    value = ctypes.c_int(1)
    for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old)
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), 4) == 0:
            break
    caption = ctypes.c_int(0x000F1213)  # COLORREF of INK_BG (0x00BBGGRR)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)  # DWMWA_CAPTION_COLOR


def round_corners(widget) -> None:
    """Ask Windows 11 DWM to round a borderless window's corners."""
    if sys.platform != "win32":
        return
    import ctypes

    preference = ctypes.c_int(2)  # DWMWCP_ROUND
    ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 33, ctypes.byref(preference), 4)
