"""Application styling: colours, stylesheet, palette and inline icons."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ACCENT = "#D94B43"
ACCENT_HOVER = "#E35C54"
ACCENT_PRESSED = "#C03F38"
ACCENT_TINT = "#3A2624"
BACKGROUND = "#1C1D20"
SURFACE = "#25272B"
SURFACE_HOVER = "#2E3035"
BORDER = "#36393F"
TEXT = "#ECECEE"
TEXT_MUTED = "#9A9DA4"
TEXT_DISABLED = "#62656C"
SUCCESS = "#5DBB82"
SUCCESS_TINT = "#203229"
ERROR = "#F07A72"
WARNING = "#E6B35A"

FONT_FAMILIES = ["Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans", "Sans Serif"]

STYLESHEET = f"""
QWidget#root {{
    background: {BACKGROUND};
}}
QWidget {{
    color: {TEXT};
    font-size: 13px;
}}
QLabel#appTitle {{
    font-size: 17px;
    font-weight: 600;
}}
QLabel#appSubtitle, QLabel[muted="true"] {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#headline {{
    font-size: 15px;
    font-weight: 600;
}}
QLabel#videoTitle {{
    font-size: 13px;
    font-weight: 600;
}}
QLabel#hint {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#hint[state="error"] {{
    color: {ERROR};
}}
QLabel#hint[state="info"] {{
    color: {SUCCESS};
}}
QLabel#warning {{
    color: {WARNING};
}}
QLabel#thumbnail {{
    background: {SURFACE_HOVER};
    border-radius: 6px;
}}
QLabel#badgeSuccess {{
    background: {SUCCESS_TINT};
    border-radius: 26px;
}}
QLabel#badgeError {{
    background: {ACCENT_TINT};
    border-radius: 26px;
}}
QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#card QLabel {{
    background: transparent;
}}
QLineEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 6px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 14px;
    min-height: 20px;
}}
QPushButton:hover {{
    background: {SURFACE_HOVER};
}}
QPushButton:pressed {{
    background: {BORDER};
}}
QPushButton:disabled {{
    color: {TEXT_DISABLED};
}}
QPushButton#primary {{
    background: {ACCENT};
    border: none;
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 600;
    padding: 10px 16px;
}}
QPushButton#primary:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#primary:pressed {{
    background: {ACCENT_PRESSED};
}}
QPushButton#primary:disabled {{
    background: {ACCENT_TINT};
    color: {TEXT_MUTED};
}}
QToolButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px;
}}
QToolButton:hover {{
    background: {SURFACE_HOVER};
}}
QProgressBar {{
    background: {SURFACE_HOVER};
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}
QToolTip {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 6px;
}}
QMessageBox {{
    background: {BACKGROUND};
}}
"""

_ICON_PATHS = {
    "clipboard": '<rect x="8" y="2" width="8" height="4" rx="1"/>'
    '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
    '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9'
    'A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
    '<polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "alert": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>'
    '<line x1="12" y1="16" x2="12.01" y2="16"/>',
    "close": '<path d="M18 6 6 18M6 6l12 12"/>',
    "retry": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    "film": '<rect x="2" y="2" width="20" height="20" rx="2.5"/><path d="M7 2v20M17 2v20M2 12h20'
    'M2 7h5M2 17h5M17 17h5M17 7h5"/>',
}


def icon_pixmap(name: str, size: int, color: str = TEXT_MUTED, scale: float = 2.0) -> QPixmap:
    """Render one of the inline line icons at *size* logical pixels."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f"{_ICON_PATHS[name]}</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixels = round(size * scale)
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def icon(name: str, size: int = 18, color: str = TEXT_MUTED) -> QIcon:
    return QIcon(icon_pixmap(name, size, color))


def apply_theme(app: QApplication) -> None:
    """Dark Fusion palette (also used by dialogs) plus the app stylesheet."""
    app.setStyle("Fusion")

    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: BACKGROUND,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE,
        QPalette.ColorRole.AlternateBase: SURFACE_HOVER,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: SURFACE,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: SURFACE,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_DISABLED,
        QPalette.ColorRole.Link: ACCENT_HOVER,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_DISABLED))
    app.setPalette(palette)

    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)

    app.setStyleSheet(STYLESHEET)
