"""
industrial_theme.py — Industrial HMI design system for SecureGuard.

Provides a single source of truth for colour, density and typography so every
tab, panel and control reads like plant-floor SCADA software rather than a
default desktop widget set.

Palette conventions follow industrial HMI practice:
  * graphite/steel surfaces so the UI recedes behind the process data
  * amber as the primary action colour (readable under harsh lighting)
  * explicit signal green / caution amber / alarm red reserved for state only
  * monospaced faces for every measured value so digits do not jitter

The styling contract is deliberately austere, because it is safety-critical
chrome and not decoration:
  * flat solid fills only — no gradients of any kind
  * sharp 90-degree corners only — zero corner rounding anywhere
  * crisp 1px borders, no shadows of any kind
  * dense metrics, so panels tile like dashboard tiles instead of floating cards

Violating any of those four rules makes a widget read as consumer software to
an operator, which is how real incidents start. Keep this file flat.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QTableWidget,
    QWidget,
    QFrame,
)


# ---------------------------------------------------------------------------
# Colour tokens
# ---------------------------------------------------------------------------

# Structure
BG_DEEP = "#0b0e13"        # window backdrop
BG_PANEL = "#161b22"       # panel body
BG_PANEL_HI = "#1f2630"    # panel top highlight
BG_CARD = "#131920"        # nested card
BG_INSET = "#0e1319"       # inset / well
BORDER = "#2b3440"         # standard 1px divider
BORDER_HI = "#3d4b5c"      # emphasised divider

# Type
TEXT = "#e6edf3"
TEXT_DIM = "#8b98a5"
TEXT_FAINT = "#5b6672"

# Brand / action
ACCENT = "#f0a500"         # industrial amber
ACCENT_HI = "#ffbe2e"
ACCENT_DEEP = "#b87d00"
BLUE = "#4a9eff"
CYAN = "#2fbfc9"
VIOLET = "#a879f0"

# Semantic state — never use these for decoration
OK = "#3fb950"             # running / safe
OK_DIM = "#1f6f30"
WARN = "#d29922"           # caution
WARN_DIM = "#7a5a12"
ALARM = "#f85149"          # fault / trip
ALARM_DIM = "#7d2823"
IDLE = "#6e7b8a"           # stopped / unknown
OFFLINE = "#484f58"
RESTRICTED = "#ff9800"     # governance-blocked. Deliberately neither WARN nor
                           # ALARM: a process warning and a permission denial
                           # need different operator responses, so this stays
                           # its own token instead of an inline literal.

ROSE = "#e8558f"          # flat series colour for the temperature subsystem

# Data-series colours (charts)
# ROSE replaced a pastel coral literal that was sitting in this list.
# A series token has to read as an identity, not as a decoration: that coral
# measured a perceptual distance (CIE76 dE) of only 27 from ALARM, so on a trend
# chart a subsystem could be mistaken for a tripped channel, and its low chroma
# made it the one washed-out trace in an otherwise flat set. ROSE is a flat,
# fully saturated rose: dE 42 from ALARM, 56 from VIOLET, 91 from ACCENT, and
# 5.4:1 contrast against BG_INSET. It is deliberately in the magenta half of the
# wheel rather than the coral half - a true coral would put the temperature
# series back within a few degrees of hue of the alarm red, which is the exact
# confusion the palette tokens exist to prevent.
SERIES = [BLUE, CYAN, ACCENT, VIOLET, OK, ALARM, WARN, ROSE]

# Font stacks
FONT_UI = "Segoe UI"       # rigid system face for labels and controls
FONT_MONO = "Consolas"     # safe default; resolve_mono_family() refines this
FONT_DISPLAY = "Bahnschrift"
# Bahnschrift is a Windows system font and is used for state headlines
# (RUNNING / QUARANTINED) where legibility at a glance decides operator
# response time. It is not decorative — do not "modernise" it away, and do not
# feed it numbers, because it is not monospaced.

# ---------------------------------------------------------------------------
# Density contract (pixels)
# ---------------------------------------------------------------------------
# Later waves shrink padding with these instead of inventing per-file values;
# that is the only way the app stays uniformly dense.

BORDER_W = 1
PAD_X = 6        # horizontal padding: inputs, table cells, list rows (was 4)
PAD_Y = 3        # vertical padding: same (was 2)
GAP = 6          # layout spacing between sibling controls (was 4)
BTN_PAD_X = 14   # was 10
BTN_PAD_Y = 5    # was 3
TAB_PAD_X = 16   # was 12
TAB_PAD_Y = 6    # was 4
ROW_H = 22       # default table row height (was 18)

# Plot contract — one grid alpha for every chart in the app, so a reviewer
# comparing two panels never sees two different "subtle" grid treatments.
GRID_ALPHA = 0.3
TICK_PT = 10     # axis tick font, in points (was 8)
LABEL_PT = 11    # axis label font, in points (was 9)


# ---------------------------------------------------------------------------
# Font resolution
# ---------------------------------------------------------------------------

# Probe order matters. An HMI needs a fixed digit advance, otherwise numeric
# columns jitter every time a value changes width — which reads as instability
# even when the data is steady. JetBrains Mono is the most legible at 8pt, SF
# Mono is the macOS equivalent, Consolas is the guaranteed Windows fallback.
_MONO_CANDIDATES = ("JetBrains Mono", "SF Mono", "Consolas")
_MONO_FALLBACK = "monospace"
_MONO_CACHE = None


def resolve_mono_family(app=None) -> str:
    """
    Return the best available monospace family, probing once and caching.

    ``app`` may be omitted; the existing ``QApplication.instance()`` is used
    instead. When no application exists yet the font database cannot be queried
    (it is loaded with the GUI stack), so the generic ``monospace`` family is
    returned *without* caching, and the next call with a live application still
    performs the real probe.

    The same fallback covers a platform plugin that reports an empty font
    database (the headless ``offscreen`` plugin does), so a verification run on
    a machine with no named family still renders with a fixed digit advance
    rather than a proportional fallback.
    """
    global _MONO_CACHE
    if _MONO_CACHE is not None:
        return _MONO_CACHE

    probe = app if app is not None else QApplication.instance()
    if probe is None:
        return _MONO_FALLBACK

    try:
        families = set(QFontDatabase.families())
    except Exception:
        families = set()

    chosen = _MONO_FALLBACK
    for name in _MONO_CANDIDATES:
        if name in families:
            chosen = name
            break
    _MONO_CACHE = chosen
    return chosen


def numeric_font(size: int = 13, weight=None) -> QFont:
    """
    Build the standard telemetry font: resolved monospace at a given size.

    Every measured value, timestamp and identifier in the app should use this
    so digits share one advance width.
    """
    if weight is None:
        weight = QFont.Weight.Normal
    return QFont(resolve_mono_family(), size, weight)


# A QApplication may already exist when this module is first imported (a tab
# module imported from a running shell), so pick up the resolved family now
# rather than leaving every downstream `from industrial_theme import FONT_MONO`
# holding the import-time default.
if QApplication.instance() is not None:
    FONT_MONO = resolve_mono_family()


def state_color(state: str) -> str:
    """Map a conveyor state string to its HMI colour."""
    key = (state or "").strip().upper()
    if key in ("RUNNING", "NORMAL", "ACCEPTED", "COMPLETED"):
        return OK
    if key in ("DEGRADED", "WARNING", "CAUTION", "RECOVERING"):
        return WARN
    if key in ("RESTRICTED", "BLOCKED"):
        # Governance-restricted: amber. Distinct from DEGRADED so an operator
        # can tell "running badly" apart from "not permitted to run".
        return RESTRICTED
    if key in ("JAMMED", "FAULT", "TRIPPED", "ESTOP", "QUARANTINED", "ALARM"):
        return ALARM
    if key in ("STOPPED", "IDLE", "OFFLINE"):
        return IDLE
    return TEXT_DIM


def risk_color(level: str) -> str:
    """Map a risk level to its HMI colour."""
    key = (level or "").strip().upper()
    if key in ("LOW", "MINIMAL", "NORMAL"):
        return OK
    if key in ("MEDIUM", "MODERATE", "ELEVATED"):
        return WARN
    if key in ("HIGH", "CRITICAL", "SEVERE"):
        return ALARM
    return TEXT_DIM


# ---------------------------------------------------------------------------
# Widget helpers
# ---------------------------------------------------------------------------

def gradient_style(
    top: str = BG_PANEL_HI,
    bottom: str = BG_PANEL,
    border: str = BORDER,
    radius: int = 8,
    accent_top: str = "",
) -> str:
    """
    Build a flat panel style sheet.

    Historically this emitted a vertical gradient; the design contract forbids
    gradients, so the body is now the flat ``top`` (formerly ``stop:0``) colour
    and the visual weight of a raised panel is unchanged. ``accent_top`` still
    marks the top edge, as a 1px strip rather than a gradient stop.

    ``radius`` and ``bottom`` are accepted and ignored: call sites across the
    tabs still pass them, and silently changing those signatures would break
    the waves that have not been rewritten yet.
    """
    strip = f" border-top: 1px solid {accent_top};" if accent_top else ""
    return (
        f"QFrame {{"
        f" background-color: {top};"
        f" border: 1px solid {border};"
        f"{strip}"
        f"}}"
    )


def led_style(color: str, size: int = 10) -> str:
    """
    Style sheet for a small LED indicator.

    The indicator is a sharp square: a rounded LED is a consumer idiom, and the
    1px OFFLINE border supplies the machined edge the old circle implied.
    """
    return (
        f"QLabel {{ background: {color};"
        f" border: 1px solid {OFFLINE};"
        f" min-width: {size}px; max-width: {size}px;"
        f" min-height: {size}px; max-height: {size}px; }}"
    )


def apply_panel(widget: QWidget, accent: str = "", radius: int = 8):
    """Apply the standard flat panel treatment to a QFrame."""
    if not isinstance(widget, QFrame):
        return
    widget.setFrameShape(QFrame.Shape.NoFrame)
    # All styling funnels through gradient_style, so flattening that one factory
    # is enough to flatten every panel in the app.
    widget.setStyleSheet(gradient_style(accent_top=accent, radius=radius))


def apply_monospace(label: QWidget, size: int = 12, color: str = TEXT):
    """Give a value label the monospaced industrial look."""
    label.setFont(numeric_font(size))
    label.setStyleSheet(f"color: {color}; background: transparent;")


def apply_label(label: QWidget, size: int = 11, color: str = TEXT_DIM, bold: bool = False):
    """Give a caption label the standard industrial look."""
    label.setFont(
        QFont(
            FONT_UI,
            size,
            QFont.Weight.DemiBold if bold else QFont.Weight.Normal,
        )
    )
    label.setStyleSheet(f"color: {color}; background: transparent;")


# ---------------------------------------------------------------------------
# Global stylesheet
# ---------------------------------------------------------------------------

# The family baked into the sheet below. apply_theme() re-points it once a
# QApplication exists and the real monospace family is known.
_QSS_MONO = FONT_MONO

INDUSTRIAL_QSS = f"""
/* ---- window ---- */
/* Deliberately NO background and NO font-family on the generic QWidget rule.
   A background would paint a flat rectangle behind every label and child,
   flattening the panel structure. A font-family is worse than useless: Qt
   resolves a sheet font over the widget font when the widget is polished, so
   `setFont(numeric_font(...))` was silently discarded and every numeric readout
   rendered in the proportional UI face. That forced three waves to repeat the
   resolved family in a widget-level sheet purely to defeat this rule, on every
   numeric label, which is fragile and will bite the next numeric widget. The
   family now comes from the widget font (numeric_font()) or, failing that, from
   apply_theme()'s application font; this rule owns size and colour only. */
QWidget {{
    color: {TEXT};
    font-size: 10px;
}}
QMainWindow, QDialog {{ background-color: {BG_DEEP}; }}
QWidget[role="canvas"] {{ background-color: {BG_DEEP}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: {BG_INSET}; }}

/* Labels and layout spacers must never own a background, otherwise they punch
   opaque holes through whatever panel sits behind them. */
QLabel, QCheckBox, QRadioButton {{
    background: transparent;
}}
QLabel[bg="true"] {{ background: {BG_INSET}; }}

/* ---- headers / section titles ---- */
QLabel[role="title"] {{
    color: {TEXT};
    font-family: '{FONT_DISPLAY}', '{FONT_UI}';
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel[role="subtitle"] {{
    color: {TEXT_FAINT};
    font-size: 9px;
    letter-spacing: 2px;
}}
QLabel[role="caption"] {{
    color: {TEXT_DIM};
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1px;
}}

/* ---- buttons ---- */
QPushButton {{
    background-color: #2b3440;
    color: {TEXT};
    border: {BORDER_W}px solid {BORDER_HI};
    padding: {BTN_PAD_Y}px {BTN_PAD_X}px;
    font-weight: 600;
    letter-spacing: 1px;
    min-height: 13px;
}}
QPushButton:hover {{
    background-color: #38434f;
    border: {BORDER_W}px solid {ACCENT_DEEP};
}}
QPushButton:pressed {{
    background-color: #1b2129;
}}
QPushButton:disabled {{
    color: {TEXT_FAINT};
    background-color: #171c23;
    border: {BORDER_W}px solid #232a33;
}}
QPushButton:checked {{
    background-color: {ACCENT};
    color: #12161c;
    border: {BORDER_W}px solid {ACCENT_HI};
}}
QPushButton[action="primary"] {{
    background-color: {ACCENT_HI};
    color: #14181e;
    border: {BORDER_W}px solid {ACCENT_HI};
    font-weight: 700;
}}
QPushButton[action="primary"]:hover {{
    background-color: #ffd05c;
}}
QPushButton[action="danger"] {{
    background-color: {ALARM};
    color: #fff2f1;
    border: {BORDER_W}px solid {ALARM};
    font-weight: 700;
}}
QPushButton[action="danger"]:hover {{
    background-color: {ALARM};
}}

/* ---- tabs ---- */
QTabWidget::pane {{
    border: {BORDER_W}px solid {BORDER};
    background-color: {BG_PANEL};
    top: -1px;
}}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background-color: #1c222a;
    color: {TEXT_DIM};
    border: {BORDER_W}px solid {BORDER};
    border-bottom: 2px solid {OFFLINE};
    padding: {TAB_PAD_Y}px {TAB_PAD_X}px;
    margin-right: 2px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QTabBar::tab:hover {{
    color: {TEXT};
    background-color: #232a33;
}}
QTabBar::tab:selected {{
    background-color: {ACCENT};
    color: #14181e;
    border-bottom: 2px solid {ACCENT_HI};
    font-weight: 700;
}}

/* ---- inputs ---- */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {BG_INSET};
    color: {TEXT};
    border: {BORDER_W}px solid {BORDER_HI};
    padding: {PAD_Y}px {PAD_X}px;
    selection-background-color: {ACCENT};
    selection-color: #14181e;
    font-family: '{_QSS_MONO}';
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border: {BORDER_W}px solid {ACCENT};
}}
QLineEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {TEXT_FAINT};
    background-color: {BG_INSET};
}}
QComboBox::drop-down {{
    border-left: {BORDER_W}px solid {BORDER_HI};
    width: 14px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {TEXT_DIM};
    width: 0; height: 0;
    margin-right: 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_INSET};
    color: {TEXT};
    border: {BORDER_W}px solid {BORDER_HI};
    selection-background-color: {ACCENT};
    selection-color: #14181e;
    outline: none;
}}

/* spin buttons */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: #232a33;
    border-left: {BORDER_W}px solid {BORDER_HI};
    width: 12px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {ACCENT_DEEP};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 2px solid transparent; border-right: 2px solid transparent;
    border-bottom: 3px solid {TEXT}; width: 0; height: 0;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 2px solid transparent; border-right: 2px solid transparent;
    border-top: 3px solid {TEXT}; width: 0; height: 0;
}}

/* ---- checkbox ---- */
QCheckBox {{ color: {TEXT}; spacing: 5px; }}
QCheckBox::indicator {{
    width: 12px; height: 12px;
    border: {BORDER_W}px solid {BORDER_HI};
    background: {BG_INSET};
}}
QCheckBox::indicator:hover {{ border: {BORDER_W}px solid {ACCENT}; }}
/* No tick image: a filled solid block is the flat equivalent of a check mark
   and keeps the widget free of raster assets. */
QCheckBox::indicator:checked {{
    background-color: {ACCENT_HI};
    border: {BORDER_W}px solid {ACCENT_HI};
}}

/* ---- tables ---- */
QTableWidget, QTableView {{
    background-color: {BG_INSET};
    gridline-color: {BORDER_HI};
    border: {BORDER_W}px solid {BORDER};
    selection-background-color: rgba(240, 165, 0, 45);
    selection-color: {TEXT};
    alternate-background-color: {BG_INSET};
}}
QTableWidget::item {{ padding: {PAD_Y}px {PAD_X}px; }}
QTableWidget::item:selected {{ background: rgba(240, 165, 0, 45); color: {TEXT}; }}
QHeaderView::section {{
    background-color: #232b35;
    color: {TEXT_DIM};
    border: none;
    border-right: {BORDER_W}px solid {BORDER};
    border-bottom: 2px solid {ACCENT_DEEP};
    padding: {PAD_Y}px 5px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QHeaderView::section:hover {{ color: {TEXT}; }}
QTableCornerButton::section {{
    background-color: #1a2029;
    border: none;
    border-bottom: 2px solid {ACCENT_DEEP};
}}

/* ---- tree ---- */
QTreeWidget, QTreeView {{
    background: {BG_INSET};
    border: {BORDER_W}px solid {BORDER};
}}
QTreeWidget::item, QTreeView::item {{ padding: {PAD_Y}px {PAD_X}px; }}
QTreeWidget::item:selected, QTreeView::item:selected {{
    background: rgba(240, 165, 0, 40);
    color: {TEXT};
}}

/* ---- group box ---- */
QGroupBox {{
    border: {BORDER_W}px solid {BORDER};
    /* margin-top is the gutter the title is drawn in and is load-bearing:
       subcontrol-origin: margin below places ::title inside it. There is
       deliberately NO padding-top here. padding-top stacked on margin-top, so
       the first row of every group box sat 8 + 6 = 14px below the border (24px
       with the grid's own default margin) while a plain QFrame panel's content
       sat at 8px - two different insets for the same job. */
    margin-top: 8px;
    background: {BG_PANEL};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 6px;
    padding: 0 3px;
    color: {ACCENT};
    font-weight: 700;
    letter-spacing: 1px;
}}

/* ---- slider ---- */
QSlider::groove:horizontal {{
    height: 5px;
    background: {BG_INSET};
    border: {BORDER_W}px solid {BORDER};
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT_DEEP};
}}
/* A sharp 10x10 block, not a pill: the flat handle is what makes the control
   read as an instrument setpoint rather than a media scrubber. */
QSlider::handle:horizontal {{
    background: {ACCENT};
    border: {BORDER_W}px solid {ACCENT_HI};
    width: 10px;
    height: 10px;
    margin: -3px 0;
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HI}; }}

/* ---- progress ---- */
QProgressBar {{
    border: {BORDER_W}px solid {BORDER};
    background: {BG_INSET};
    text-align: center;
    color: {TEXT};
    font-family: '{_QSS_MONO}';
    height: 12px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT_DEEP};
}}

/* ---- scrollbars ---- */
QScrollBar:vertical {{
    background: {BG_DEEP};
    width: 9px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: #2b3440;
    border: {BORDER_W}px solid {BORDER};
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DEEP}; }}
QScrollBar:horizontal {{
    background: {BG_DEEP};
    height: 9px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: #2b3440;
    border: {BORDER_W}px solid {BORDER};
    min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{ background: {ACCENT_DEEP}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---- status bar ---- */
QStatusBar {{
    background-color: #1a2029;
    color: {TEXT_DIM};
    border-top: {BORDER_W}px solid {BORDER};
    font-family: '{_QSS_MONO}';
    font-size: 9px;
    padding: 1px 4px;
}}
QStatusBar::item {{ border: none; }}

/* ---- splitters ---- */
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}
QSplitter::handle:hover {{ background: {ACCENT_DEEP}; }}

/* ---- tooltips ---- */
QToolTip {{
    background: {BG_CARD};
    color: {TEXT};
    border: {BORDER_W}px solid {ACCENT_DEEP};
    padding: {PAD_Y}px {PAD_X}px;
}}

/* ---- lists ---- */
QListWidget {{
    background: {BG_INSET};
    border: {BORDER_W}px solid {BORDER};
}}
QListWidget::item {{ padding: {PAD_Y}px {PAD_X}px; border-bottom: {BORDER_W}px solid #1a212a; }}
QListWidget::item:selected {{ background: rgba(240, 165, 0, 40); color: {TEXT}; }}

/* ---- native modals ----
   QMessageBox and QFileDialog are the only surfaces Qt paints outside our rule
   set, so they would otherwise fall back to the Fusion look. The Export JSONL
   path opens a QFileDialog, and a governance export must not look like a
   consumer file picker. */
QMessageBox {{
    background-color: {BG_PANEL};
    border: {BORDER_W}px solid {BORDER_HI};
}}
QMessageBox QLabel {{ background: transparent; color: {TEXT}; }}
QMessageBox QPushButton {{ min-width: 64px; }}
QFileDialog {{
    background-color: {BG_PANEL};
    border: {BORDER_W}px solid {BORDER_HI};
}}
QFileDialog QListView, QFileDialog QTreeView {{
    background: {BG_INSET};
    border: {BORDER_W}px solid {BORDER};
}}
QFileDialog QToolButton {{
    background-color: {BG_PANEL_HI};
    border: {BORDER_W}px solid {BORDER_HI};
    padding: 1px 4px;
}}
QFileDialog QLineEdit {{ padding: {PAD_Y}px {PAD_X}px; }}
"""


def apply_theme(app: QApplication):
    """Install the SecureGuard industrial stylesheet on the application."""
    # Load-bearing, do not remove: Fusion is the only style that lets a QSS
    # paint scrollbars, inputs and native dialogs. Under the Windows style, Qt
    # re-introduces Aero rounded corners and translucent chrome on every modal.
    app.setStyle("Fusion")

    # The sheet is rendered at import time, before a QApplication exists, so
    # the monospace family is still the safe default. Now that the GUI stack is
    # up, re-point every monospace rule at the family we actually resolved.
    # Modules that did `from industrial_theme import INDUSTRIAL_QSS` hold the
    # import-time copy, so read this module attribute after apply_theme() rather
    # than the imported name.
    global FONT_MONO, INDUSTRIAL_QSS
    resolved = resolve_mono_family(app)
    if resolved != FONT_MONO:
        FONT_MONO = resolved
        INDUSTRIAL_QSS = INDUSTRIAL_QSS.replace(
            f"'{_QSS_MONO}'", f"'{resolved}'"
        )

    app.setStyleSheet(INDUSTRIAL_QSS)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_DEEP))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_INSET))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_INSET))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_PANEL_HI))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#14181e"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_CARD))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    app.setPalette(palette)

    # One deliberate UI size for the whole app. dashboard_qt sets 9pt on line
    # before calling us, and this overrides it; two competing sizes is how
    # numeric columns end up ragged, so the single 10pt size wins and the 9pt
    # call is dead weight that later waves should delete.
    app.setFont(QFont(FONT_UI, 10))

    # Telemetry face for the view WIDGETS, set centrally.
    # QStyledItemDelegate does not take an item's font from the view, which is
    # why style_table() alone could not put the cells in the telemetry face and
    # every table had to carry the font on each item instead. Naming the family
    # on the application classes removes the second half of that problem: a
    # QHeaderView, and any QTableWidget/QTableView that never had setFont() called
    # on it, now inherit the monospace face, so a header and the column under it
    # cannot disagree about digit advance.
    #
    # Verified headless on this Qt build, and deliberately stated plainly: it does
    # NOT reach item rendering. An item with no Qt::FontRole still falls back to
    # the application default font (the Segoe UI 10pt set below), for a
    # widget-backed table and a model-backed view alike. The per-item font calls
    # already in dashboard_qt and evidence_tab therefore stay; what this changes
    # is that a table with plain items no longer frames its columns in a different
    # face from the data inside them.
    mono = QFont(resolve_mono_family(app), 9)
    for role in ("QTableView", "QTableWidget", "QHeaderView"):
        try:
            app.setFont(mono, role)
        except (TypeError, RuntimeError):
            continue

    if hasattr(app, "sg_themed"):
        return
    app.sg_themed = True


# ---------------------------------------------------------------------------
# pyqtgraph dark theme
# ---------------------------------------------------------------------------

def apply_plot_theme(pg):
    """
    Align pyqtgraph rendering with the application chrome.

    Grid lines are drawn with each axis' own pen, so the real grid colour is
    controlled by the axis pen set in style_plot() plus showGrid(alpha), not by
    a config option. "antialias" is set explicitly because trace smoothing is
    never acceptable on a step plot: it hides real inflections in the data.
    """
    options = {
        "background": BG_INSET,
        "foreground": TEXT_DIM,
        "antialias": False,
        "ui.background": BG_INSET,
        "ui.borderColor": BORDER,
        "ui.buttonColor": BG_PANEL_HI,
        "ui.font": FONT_UI,
    }
    # Option names drift between pyqtgraph releases, so apply what this build
    # actually accepts instead of raising on an unknown key. ("grid.color" used
    # to sit in this dict; pyqtgraph has never read that key, which is why the
    # real grid colour was never applied and nobody could work out why.)
    for key, value in options.items():
        try:
            pg.setConfigOption(key, value)
        except (KeyError, TypeError, ValueError):
            continue


def trace_pen(color, width: int = BORDER_W):
    """
    Build a chart pen in the industrial contract: solid, 1px unless asked.

    pyqtgraph is imported lazily so this module stays importable without a
    QApplication — the theme is imported by background workers and by the test
    harness before any GUI exists.
    """
    import pyqtgraph as pg

    return pg.mkPen(color, width=width)


def _set_frame_pen(view_box, pen) -> None:
    """
    Draw a 1px frame around a ViewBox across pyqtgraph versions.

    pyqtgraph has no setBorderColor; the frame is set with setBorder, and
    mkPen(None) yields a NoPen — which is why our plot frames were rendering
    open by accident. Prefer the documented setter when it exists and fall back
    gracefully, so a future rename cannot take a tab down.
    """
    for name in ("setBorderColor", "setBorder"):
        setter = getattr(view_box, name, None)
        if callable(setter):
            try:
                setter(pen)
                return
            except TypeError:
                continue


def style_plot(
    plot,
    title: str = "",
    y_label: str = "",
    x_label: str = "",
    *,
    mouse_x: bool = True,
    mouse_y: bool = False,
    grid: bool = True,
):
    """
    Apply the standard industrial chart treatment to a PlotItem/PlotWidget.

    This is the single entry point for plot styling: charts_tab and
    evidence_tab both delegate here so axis pens, grid alpha and tick fonts
    cannot drift apart between panels.

    ``mouse_x`` defaults to the charts_tab behaviour (x pan only); evidence_tab
    locks both off with ``mouse_x=False, mouse_y=False`` because its plots are
    read-only evidence snapshots and must not be scrolled off their range.
    """
    # A PlotWidget forwards unknown attributes to its PlotItem, but not the
    # other way round, so resolve the item once and drive it from there. Both
    # shapes are supported because charts_tab hands over a PlotWidget and
    # evidence_tab embeds a bare PlotItem.
    item = plot.getPlotItem() if hasattr(plot, "getPlotItem") else plot
    view_box = item.getViewBox()

    # A PlotWidget paints the widget-level background while a bare PlotItem
    # leaves it to the ViewBox; set whichever this object exposes so the two
    # call sites cannot end up with different plot interiors.
    if hasattr(plot, "setBackground"):
        plot.setBackground(BG_INSET)
    for name in ("setBackgroundColor", "setBackground"):
        setter = getattr(view_box, name, None)
        if callable(setter):
            try:
                setter(BG_INSET)
                break
            except TypeError:
                continue

    item.showGrid(x=grid, y=grid, alpha=GRID_ALPHA)
    item.setMouseEnabled(x=mouse_x, y=mouse_y)
    item.setMenuEnabled(False)
    item.hideButtons()

    # Numeric ticks inherit the UI face unless pinned, and a proportional face
    # makes the axis re-flow as values change width.
    tick_font = numeric_font(TICK_PT)
    label_font = numeric_font(LABEL_PT)
    for name in ("left", "bottom"):
        axis = item.getAxis(name)
        axis.setPen(trace_pen(BORDER_HI, BORDER_W))
        axis.setTextPen(trace_pen(TEXT_DIM, BORDER_W))
        try:
            axis.setStyle(tickFont=tick_font)
        except Exception:
            continue

    _set_frame_pen(view_box, trace_pen(BORDER, BORDER_W))

    if title:
        item.setTitle(title, color=TEXT_DIM, size="9pt")
    if y_label:
        item.setLabel("left", y_label, color=TEXT_DIM)
    if x_label:
        item.setLabel("bottom", x_label, color=TEXT_DIM)

    # Axis labels are the one place a label is a number as often as a word, so
    # they get the telemetry face too. The colour is already explicit — it goes
    # through the label HTML via setLabel(color=...) — but the font does not
    # inherit from the axis, so it has to be set here.
    for name, text in (("left", y_label), ("bottom", x_label)):
        if not text:
            continue
        axis_label = item.getAxis(name).label
        if axis_label is not None:
            axis_label.setFont(label_font)


def _grid_inside_style():
    """
    Resolve ``GridInsideHorizontal | GridInsideVertical``, or None if the
    running Qt binding does not expose the enum.

    PySide6 6.11 dropped GridStyle from the unscoped ``Qt`` namespace, and it
    misbinds QTableView.setGridStyle to a PenStyle argument, so the enum is
    looked up by name everywhere it has lived and the setter is skipped when it
    cannot be resolved. Skipping is safe: showGrid(True) with the sheet's
    gridline-color already draws both interior directions.
    """
    for holder in (Qt, QAbstractItemView, QTableWidget):
        enum = getattr(holder, "GridStyle", None)
        if enum is not None:
            try:
                return enum.GridInsideHorizontal | enum.GridInsideVertical
            except AttributeError:
                continue
    return None


def style_table(table):
    """
    Apply the high-contrast 1px grid contract to a QTableWidget/QTableView.

    Alternating row shading is switched off: it halves the contrast of every
    other cell and reads as decoration on an HMI. Row banding belongs in the
    data, not in the chrome. Every call is individually guarded because Qt minor
    versions differ in which of these setters exist, and a styling helper must
    never be the reason a tab fails to build.
    """
    def _try(fn, *args):
        try:
            fn(*args)
        except Exception:
            pass

    _try(table.setShowGrid, True)
    grid_style = _grid_inside_style()
    if grid_style is not None:
        # QTableWidget has setGridStyle; a plain QTableView does not.
        _try(getattr(table, "setGridStyle", None), grid_style)
    _try(table.setAlternatingRowColors, False)
    _try(table.setWordWrap, False)
    _try(table.setFont, numeric_font(9))
    vertical = table.verticalHeader()
    _try(vertical.setVisible, False)
    _try(vertical.setDefaultSectionSize, ROW_H)
    horizontal = table.horizontalHeader()
    _try(horizontal.setHighlightSections, False)
    # Headers are the frozen reference for every column below, so give them the
    # same fixed digit advance as the cells.
    _try(horizontal.setFont, numeric_font(9, QFont.Weight.DemiBold))
