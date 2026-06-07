"""Modern dark theme for the desktop app.

Important rendering notes:
- Do NOT set `background-color: transparent` on QWidget globally. It causes
  paint trails / doubled text on Linux when widgets repaint without erasing.
  Backgrounds are set on the root widgets only; labels and similar
  transparent chrome opt in explicitly.
- Fonts: system UI everywhere except the log viewer, which is monospace.
"""
from __future__ import annotations


# ---- Color tokens -----------------------------------------------------------

BG          = "#0b0e14"   # canvas
SURFACE     = "#11161d"   # cards / inputs
SURFACE_HI  = "#161c25"   # hover / elevated
BORDER      = "#1e2630"
BORDER_HI   = "#2a3441"
TEXT        = "#e6ebf2"
TEXT_DIM    = "#9aa5b1"
TEXT_MUTED  = "#5f6b78"

ACCENT      = "#5b8cff"
ACCENT_HI   = "#7aa3ff"
POSITIVE    = "#3ed598"
WARNING     = "#ffc46b"
DANGER      = "#ff6262"


UI_FONT_STACK = (
    '"Inter", "SF Pro Text", "-apple-system", "Segoe UI Variable",'
    ' "Segoe UI", "Ubuntu", "Roboto", "Helvetica Neue", sans-serif'
)

MONO_FONT_STACK = (
    '"JetBrains Mono", "Cascadia Code", "SF Mono", "Consolas",'
    ' "Menlo", "DejaVu Sans Mono", monospace'
)


STYLE_QSS = f"""
QWidget {{
    font-family: {UI_FONT_STACK};
    font-size: 15pt;
}}

QMainWindow,
QDialog,
QWidget#centralWidget {{
    background-color: {BG};
    color: {TEXT};
}}

/* Transparent surfaces — opt-in, NOT global. Setting transparent on
   QWidget globally causes paint trails on X11. */
QLabel,
QFrame,
QSplitter,
QTabBar,
QHeaderView,
QStatusBar > QLabel {{
    background-color: transparent;
}}

QLabel {{
    color: {TEXT};
}}

/* ---------- Section labels ---------- */
QLabel#sectionTitle {{
    color: {TEXT_DIM};
    font-size: 13pt;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 0 2px 6px 2px;
}}

QLabel#statusText {{
    font-size: 32pt;
    font-weight: 700;
    letter-spacing: -0.5px;
}}

QLabel#statusDot {{
    font-size: 32pt;
}}

QLabel#metaBadge {{
    color: {TEXT_DIM};
    font-size: 13pt;
    padding: 7px 12px;
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QLabel#hint {{
    color: {TEXT_DIM};
    font-size: 13pt;
}}

/* ---------- Buttons ---------- */
QPushButton {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 11px 20px;
    font-weight: 600;
    font-size: 15pt;
}}
QPushButton:hover {{
    background-color: {SURFACE_HI};
    border-color: {BORDER_HI};
}}
QPushButton:pressed {{
    background-color: {BORDER};
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background-color: {SURFACE};
    border-color: {BORDER};
}}

QPushButton#primaryButton {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: white;
}}
QPushButton#primaryButton:hover {{
    background-color: {ACCENT_HI};
    border-color: {ACCENT_HI};
}}
QPushButton#primaryButton:disabled {{
    background-color: {SURFACE};
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}

QPushButton#dangerButton {{
    background-color: {SURFACE};
    color: {DANGER};
    border: 1px solid {BORDER};
}}
QPushButton#dangerButton:hover {{
    background-color: {SURFACE_HI};
    border-color: {DANGER};
}}
QPushButton#dangerButton:disabled {{
    color: {TEXT_MUTED};
}}

QPushButton#ghostButton {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {TEXT_DIM};
    padding: 8px 14px;
    font-size: 14pt;
}}
QPushButton#ghostButton:hover {{
    color: {TEXT};
    background-color: {SURFACE};
}}

/* ---------- Inputs ---------- */
QLineEdit,
QPlainTextEdit,
QTextEdit,
QComboBox {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {ACCENT};
    selection-color: white;
    padding: 10px 12px;
    font-size: 15pt;
}}
QLineEdit:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QComboBox:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled,
QPlainTextEdit:disabled {{
    color: {TEXT_MUTED};
    background-color: {BG};
}}

QPlainTextEdit#logView {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-family: {MONO_FONT_STACK};
    font-size: 13pt;
    padding: 12px;
}}

/* ---------- Tables ---------- */
QTableWidget {{
    background-color: {SURFACE};
    alternate-background-color: {SURFACE_HI};
    color: {TEXT};
    gridline-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-size: 15pt;
}}
QTableWidget::item {{
    padding: 12px 14px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {SURFACE_HI};
    color: {TEXT};
}}
QHeaderView::section {{
    background-color: {SURFACE};
    color: {TEXT_DIM};
    padding: 12px 14px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
    font-size: 13pt;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QHeaderView::section:first {{
    border-top-left-radius: 10px;
}}
QHeaderView::section:last {{
    border-top-right-radius: 10px;
}}
QTableCornerButton::section {{
    background-color: {SURFACE};
    border: none;
}}

/* ---------- Tabs (settings dialog) ---------- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    top: -1px;
    background-color: {SURFACE};
    padding: 10px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {TEXT_DIM};
    padding: 12px 22px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 4px;
    font-weight: 500;
    font-size: 15pt;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover {{
    color: {TEXT};
}}

/* ---------- Checkboxes ---------- */
QCheckBox {{
    color: {TEXT};
    spacing: 12px;
    font-size: 15pt;
    padding: 4px 0;
    background-color: transparent;
}}
QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border: 1px solid {BORDER_HI};
    border-radius: 4px;
    background-color: {SURFACE};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    image: none;
}}

/* ---------- Status bar / splitter ---------- */
QStatusBar {{
    background-color: {BG};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
    font-size: 12pt;
}}
QStatusBar QLabel {{
    color: {TEXT_MUTED};
    font-size: 12pt;
}}
QStatusBar::item {{
    border: none;
}}

QSplitter::handle {{
    background-color: transparent;
}}
QSplitter::handle:vertical {{
    height: 12px;
}}

/* ---------- Scrollbars ---------- */
QScrollBar:vertical {{
    background-color: {BG};
    width: 14px;
    border: none;
    margin: 4px 0;
}}
QScrollBar::handle:vertical {{
    background-color: {BORDER_HI};
    min-height: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {TEXT_MUTED};
}}
QScrollBar:horizontal {{
    background-color: {BG};
    height: 14px;
    border: none;
    margin: 0 4px;
}}
QScrollBar::handle:horizontal {{
    background-color: {BORDER_HI};
    min-width: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {TEXT_MUTED};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    background: none;
    border: none;
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}

/* ---------- Tooltips & dialogs ---------- */
QToolTip {{
    background-color: {SURFACE_HI};
    color: {TEXT};
    border: 1px solid {BORDER_HI};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13pt;
}}
QMessageBox {{
    background-color: {BG};
}}
QMessageBox QLabel {{
    color: {TEXT};
    font-size: 14pt;
}}
"""


STATUS_COLORS = {
    "idle":     (TEXT_MUTED, "Idle"),
    "starting": (WARNING,    "Connecting…"),
    "running":  (POSITIVE,   "Live"),
    "stopped":  (TEXT_MUTED, "Stopped"),
    "error":    (DANGER,     "Error"),
}

LOG_LEVEL_COLORS = {
    "DEBUG":    TEXT_MUTED,
    "INFO":     TEXT,
    "WARNING":  WARNING,
    "ERROR":    DANGER,
    "CRITICAL": DANGER,
}

BROKER_STATUS_COLORS = {
    "ok":       POSITIVE,
    "skip":     TEXT_MUTED,
    "error":    DANGER,
    "checking": WARNING,
}

BROKER_STATUS_LABEL = {
    "ok":       "Connected",
    "skip":     "Not configured",
    "error":    "Failed",
    "checking": "Checking…",
}
