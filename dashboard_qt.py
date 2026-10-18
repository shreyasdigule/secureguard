"""
SecureGuard Governance Model - PySide6 Dashboard
Modern industrial control panel with PySide6 + pyqtgraph
"""

import os
import sys
import time
from dataclasses import asdict, dataclass
from typing import Optional, Dict, List, Any, Tuple

# Auto-login is a development convenience only. This must NOT default to "1":
# it mints a supervisor token with MFA already verified, which would silently
# bypass the auth and dual-control gates this console exists to enforce. Test
# suites set the variable before importing this module.
os.environ.setdefault("SECUREGUARD_TEST_MODE", "0")

# pyqtgraph selects its Qt binding by scanning sys.modules, and PyQt6 is
# present on this machine without being a dependency. Without this, a stray
# PyQt6 import anywhere in the process would silently rebind every QFont/
# QColor/QPen crossing and crash the chart tabs. Pin the binding explicitly.
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QGridLayout,
    QGroupBox, QDialog, QTextEdit, QSizePolicy, QStatusBar,
    QScrollArea, QSpinBox, QSlider, QCheckBox, QLineEdit,
)
from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, Slot, QSize,
    QRect, QPoint, QPropertyAnimation, QEasingCurve,
    QDateTime, QLocale, QSettings, QTranslator, QEvent
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QIcon, QPixmap, QBrush,
    QPen, QFontDatabase, QAction, QKeySequence, QCursor
)
import pyqtgraph as pg

# Core governance backend
from pipeline import SecureGuardPipeline
from keycloak_auth import validate_access_token, AuthContext, dual_control_required
from keycloak_client import create_test_token
from config import app_config
from timeout_utils import TimeoutError
from industrial_theme import (
    ACCENT, ACCENT_HI, ACCENT_DEEP,
    BG_DEEP, BG_PANEL, BG_PANEL_HI, BG_CARD, BG_INSET,
    BORDER, BORDER_HI, TEXT, TEXT_DIM, TEXT_FAINT,
    OK, WARN, ALARM, IDLE, OFFLINE, RESTRICTED,
    FONT_UI, FONT_DISPLAY,
    state_color, risk_color,
    resolve_mono_family, numeric_font, style_table, led_style,
    BORDER_W, PAD_X, PAD_Y, GAP, TAB_PAD_Y, ROW_H,
)

# Tab implementations
from charts_tab import ChartsTab
from evidence_tab import StreamTab, EvidenceDetailDialog
from view3d_tab import View3DTab
from qt_view3d import Conveyor3DView

__all__ = [
    "SecureGuardDashboard",
    "RiskGauge",
    "RiskGaugeWidget",
    "SubsystemTile",
    "IdentityCard",
    "RiskThresholds",
    "RiskConfigWidget",
    "CommandForm",
    "SafetyEnvelopePanel",
    "EvidenceLogTab",
    "SystemStatePanel",
    "main",
]


# _set_status() is called with token *names* ("OK", "TEXT_DIM") rather than
# hex strings, so they have to be resolved before they reach a stylesheet.
# Emitting `color: OK;` was silently invalid CSS: Qt discarded the declaration
# and every tile fell back to inherited text colour, so MFA/STALE states were
# not colour-coded at all.
_STATUS_COLORS = {
    "OK": OK,
    "WARN": WARN,
    "ALARM": ALARM,
    "RESTRICTED": RESTRICTED,
    "IDLE": IDLE,
    "OFFLINE": OFFLINE,
    "TEXT": TEXT,
    "TEXT_DIM": TEXT_DIM,
    "TEXT_FAINT": TEXT_FAINT,
}


def _mark_primary(button: QPushButton):
    """
    Tag a button for the theme's amber primary treatment.

    The design system styles ``QPushButton[action="primary"]`` app-wide, but Qt
    only re-reads a dynamic property selector when the widget is re-polished,
    and setting the property after construction does not trigger that itself.
    Without the re-polish these buttons silently fall back to the plain default
    box, which is how three command-path controls ended up with no defined
    border at all.
    """
    button.setProperty("action", "primary")
    button.style().unpolish(button)
    button.style().polish(button)


class RiskGauge(QFrame):
    """
    Composite risk indicator: an animated circular gauge, a severity headline
    and a large numeric readout, all recoloured from one place via ``risk_color``.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._level = "LOW"
        self._target_value = 0.0
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._animate_step)
        self._animation_timer.setInterval(50)  # 20 FPS animation
        self.setMinimumWidth(250)
        self.setMinimumHeight(240)
        self.setStyleSheet(
            "RiskGauge {"
            f" background-color: {BG_PANEL};"
            f" border: {BORDER_W}px solid {BORDER};"
            "}"
        )
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(GAP * 2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        caption = QLabel("COMPOSITE RISK INDEX")
        caption.setFont(QFont(FONT_UI, 9, QFont.Weight.DemiBold))
        caption.setStyleSheet(f"color: {TEXT_FAINT}; background: transparent; letter-spacing: 2px;")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(caption)
        
        # Circular gauge canvas
        self.gauge_canvas = _CircularGaugeCanvas(self)
        self.gauge_canvas.setMinimumSize(160, 160)
        self.gauge_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.gauge_canvas, 1)
        
        read_row = QHBoxLayout()
        read_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.level_label = QLabel("RISK LEVEL: LOW")
        self.level_label.setFont(QFont(FONT_DISPLAY, 13, QFont.Weight.Bold))
        self.level_label.setStyleSheet(f"color: {OK}; background: transparent; letter-spacing: 1px;")
        self.level_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        read_row.addWidget(self.level_label)
        read_row.addStretch()
        
        self.value_label = QLabel("0.0")
        self.value_label.setFont(numeric_font(28, QFont.Weight.Bold))
        self.value_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.value_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {TEXT}; background: transparent;"
        )
        read_row.addWidget(self.value_label)
        layout.addLayout(read_row)
        
        layout.addStretch()
    
    def _animate_step(self):
        """Animate the gauge value toward target."""
        diff = self._target_value - self._value
        if abs(diff) < 0.5:
            self._value = self._target_value
            self._animation_timer.stop()
        else:
            # Ease toward target
            self._value += diff * 0.15
        self.gauge_canvas.set_value(self._value)
        self.gauge_canvas.update()
    
    def set_value(self, value: float, level: str):
        self._target_value = max(0.0, min(100.0, float(value) * 100.0 if value <= 1.0 else float(value)))
        self._level = level
        
        if not self._animation_timer.isActive():
            self._animation_timer.start()
        
        color = risk_color(level)
        self.level_label.setText(f"RISK LEVEL: {level}")
        self.level_label.setStyleSheet(
            f"color: {color}; background: transparent; letter-spacing: 1px;"
        )
        # Value label updates on animation; set immediate for snap
        self.value_label.setText(f"{self._target_value:.1f}")
        self.value_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {color}; background: transparent;"
        )
        self.gauge_canvas.set_color(color)
    
    @property
    def value(self) -> float:
        return self._value
    
    @property
    def level(self) -> str:
        return self._level


class _CircularGaugeCanvas(QWidget):
    """Canvas for drawing the animated circular risk gauge."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._color = OK
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    
    def set_value(self, value: float):
        self._value = max(0.0, min(100.0, value))
    
    def set_color(self, color: str):
        self._color = color
    
    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QColor
        from PySide6.QtCore import QRectF
        
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            rect = self.rect()
            # Cleanly erase the entire canvas rectangle to eliminate animation ghost trails and smearing
            painter.fillRect(rect, QColor(BG_PANEL))
            
            # Center and radius
            center_x = rect.width() / 2
            center_y = rect.height() / 2
            radius = min(rect.width(), rect.height()) / 2 - 20
            if radius <= 4:
                return
            
            # Track circle (background)
            track_pen = QPen(QColor(BG_INSET), 16)
            track_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(track_pen)
            painter.drawArc(
                QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2),
                90 * 16,  # Start at top (90 degrees * 16 = 1440 = 1/4 circle in 1/16 degrees)
                -360 * 16  # Full circle
            )
            
            # Value arc
            value_pen = QPen(QColor(self._color), 16)
            value_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(value_pen)
            
            # Draw arc from top (90°) clockwise based on value (0-100%)
            # 0% = no arc, 100% = full circle
            span_angle = int(-360 * 16 * (self._value / 100.0))
            if span_angle != 0:
                painter.drawArc(
                    QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2),
                    90 * 16,
                    span_angle
                )
        finally:
            painter.end()


class RiskGaugeWidget(QWidget):
    """Wrapper for backward compatibility"""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.gauge = RiskGauge()
        layout.addWidget(self.gauge)
    
    def set_value(self, score: float, level: str):
        self.gauge.set_value(score, level)


class SubsystemTile(QFrame):
    """
    Subsystem status tile.

    Laid out as an asset tag + state headline + 2x2 measurement grid, which is
    how a plant-floor HMI presents a drive: identity on top, live state in the
    middle, numbers below. The asset tag and the state are stacked rather than
    side by side because "Conveyor_Motor_01" and "QUARANTINED" together need
    ~430px and would otherwise clip in a narrow column.
    """

    def __init__(self, subsystem_id: str, parent=None):
        super().__init__(parent)
        self.subsystem_id = subsystem_id
        self.setMinimumWidth(232)
        self.setMinimumHeight(168)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(GAP * 2)

        # Accent strip across the top; recoloured with the state.
        self.color_bar = QFrame()
        self.color_bar.setFixedHeight(4)
        self.color_bar.setStyleSheet(f"background: {state_color('QUARANTINED')};")
        layout.addWidget(self.color_bar)

        # Asset tag
        self.id_label = QLabel()
        self.id_label.setFont(numeric_font(9))
        self.id_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {TEXT_DIM}; background: transparent;"
        )
        layout.addWidget(self.id_label)

        # State headline with LED
        state_row = QHBoxLayout()
        state_row.setSpacing(8)
        self.led = QLabel()
        # 13, not 11: led_style() asks Qt for an 11px CONTENT box and then draws
        # a 1px border on all four edges of it, so the indicator that actually
        # gets painted is 13x13. Declaring 11x11 left two size systems counting
        # the same border and each believing the other had done it.
        self.led.setFixedSize(13, 13)
        state_row.addWidget(self.led)
        self.state_label = QLabel()
        self.state_label.setFont(QFont(FONT_DISPLAY, 13, QFont.Weight.Bold))
        self.state_label.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent; letter-spacing: 1px;"
        )
        state_row.addWidget(self.state_label)
        state_row.addStretch()
        layout.addLayout(state_row)

        # Divider
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {BORDER};")
        layout.addWidget(rule)

        # 2x2 measurement grid
        metrics_layout = QGridLayout()
        metrics_layout.setHorizontalSpacing(GAP * 2)
        metrics_layout.setVerticalSpacing(GAP * 2)
        self.metric_labels = {}
        metrics = [
            ("SPEED", "motor_speed_rpm", "RPM"),
            ("CURRENT", "motor_current_amps", "A"),
            ("TEMP", "temperature_c", "°C"),
            ("BOX RATE", "box_rate_per_min", "/min"),
        ]
        for i, (caption, key, unit) in enumerate(metrics):
            cap = QLabel(caption)
            cap.setFont(QFont(FONT_UI, 8, QFont.Weight.DemiBold))
            cap.setStyleSheet(f"color: {TEXT_FAINT}; background: transparent; letter-spacing: 1px;")
            value_label = QLabel("--")
            value_label.setFont(numeric_font(11, QFont.Weight.DemiBold))
            value_label.setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {TEXT}; background: transparent;"
            )
            value_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.metric_labels[key] = (value_label, unit)
            metrics_layout.addWidget(cap, i // 2, (i % 2) * 2)
            metrics_layout.addWidget(value_label, i // 2, (i % 2) * 2 + 1)
        metrics_layout.setColumnStretch(0, 1)
        metrics_layout.setColumnStretch(2, 1)
        layout.addLayout(metrics_layout)
        layout.addStretch()

        self._restyle(state_color("QUARANTINED"))

    def _restyle(self, color: str):
        """Repaint the bezel and recolour the state text."""
        # Flat fill, sharp corners. The 3px left accent strip is the one piece of
        # decoration the tile keeps: it is the fastest way for an operator to
        # scan a row of drives and find the one that changed state.
        self.setStyleSheet(
            "SubsystemTile {"
            f" background-color: {BG_PANEL};"
            f" border: {BORDER_W}px solid {BORDER};"
            f" border-left: 3px solid {color};"
            "}"
            "SubsystemTile:hover {"
            f" background-color: {BG_PANEL_HI};"
            f" border: {BORDER_W}px solid {BORDER_HI};"
            f" border-left: 3px solid {color};"
            "}"
        )
        self.color_bar.setStyleSheet(f"background-color: {color};")
        # led_style() keeps the indicator a sharp square; a rounded 11x11 LED is
        # the consumer idiom this design system deliberately rejects.
        self.led.setStyleSheet(led_style(color, size=11))
        self.state_label.setStyleSheet(
            f"color: {color}; background: transparent; letter-spacing: 1px;"
        )

    def update_data(self, subsystem_id: str, state: str, metrics: Dict, consecutive: int):
        self.subsystem_id = subsystem_id
        self.id_label.setText(subsystem_id)
        self.state_label.setText(state.replace("_", " ") if state else "UNKNOWN")

        color = state_color(state)
        self._restyle(color)

        for key, (label, unit) in self.metric_labels.items():
            value = metrics.get(key)
            if value is None:
                continue
            if isinstance(value, float):
                label.setText(f"{value:.1f} {unit}")
            else:
                label.setText(f"{value} {unit}")


class IdentityCard(QFrame):
    """User identity card with security context"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # Box only. The native Raised shadow drew a bevel that the stylesheet
        # immediately painted over, so the card showed a doubled edge with a
        # highlight line that never corresponded to any real state.
        self.setFrameStyle(QFrame.Shape.Box)
        self.setStyleSheet(
            "QFrame {"
            f" background-color: {BG_PANEL};"
            f" border: {BORDER_W}px solid {BORDER};"
            "}"
        )
        self._auth = None
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(GAP * 2)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("IDENTITY & ACCESS")
        title.setStyleSheet(
            f"font-family: '{FONT_UI}'; font-size: 12px; font-weight: 700;"
            f" letter-spacing: 2px; color: {TEXT_DIM}; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        # User info
        self.user_info = QLabel("No session")
        self.user_info.setStyleSheet(
            f"font-family: '{FONT_UI}'; font-size: 24px; font-weight: 700;"
            f" color: {TEXT}; background: transparent;"
        )
        layout.addWidget(self.user_info)
        
        # Roles
        roles_layout = QHBoxLayout()
        self.roles_label = QLabel("Roles: —")
        self.roles_label.setStyleSheet(f"color: {ACCENT}; font-weight: 600; background: transparent;")
        # No static "Roles:" caption beside this label: roles_label already
        # prefixes the string it is given ("Roles: operator, supervisor"), so
        # the caption rendered the panel as "Roles: Roles: operator,
        # supervisor" and pushed the role list 50px to the right.
        roles_layout.addWidget(self.roles_label)
        roles_layout.addStretch()
        layout.addLayout(roles_layout)
        
        # Security status row
        status_layout = QHBoxLayout()
        # GAP, not Qt's default: the six status tiles were 8px apart while every
        # other row of this panel spaced on the 4px token.
        status_layout.setSpacing(GAP)
        
        # MFA Status
        self.mfa_frame = self._create_status_item("MFA", "—", WARN)
        status_layout.addWidget(self.mfa_frame)
        
        # Supervisor
        self.sup_frame = self._create_status_item("SUPERVISOR", "—", TEXT_DIM)
        status_layout.addWidget(self.sup_frame)
        
        # Device
        self.device_frame = self._create_status_item("DEVICE", "—", TEXT_DIM)
        status_layout.addWidget(self.device_frame)
        
        # Token JTI
        self.jti_frame = self._create_status_item("TOKEN JTI", "—", TEXT_DIM)
        status_layout.addWidget(self.jti_frame)
        
        # Dual Control
        self.dc_frame = self._create_status_item("DUAL CTRL", "—", TEXT_DIM)
        status_layout.addWidget(self.dc_frame)
        
        # Token Fresh
        self.fresh_frame = self._create_status_item("TOKEN FRESH", "—", TEXT_DIM)
        status_layout.addWidget(self.fresh_frame)
        
        layout.addLayout(status_layout)
        
        # Session expiry
        expiry_layout = QHBoxLayout()
        expiry_label = QLabel("SESSION EXPIRES:")
        expiry_label.setStyleSheet(
            f"font-family: '{FONT_UI}'; color: {TEXT_DIM};"
            f" font-size: 10px; background: transparent;"
        )
        self.expiry_label = QLabel("--:--")
        # The countdown is the only timestamp in the window chrome, so it is
        # pinned to the resolved monospace family. Without an explicit family it
        # rendered in the proportional UI face until the first live tick, which
        # is exactly when an operator is reading it to decide whether to re-auth.
        self.expiry_label.setFont(numeric_font(18, QFont.Weight.Bold))
        self.expiry_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {OK}; background: transparent;"
        )
        expiry_layout.addWidget(expiry_label)
        expiry_layout.addWidget(self.expiry_label)
        expiry_layout.addStretch()
        layout.addLayout(expiry_layout)
        
        # A floor, not a fixed height. setFixedHeight(220) was sized for the
        # pre-density layout and reserved ~67px of dead space under content whose
        # sizeHint is 153. A minimum derived from the content plus one GAP cannot
        # clip the panel, and lets the identity strip grow if a long role list or
        # a longer session word ever needs it to.
        self.setMinimumHeight(self.sizeHint().height() + GAP)
    
    def _create_status_item(self, label: str, value: str, color: str) -> QFrame:
        """
        Build one status tile.

        The value label is attached to the frame as ``_value_label`` because
        ``_set_status`` used to find it by matching ``font().pointSize() == 12``,
        which silently failed (stylesheet px sizes do not change the widget
        font), leaving every tile stuck on its placeholder.
        """
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame {"
            f" background-color: {BG_PANEL_HI};"
            f" border: {BORDER_W}px solid {BORDER};"
            "}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)

        label_widget = QLabel(label)
        label_widget.setFont(QFont(FONT_UI, 8, QFont.Weight.DemiBold))
        label_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label_widget.setStyleSheet(
            f"color: {TEXT_FAINT}; background: transparent; letter-spacing: 1px;"
        )
        layout.addWidget(label_widget)

        value_label = QLabel(value)
        value_label.setFont(numeric_font(9, QFont.Weight.DemiBold))
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {color}; background: transparent;"
        )
        layout.addWidget(value_label)

        frame._value_label = value_label
        return frame
    
    def update_auth(self, auth: Optional[AuthContext]):
        self._auth = auth
        if auth is None:
            self.user_info.setText("No session")
            self.roles_label.setText("Roles: —")
            self._set_status(self.mfa_frame, "—", "WARN")
            self._set_status(self.sup_frame, "—", "TEXT_DIM")
            self._set_status(self.device_frame, "—", "TEXT_DIM")
            self._set_status(self.jti_frame, "—", "TEXT_DIM")
            self._set_status(self.dc_frame, "—", "TEXT_DIM")
            self._set_status(self.fresh_frame, "—", "TEXT_DIM")
            self.expiry_label.setText("--:--")
            return
        
        self.user_info.setText(auth.username)
        self.roles_label.setText(f"Roles: {', '.join(sorted(auth.roles))}")
        
        # MFA
        if auth.mfa_verified:
            self._set_status(self.mfa_frame, "OTP VERIFIED", "OK")
        else:
            self._set_status(self.mfa_frame, "STANDARD", "WARN")
        
        # Supervisor
        if auth.supervisor_approved:
            self._set_status(self.sup_frame, "AUTHORIZED", "OK")
        else:
            self._set_status(self.sup_frame, "STANDARD", "TEXT_DIM")
        
        # Device
        fp = auth.device_fingerprint
        self._set_status(self.device_frame, fp[:8] + "..." if fp != "unknown" else "—", "TEXT")
        
        # Token JTI
        jti = auth.token_jti
        self._set_status(self.jti_frame, jti[:8] + "..." if jti else "—", "TEXT")
        
        # Dual Control
        if auth.dual_control_satisfied():
            self._set_status(self.dc_frame, "SATISFIED", "OK")
        else:
            self._set_status(self.dc_frame, "PENDING", "WARN")
        
        # Token Fresh
        if auth.token_fresh():
            self._set_status(self.fresh_frame, "FRESH", "OK")
        else:
            self._set_status(self.fresh_frame, "STALE", "ALARM")
        
        # Expiry is rendered by tick_session() so it counts down live.
        self.tick_session()
    
    def _set_status(self, frame: QFrame, value: str, color: str):
        """Update a status tile's value text and colour."""
        label = getattr(frame, "_value_label", None)
        if label is None:  # pragma: no cover - defensive
            return
        label.setText(value)
        # Callers pass token names ("OK", "TEXT_DIM"); resolve them so the
        # stylesheet receives a real colour instead of being silently dropped.
        label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {_STATUS_COLORS.get(color, color)}; background: transparent;"
        )

    def tick_session(self):
        """
        Recompute the live session countdown.

        The countdown used to be computed once inside ``update_auth`` and never
        refreshed, so it sat frozen at its login value for the life of the
        window. Driven from the 1s clock timer instead.
        """
        auth = self._auth
        if auth is None:
            self.expiry_label.setText("--:--")
            # Drop back to the faint placeholder colour: leaving the last live
            # green in place after sign-out reads as a healthy session.
            self.expiry_label.setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {TEXT_FAINT}; background: transparent;"
            )
            return

        remaining = auth.seconds_until_expiry()
        if auth.token_expires_at is None and auth.token_issued_at is None:
            self.expiry_label.setText("--:--")
            self.expiry_label.setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {TEXT_FAINT}; background: transparent;"
            )
            return

        mins = int(remaining // 60)
        secs = int(remaining % 60)
        self.expiry_label.setText(f"{mins:02d}:{secs:02d}")

        if remaining <= 0:
            colour, text = ALARM, "EXPIRED"
        elif remaining < 60:
            colour = ALARM
        elif remaining < 300:
            colour = WARN
        else:
            colour = OK
        self.expiry_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {colour}; background: transparent;"
        )
        self.expiry_label.setToolTip(
            f"Session remaining: {mins}m {secs}s" if remaining > 0 else text
        )

        # Token freshness decays over time too, so refresh it on every tick.
        self._set_status(
            self.fresh_frame, "FRESH" if auth.token_fresh() else "STALE",
            OK if auth.token_fresh() else ALARM,
        )


# State colours come from industrial_theme.state_color so the dashboard chrome,
# the subsystem tiles and the charts cannot disagree about what "running" and
# "tripped" mean. A local copy of this map previously drifted: it had RESTRICTED
# while the theme did not, and the theme had states this map lacked. The
# zero-call-site `_state_color` wrapper that stood in for the theme import is
# gone with that drift; nothing outside this module ever called it.


DEFAULT_SUBSYSTEMS = ["Conveyor_Motor_01", "Conveyor_Motor_02", "Conveyor_Motor_03"]


# ===========================================================================
# Risk threshold configuration
# ===========================================================================

@dataclass
class RiskThresholds:
    """Operator-adjustable alert thresholds for conveyor telemetry."""
    over_temperature_c: float = 85.0
    over_current_a: float = 15.0
    over_speed_rpm: float = 1000.0
    box_rate_low: float = 10.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "over_temperature_c": self.over_temperature_c,
            "over_current_a": self.over_current_a,
            "over_speed_rpm": self.over_speed_rpm,
            "box_rate_low": self.box_rate_low,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "RiskThresholds":
        base = cls()
        for key in base.to_dict():
            if key in data:
                try:
                    setattr(base, key, float(data[key]))
                except (TypeError, ValueError):
                    pass
        return base

    def severity(self, metrics: Dict[str, float]) -> Tuple[str, str]:
        """
        Classify a telemetry sample against the thresholds.

        Returns ``(state, driver)`` where state is one of
        NORMAL / DEGRADED / RESTRICTED / QUARANTINED.
        """
        temp = metrics.get("temperature_c")
        current = metrics.get("motor_current_amps")
        speed = metrics.get("motor_speed_rpm")
        boxes = metrics.get("box_rate_per_min")

        breaches: List[Tuple[float, str]] = []
        if temp is not None:
            ratio = temp / self.over_temperature_c if self.over_temperature_c else 0.0
            breaches.append((ratio, "temperature"))
        if current is not None:
            ratio = current / self.over_current_a if self.over_current_a else 0.0
            breaches.append((ratio, "motor current"))
        if speed is not None:
            ratio = speed / self.over_speed_rpm if self.over_speed_rpm else 0.0
            breaches.append((ratio, "motor speed"))
        if boxes is not None and self.box_rate_low:
            # Inverted: throughput *below* the floor is the concern.
            breaches.append((self.box_rate_low / max(boxes, 1e-6), "box rate shortfall"))

        if not breaches:
            return "NORMAL", ""

        worst_ratio, driver = max(breaches, key=lambda item: item[0])
        if worst_ratio >= 1.0:
            return "QUARANTINED", driver
        if worst_ratio >= 0.85:
            return "RESTRICTED", driver
        if worst_ratio >= 0.65:
            return "DEGRADED", driver
        return "NORMAL", ""


class RiskConfigWidget(QGroupBox):
    """Editable threshold panel feeding the dashboard's colour logic."""

    thresholds_changed = Signal(dict)

    _FIELDS = (
        ("over_temperature_c", "Over Temperature", "deg C", 0.0, 300.0, 1.0),
        ("over_current_a", "Over Current", "A", 0.0, 200.0, 0.5),
        ("over_speed_rpm", "Over Speed", "RPM", 0.0, 3000.0, 10.0),
        ("box_rate_low", "Box Rate Floor", "/min", 0.0, 500.0, 1.0),
    )

    def __init__(self, thresholds: RiskThresholds, parent=None):
        super().__init__("RISK THRESHOLDS", parent)
        self._thresholds = thresholds
        self._build()

    def _build(self):
        grid = QGridLayout(self)
        # Token margins, not Qt's 9px default. A QGroupBox already reserves 8px
        # of QSS margin-top for its own title, so the grid's default stacked on
        # top of it and put the first caption row 24px below the border while a
        # plain QFrame panel sat at 7px. Same inset everywhere is the whole point.
        grid.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        grid.setSpacing(GAP * 2)
        self._spins: Dict[str, QDoubleSpinBox] = {}

        for row, (key, label, unit, lo, hi, step) in enumerate(self._FIELDS):
            caption = QLabel(f"{label}:")
            caption.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setDecimals(1)
            spin.setSingleStep(step)
            spin.setValue(getattr(self._thresholds, key))
            spin.setSuffix(f" {unit}")
            spin.setToolTip(f"{label} threshold — alerts when exceeded")
            spin.valueChanged.connect(self._on_changed)
            self._spins[key] = spin
            grid.addWidget(caption, row, 0)
            grid.addWidget(spin, row, 1)

        self.reset_btn = QPushButton("Reset Defaults")
        self.reset_btn.clicked.connect(self.reset_defaults)
        grid.addWidget(self.reset_btn, len(self._FIELDS), 0, 1, 2)
        # Slack below the button, never between the rows: a QGridLayout with no
        # row stretch spreads surplus height across the rows instead, which is
        # what separated this panel's first row from its neighbours'.
        grid.setRowStretch(len(self._FIELDS) + 1, 1)

    def _on_changed(self, *_args):
        for key, spin in self._spins.items():
            setattr(self._thresholds, key, spin.value())
        self.thresholds_changed.emit(self._thresholds.to_dict())

    def reset_defaults(self):
        defaults = RiskThresholds()
        for key, spin in self._spins.items():
            spin.setValue(getattr(defaults, key))
        self._on_changed()


# ===========================================================================
# Overview tab widgets
# ===========================================================================

class CommandForm(QGroupBox):
    """Operator command entry wired to the governance pipeline."""

    command_submitted = Signal(str, float, float)

    def __init__(self, subsystems: List[str], parent=None):
        super().__init__("COMMAND — SET SPEED", parent)
        self._subsystems = subsystems
        self._build()

    def _build(self):
        grid = QGridLayout(self)
        # Token margins: see RiskConfigWidget._build. QGroupBox's QSS
        # margin-top already carries the title gutter, so a Qt-default 9px grid
        # margin was a second inset nobody had asked for.
        grid.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        grid.setSpacing(GAP * 2)

        self.subsystem_combo = QComboBox()
        self.subsystem_combo.addItems(self._subsystems)
        self.subsystem_combo.currentTextChanged.connect(self._on_subsystem_changed)

        self.current_speed = QLabel("0 RPM")
        # Numeric telemetry: monospace via the resolved family so the RPM digits
        # share one advance as the value changes while a command is in flight.
        self.current_speed.setFont(numeric_font(11))
        self.current_speed.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {TEXT}; background: transparent;"
        )

        self.to_speed = QDoubleSpinBox()
        self.to_speed.setRange(0, 2000)
        self.to_speed.setValue(500)
        self.to_speed.setDecimals(0)
        self.to_speed.setSingleStep(50)
        self.to_speed.setSuffix(" RPM")

        self.submit_btn = QPushButton("SUBMIT COMMAND")
        _mark_primary(self.submit_btn)
        self.submit_btn.clicked.connect(self._on_submit)

        grid.addWidget(QLabel("Subsystem:"), 0, 0)
        grid.addWidget(self.subsystem_combo, 0, 1)
        grid.addWidget(QLabel("Current:"), 0, 2)
        grid.addWidget(self.current_speed, 0, 3)
        grid.addWidget(QLabel("Target:"), 1, 0)
        grid.addWidget(self.to_speed, 1, 1)
        grid.addWidget(self.submit_btn, 1, 2, 1, 2)
        # Slack below the form, on an EMPTY row - the same trick the other two
        # group grids use. Stretching row 1 instead, which holds the spin box
        # and the button, does not work: those two are Fixed-policy, so the row
        # cannot grow to absorb the surplus and QGridLayout spills it around
        # the rows instead. Measured at 1600x900 that put 54px above row 0, 43
        # px of phantom gap between the rows and 36px below row 1 - the panel
        # was more misaligned than before the fix, not less. An empty row
        # absorbs all of it: row 0 then sits at the 11px inset that
        # SafetyEnvelopePanel and RiskConfigWidget sit at.
        grid.setRowStretch(2, 1)

        self._speeds: Dict[str, float] = {s: 0.0 for s in self._subsystems}
        self._on_subsystem_changed(self.subsystem_combo.currentText())

    def _on_subsystem_changed(self, subsystem: str):
        self.current_speed.setText(f"{self._speeds.get(subsystem, 0.0):.0f} RPM")
        self.to_speed.setValue(self._speeds.get(subsystem, 0.0) or 500)

    def record_result(self, subsystem: str, speed_rpm: float):
        self._speeds[subsystem] = speed_rpm
        if subsystem == self.subsystem_combo.currentText():
            self.current_speed.setText(f"{speed_rpm:.0f} RPM")

    def _on_submit(self):
        self.command_submitted.emit(
            self.subsystem_combo.currentText(),
            self._speeds.get(self.subsystem_combo.currentText(), 0.0),
            self.to_speed.value(),
        )


class SafetyEnvelopePanel(QGroupBox):
    """Read-only view of the physics twin's hard safety limits."""

    def __init__(self, spec, parent=None):
        super().__init__("SAFETY ENVELOPE", parent)
        self._build(spec)

    def _build(self, spec):
        grid = QGridLayout(self)
        grid.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        grid.setSpacing(GAP)
        rows = [
            ("Motor power", f"{getattr(spec, 'motor_power', 0):.1f} kW"),
            ("Rated speed", f"{getattr(spec, 'motor_rated_speed', 0):.0f} RPM"),
            ("Max safe speed", f"{getattr(spec, 'max_safe_rpm', 0):.0f} RPM"),
            ("Max safe current", f"{getattr(spec, 'max_safe_current_amps', 0):.1f} A"),
            ("Max safe temp", f"{getattr(spec, 'max_safe_temperature_c', 0):.0f} deg C"),
            ("Belt length", f"{getattr(spec, 'length', 0):.0f} m"),
        ]
        for row, (label, value) in enumerate(rows):
            caption = QLabel(label)
            caption.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
            readout = QLabel(value)
            # Hard limits are measured values, so they get the telemetry face;
            # reading "1800 RPM" against a proportional face invites digit slips.
            readout.setFont(numeric_font(10))
            readout.setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {TEXT}; background: transparent;"
            )
            grid.addWidget(caption, row, 0)
            grid.addWidget(readout, row, 1)
        # Slack below the last limit, matching the tile and the gauge: see
        # RiskConfigWidget._build.
        grid.setRowStretch(len(rows), 1)


# ===========================================================================
# Evidence tab
# ===========================================================================

class EvidenceLogTab(QWidget):
    """Forensic ledger browser with detail drill-down."""

    # Column indices are named because the cell-styling loop below keys off
    # them; positional literals there are how the timestamp and risk columns
    # ended up unstyled while everyone assumed they were covered.
    COLUMN_TIMESTAMP = 0
    COLUMN_SUBSYSTEM = 1
    COLUMN_COMMAND = 2
    COLUMN_DECISION = 3
    COLUMN_RISK = 4
    COLUMN_USER = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: List[Dict] = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(GAP * 2)

        header = QHBoxLayout()
        title = QLabel("FORENSIC EVIDENCE LOG")
        title.setStyleSheet(
            f"font-family: '{FONT_DISPLAY}'; font-size: 15px; font-weight: 700;"
            f" letter-spacing: 3px; color: {TEXT}; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch()

        self.verify_btn = QPushButton("VERIFY CHAIN")
        self.verify_btn.setToolTip("Recompute the hash chain and Ed25519 signatures")
        self.verify_btn.clicked.connect(self._on_verify)
        header.addWidget(self.verify_btn)

        self.refresh_btn = QPushButton("RELOAD")
        self.refresh_btn.clicked.connect(self.reload)
        header.addWidget(self.refresh_btn)

        self.export_btn = QPushButton("EXPORT JSONL")
        self.export_btn.clicked.connect(self.export_records)
        header.addWidget(self.export_btn)

        layout.addLayout(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Timestamp", "Subsystem", "Command", "Decision", "Risk", "User"]
        )
        # style_table() owns the grid/row-height/vertical-header contract. It
        # cannot be spelled out here: PySide6 6.11 dropped Qt.GridStyle and
        # mis-binds QTableView.setGridStyle, so the enum has to be resolved by
        # the theme helper that knows where it moved to.
        style_table(self.table)
        # style_table() sets the table font, but the app sheet's generic
        # `QWidget { font-family }` rule outranks it. Re-declare the family in a
        # widget-level sheet so every cell without an explicit item font still
        # lands on a fixed digit advance.
        self.table.setStyleSheet(
            f"QTableWidget {{ font-family: '{resolve_mono_family()}'; }}"
        )
        self._configure_columns()
        self.table.doubleClicked.connect(self._on_row_activated)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("")
        # Counts and indices are telemetry, so the whole status line is pinned
        # to the resolved monospace family rather than the proportional UI face.
        self.status_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {TEXT_DIM}; background: transparent;"
        )
        layout.addWidget(self.status_label)

    def _configure_columns(self):
        """
        Size the ledger columns explicitly.

        Every column used to inherit Qt's default interactive resize, so a
        double-click on a header silently re-flowed the whole forensic table
        and an operator could lose the timestamp column off the left edge. The
        two free-text columns stretch; the identifiers and the Risk score get a
        deterministic width so the numeric column stays a straight edge.
        """
        header_view = self.table.horizontalHeader()
        header_view.setHighlightSections(False)
        header_view.setSectionsClickable(False)
        header_view.setDefaultSectionSize(ROW_H)
        header_view.setMinimumSectionSize(40)
        modes = {
            self.COLUMN_TIMESTAMP: QHeaderView.ResizeMode.ResizeToContents,
            self.COLUMN_SUBSYSTEM: QHeaderView.ResizeMode.ResizeToContents,
            self.COLUMN_COMMAND: QHeaderView.ResizeMode.Stretch,
            self.COLUMN_DECISION: QHeaderView.ResizeMode.ResizeToContents,
            self.COLUMN_RISK: QHeaderView.ResizeMode.Fixed,
            self.COLUMN_USER: QHeaderView.ResizeMode.Stretch,
        }
        for column, mode in modes.items():
            header_view.setSectionResizeMode(column, mode)
        self.table.setColumnWidth(self.COLUMN_RISK, 60)

    def reload(self):
        try:
            from evidence_log import read_all_evidence
            self._records = list(read_all_evidence() or [])
        except Exception as exc:  # pragma: no cover - defensive
            self._records = []
            self.status_label.setText(f"Unable to read evidence ledger: {exc}")
            return

        # read_all_evidence() already returns newest-first. Reversing here put
        # the oldest record on row 0 and pushed recent decisions off-screen,
        # which is the opposite of what an operator watches this tab for.
        self.table.setRowCount(len(self._records))
        # Every cell gets the ledger's monospace face explicitly. QStyledItemDelegate
        # falls back to QApplication::font("QTableView") for items with no
        # FontRole, not to the view's font, so setting the table font alone left
        # every column proportional - and the Command column ("SET_SPEED = 480
        # RPM") is read as a number.
        mono = numeric_font(9)
        for row, record in enumerate(self._records):
            decision = record.get("final_decision", "")
            risk = record.get("risk_score", 0.0)
            try:
                risk_text = f"{float(risk):.1f}"
            except (TypeError, ValueError):
                risk_text = str(risk)

            cells = [
                str(record.get("timestamp", ""))[:19],
                str(record.get("subsystem", "")),
                str(record.get("command", "")),
                str(decision),
                risk_text,
                str(record.get("user", "")),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFont(mono)
                if col == self.COLUMN_DECISION:
                    # Decision -> colour is kept explicit rather than routed
                    # through state_color(): the theme maps REJECTED_SAFETY and
                    # REJECTED_AUTH to neutral TEXT_DIM, which would strip the
                    # alarm signal an auditor scans this column for. Only the
                    # literal values changed, never the state mapping.
                    colour = {
                        "ACCEPTED": OK,
                        "REJECTED_SAFETY": ALARM,
                        "REJECTED_AUTH": RESTRICTED,
                        "BLOCKED_QUARANTINE": ALARM,
                    }.get(decision)
                    if colour:
                        item.setForeground(QColor(colour))
                elif col == self.COLUMN_RISK:
                    level = record.get("risk_level")
                    if level:
                        # Severity tint from the theme's own risk map, so the
                        # ledger and the gauge cannot disagree about a score.
                        item.setForeground(QColor(risk_color(level)))
                self.table.setItem(row, col, item)

        self.status_label.setText(f"{len(self._records)} record(s) loaded")

    def _on_row_activated(self, index):
        if 0 <= index.row() < len(self._records):
            from evidence_tab import EvidenceDetailDialog
            dialog = EvidenceDetailDialog(self, self._records[index.row()])
            dialog.exec()

    def _on_verify(self):
        try:
            import evidence_log
            from verify_log import verify_chain
            result = verify_chain(log_path=evidence_log.LOG_PATH, verbose=False)
        except Exception as exc:  # pragma: no cover - defensive
            self.status_label.setText(f"Verification error: {exc}")
            return

        if getattr(result, "tampered", False):
            self.status_label.setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; font-weight: 600;"
                f" color: {ALARM}; background: transparent;"
            )
            self.status_label.setText(
                f"TAMPER DETECTED at index {getattr(result, 'first_tampered_index', '?')}"
            )
        else:
            self.status_label.setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; font-weight: 600;"
                f" color: {OK}; background: transparent;"
            )
            self.status_label.setText(
                f"Chain intact - {getattr(result, 'total_records', 0)} records verified"
            )

    def export_records(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Evidence", "evidence_export.jsonl", "JSON Lines (*.jsonl)"
        )
        if not path:
            return
        import json
        try:
            with open(path, "w", encoding="utf-8") as handle:
                for record in self._records:
                    handle.write(json.dumps(record, default=str) + "\n")
        except OSError as exc:
            self.status_label.setText(f"Export failed: {exc}")
            return
        self.status_label.setText(f"Exported {len(self._records)} record(s) to {path}")


# ===========================================================================
# Push Commands tab - Full PLC command set for industrial demo
# ===========================================================================

from enum import Enum

class PLCCommandType(Enum):
    """Supported PLC command types for heavy-duty industrial demonstration."""
    SET_SPEED = "SET_SPEED"
    START = "START"
    STOP = "STOP"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    REVERSE = "REVERSE"
    JOG = "JOG"
    RAMP_UP = "RAMP_UP"
    RAMP_DOWN = "RAMP_DOWN"
    TORQUE_LIMIT = "TORQUE_LIMIT"
    RESET_RECOVERY = "RESET_RECOVERY"
    HOLD = "HOLD"
    SPEED_RAMP = "SPEED_RAMP"
    CHANGE_DIRECTION = "CHANGE_DIRECTION"
    SET_CTRL_MODE = "SET_CTRL_MODE"


class PushCommandsTab(QWidget):
    """
    Push Commands tab for heavy-duty industrial PLC demonstration.
    
    Provides a diverse set of commands suitable for conveyor control systems.
    Each command goes through the full governance pipeline: auth gating,
    safety envelope check, risk assessment, and evidence recording.
    """
    
    command_submitted = Signal(str, dict)  # subsystem_id, command_dict
    
    def __init__(self, pipeline, subsystems: List[str], parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.subsystems = subsystems
        self._current_speeds = {s: 0.0 for s in subsystems}
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(GAP * 2)
        
        # Title
        title = QLabel("PUSH COMMANDS — Industrial PLC Control")
        title.setStyleSheet(
            f"font-family: '{FONT_DISPLAY}'; font-size: 15px; font-weight: 700;"
            f" letter-spacing: 3px; color: {TEXT}; background: transparent;"
        )
        layout.addWidget(title)
        
        # Subsystem selector
        select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("Subsystem:"))
        self.subsystem_combo = QComboBox()
        self.subsystem_combo.addItems(self.subsystems)
        self.subsystem_combo.currentTextChanged.connect(self._on_subsystem_changed)
        select_layout.addWidget(self.subsystem_combo)
        
        # Live speed readout
        select_layout.addWidget(QLabel("Current Speed:"))
        self.current_speed_label = QLabel("0 RPM")
        self.current_speed_label.setFont(numeric_font(14, QFont.Weight.DemiBold))
        self.current_speed_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}'; color: {TEXT}; background: transparent;"
        )
        select_layout.addWidget(self.current_speed_label)
        select_layout.addStretch()
        layout.addLayout(select_layout)
        
        # Command grid
        cmd_grid = QGridLayout()
        cmd_grid.setHorizontalSpacing(GAP * 3)
        cmd_grid.setVerticalSpacing(GAP)
        
        # Define command buttons with their parameters
        commands = [
            # Row 0: Basic motion
            ("START", PLCCommandType.START, "Start conveyor at target speed", {}),
            ("STOP", PLCCommandType.STOP, "Stop conveyor (controlled decel)", {}),
            ("EMERGENCY STOP", PLCCommandType.EMERGENCY_STOP, "Immediate emergency stop", {"style": "danger"}),
            
            # Row 1: Speed control
            ("SET SPEED", PLCCommandType.SET_SPEED, "Set target speed with ramp", {"has_param": "speed"}),
            ("JOG", PLCCommandType.JOG, "Momentary jog at jog speed", {"has_param": "speed"}),
            ("HOLD", PLCCommandType.HOLD, "Hold current speed", {}),
            
            # Row 2: Ramp control
            ("RAMP UP", PLCCommandType.RAMP_UP, "Increase speed with ramp rate", {"has_param": "rate"}),
            ("RAMP DOWN", PLCCommandType.RAMP_DOWN, "Decrease speed with ramp rate", {"has_param": "rate"}),
            ("SPEED RAMP", PLCCommandType.SPEED_RAMP, "Ramp to target speed", {"has_param": "speed", "has_param2": "rate"}),
            
            # Row 3: Direction & mode
            ("REVERSE", PLCCommandType.REVERSE, "Reverse direction at current speed", {}),
            ("CHANGE DIR", PLCCommandType.CHANGE_DIRECTION, "Set direction FWD/REV", {"has_param": "direction"}),
            ("CTRL MODE", PLCCommandType.SET_CTRL_MODE, "Velocity/Torque control mode", {"has_param": "mode"}),
            
            # Row 4: Limits & recovery
            ("TORQUE LIMIT", PLCCommandType.TORQUE_LIMIT, "Set torque limit %", {"has_param": "torque"}),
            ("RESET/RECOVERY", PLCCommandType.RESET_RECOVERY, "Reset from QUARANTINED/RESTRICTED", {}),
        ]
        
        # Create parameter input widgets
        self.param_widgets = {}
        
        for idx, (label, cmd_type, tooltip, opts) in enumerate(commands):
            row = idx // 3
            col = idx % 3
            
            btn = QPushButton(label)
            btn.setMinimumHeight(36)
            btn.setFont(QFont(FONT_UI, 10, QFont.Weight.DemiBold))
            btn.setToolTip(tooltip)
            
            if opts.get("style") == "danger":
                btn.setProperty("action", "danger")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            else:
                btn.setProperty("action", "primary")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            
            # Store command type for the callback
            btn.clicked.connect(lambda checked, ct=cmd_type, o=opts: self._on_command_button(ct, o))
            cmd_grid.addWidget(btn, row, col)
        
        layout.addLayout(cmd_grid)
        
        # Parameter input panel (initially hidden, shown when needed)
        self.param_panel = QFrame()
        self.param_panel.setStyleSheet(
            f"QFrame {{ background-color: {BG_PANEL_HI}; border: {BORDER_W}px solid {BORDER}; }}"
        )
        param_layout = QGridLayout(self.param_panel)
        param_layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        param_layout.setSpacing(GAP)
        
        # Speed parameter
        self.param_speed = QDoubleSpinBox()
        self.param_speed.setRange(0, 2000)
        self.param_speed.setValue(500)
        self.param_speed.setDecimals(0)
        self.param_speed.setSuffix(" RPM")
        self.param_speed.setSingleStep(50)
        
        # Rate parameter
        self.param_rate = QDoubleSpinBox()
        self.param_rate.setRange(10, 500)
        self.param_rate.setValue(100)
        self.param_rate.setDecimals(0)
        self.param_rate.setSuffix(" %/s")
        self.param_rate.setSingleStep(10)
        
        # Torque parameter
        self.param_torque = QDoubleSpinBox()
        self.param_torque.setRange(10, 150)
        self.param_torque.setValue(100)
        self.param_torque.setDecimals(0)
        self.param_torque.setSuffix(" %")
        self.param_torque.setSingleStep(10)
        
        # Direction parameter
        self.param_direction = QComboBox()
        self.param_direction.addItems(["FWD", "REV"])
        
        # Control mode parameter
        self.param_mode = QComboBox()
        self.param_mode.addItems(["VELOCITY", "TORQUE"])
        
        # Confirm button
        self.param_confirm = QPushButton("EXECUTE COMMAND")
        self.param_confirm.setProperty("action", "primary")
        self.param_confirm.style().unpolish(self.param_confirm)
        self.param_confirm.style().polish(self.param_confirm)
        self.param_confirm.setMinimumHeight(36)
        self.param_confirm.clicked.connect(self._execute_pending_command)
        
        self.param_cancel = QPushButton("CANCEL")
        self.param_cancel.setMinimumHeight(36)
        self.param_cancel.clicked.connect(self._hide_param_panel)
        
        # Layout params (will be shown/hidden dynamically)
        param_layout.addWidget(QLabel("Target Speed:"), 0, 0)
        param_layout.addWidget(self.param_speed, 0, 1)
        param_layout.addWidget(QLabel("Ramp Rate (%/s):"), 1, 0)
        param_layout.addWidget(self.param_rate, 1, 1)
        param_layout.addWidget(QLabel("Torque Limit (%):"), 2, 0)
        param_layout.addWidget(self.param_torque, 2, 1)
        param_layout.addWidget(QLabel("Direction:"), 3, 0)
        param_layout.addWidget(self.param_direction, 3, 1)
        param_layout.addWidget(QLabel("Control Mode:"), 4, 0)
        param_layout.addWidget(self.param_mode, 4, 1)
        param_layout.addWidget(self.param_confirm, 5, 0)
        param_layout.addWidget(self.param_cancel, 5, 1)
        
        self.param_panel.hide()
        layout.addWidget(self.param_panel)
        
        # System state display
        state_frame = QFrame()
        state_frame.setStyleSheet(
            f"QFrame {{ background-color: {BG_PANEL}; border: {BORDER_W}px solid {BORDER}; }}"
        )
        state_layout = QGridLayout(state_frame)
        state_layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        state_layout.setSpacing(GAP)
        
        state_layout.addWidget(QLabel("SYSTEM STATE:"), 0, 0, 1, 2)
        
        self.state_labels = {}
        state_items = [
            ("Subsystem State", "subsystem_state"),
            ("Auth Requirement", "auth_requirement"),
            ("Risk Level", "risk_level"),
            ("Risk Score", "risk_score"),
            ("MFA Verified", "mfa_verified"),
            ("Supervisor Approved", "supervisor_approved"),
            ("Dual Control", "dual_control"),
            ("Token Fresh", "token_fresh"),
            ("Session Remaining", "session_remaining"),
        ]
        
        for i, (label, key) in enumerate(state_items):
            row = 1 + i // 2
            col = (i % 2) * 2
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 9px;")
            val = QLabel("—")
            val.setFont(numeric_font(10, QFont.Weight.DemiBold))
            val.setStyleSheet(f"font-family: '{resolve_mono_family()}'; color: {TEXT};")
            state_layout.addWidget(lbl, row, col)
            state_layout.addWidget(val, row, col + 1)
            self.state_labels[key] = val
        
        layout.addWidget(state_frame)
        layout.addStretch()
        
        # Pending command state
        self._pending_command = None
        self._pending_options = None
        
        # Initialize with first subsystem
        self._on_subsystem_changed(self.subsystem_combo.currentText())
    
    def _on_subsystem_changed(self, subsystem: str):
        """Update UI when subsystem selection changes."""
        speed = self._current_speeds.get(subsystem, 0.0)
        self.current_speed_label.setText(f"{speed:.0f} RPM")
        self._update_system_state(subsystem)
        self._hide_param_panel()
    
    def update_current_speed(self, subsystem: str, speed: float):
        """Update the live speed readout."""
        self._current_speeds[subsystem] = speed
        if subsystem == self.subsystem_combo.currentText():
            self.current_speed_label.setText(f"{speed:.0f} RPM")
    
    def _update_system_state(self, subsystem: str):
        """Update the system state display."""
        try:
            auth_subsystem = self.pipeline.state_store.get(subsystem)
            
            self.state_labels["subsystem_state"].setText(auth_subsystem.state.value)
            self.state_labels["auth_requirement"].setText(auth_subsystem.required_auth())
            
            # Risk level from thresholds
            metrics = self.pipeline._get_telemetry().get(subsystem, {})
            if metrics:
                verdict, _ = self.pipeline.risk_engine.assess(
                    prediction=None,  # Will use simplified assessment
                    observation=metrics,
                    context={"belt_age_hours": getattr(auth_subsystem, 'belt_age_hours', 0.0)},
                    safety_violations=[]
                )
                self.state_labels["risk_level"].setText(getattr(verdict, 'overall_risk_level', 'LOW') if verdict else 'LOW')
                self.state_labels["risk_score"].setText(f"{getattr(verdict, 'overall_risk_score', 0.0):.1f}")
            
            if hasattr(self, '_auth') and self._auth:
                auth = self._auth
                self.state_labels["mfa_verified"].setText("YES" if auth.mfa_verified else "NO")
                self.state_labels["supervisor_approved"].setText("YES" if auth.supervisor_approved else "NO")
                self.state_labels["dual_control"].setText("SATISFIED" if auth.dual_control_satisfied() else "PENDING")
                self.state_labels["token_fresh"].setText("FRESH" if auth.token_fresh() else "STALE")
                remaining = int(auth.seconds_until_expiry())
                mins, secs = divmod(remaining, 60)
                self.state_labels["session_remaining"].setText(f"{mins:02d}:{secs:02d}")
        except Exception:
            pass  # Defensive
    
    def _on_command_button(self, cmd_type: PLCCommandType, options: dict):
        """Handle command button click - show parameter panel if needed."""
        self._pending_command = cmd_type
        self._pending_options = options
        
        # Show/hide relevant parameter inputs
        self.param_speed.setVisible(options.get("has_param") == "speed" or options.get("has_param2") == "speed")
        self.param_rate.setVisible(options.get("has_param") == "rate" or options.get("has_param2") == "rate")
        self.param_torque.setVisible(options.get("has_param") == "torque")
        self.param_direction.setVisible(options.get("has_param") == "direction")
        self.param_mode.setVisible(options.get("has_param") == "mode")
        
        # Show the panel
        self.param_panel.show()
    
    def _hide_param_panel(self):
        """Hide the parameter panel."""
        self.param_panel.hide()
        self._pending_command = None
        self._pending_options = None
    
    def _execute_pending_command(self):
        """Execute the pending command with parameters."""
        if self._pending_command is None:
            return
        
        subsystem = self.subsystem_combo.currentText()
        cmd_type = self._pending_command
        options = self._pending_options or {}
        
        # Build command dict
        command = {"cmd_type": cmd_type.value}
        
        if options.get("has_param") == "speed" or options.get("has_param2") == "speed":
            command["to_speed_rpm"] = self.param_speed.value()
        if options.get("has_param") == "rate" or options.get("has_param2") == "rate":
            command["accel_rate"] = self.param_rate.value()
            command["decel_rate"] = self.param_rate.value()
        if options.get("has_param") == "torque":
            command["torque_limit"] = self.param_torque.value()
        if options.get("has_param") == "direction":
            command["direction"] = self.param_direction.currentText()
        if options.get("has_param") == "mode":
            command["ctrl_mode"] = self.param_mode.currentText()
        
        # For commands without speed param, use current speed as from_speed
        if "to_speed_rpm" not in command and cmd_type != PLCCommandType.STOP and cmd_type != PLCCommandType.EMERGENCY_STOP:
            command["to_speed_rpm"] = self._current_speeds.get(subsystem, 0.0)
        if "from_speed_rpm" not in command:
            command["from_speed_rpm"] = self._current_speeds.get(subsystem, 0.0)
        
        # Defaults
        command.setdefault("accel_rate", 100.0)
        command.setdefault("decel_rate", 150.0)
        command.setdefault("torque_limit", 100.0)
        command.setdefault("direction", "FWD")
        command.setdefault("ctrl_mode", "VELOCITY")
        
        # Emit for dashboard to process through pipeline
        self.command_submitted.emit(subsystem, command)
        self._hide_param_panel()


# ===========================================================================
# System State Panel - consolidated system status for Overview tab
# ===========================================================================

class SystemStatePanel(QFrame):
    """
    Consolidated system state display for the Overview tab.
    Shows overall plant health, governance status, and auth context.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box)
        self.setStyleSheet(
            "SystemStatePanel {"
            f" background-color: {BG_PANEL};"
            f" border: {BORDER_W}px solid {BORDER};"
            "}"
        )
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(GAP)
        
        # Title
        title = QLabel("SYSTEM STATUS")
        title.setStyleSheet(
            f"font-family: '{FONT_DISPLAY}'; font-size: 13px; font-weight: 700;"
            f" letter-spacing: 2px; color: {ACCENT}; background: transparent;"
        )
        layout.addWidget(title)
        
        # Grid of status items
        grid = QGridLayout()
        grid.setHorizontalSpacing(GAP * 3)
        grid.setVerticalSpacing(GAP)
        
        self.state_items = {}
        
        # Row 0: Plant health & governance
        items_row0 = [
            ("PLANT STATE", "plant_state", "RUNNING"),
            ("OVERALL RISK", "overall_risk", "LOW"),
            ("ACTIVE ALARMS", "active_alarms", "0"),
            ("GOVERNANCE", "governance", "NORMAL"),
            ("QUARANTINED", "quarantined_count", "0"),
            ("RESTRICTED", "restricted_count", "0"),
        ]
        for col, (label, key, default) in enumerate(items_row0):
            self._add_state_item(grid, 0, col, label, key, default)
        
        # Row 1: Auth & session context
        items_row1 = [
            ("MFA STATUS", "mfa_status", "—"),
            ("SUPERVISOR", "supervisor_status", "—"),
            ("DUAL CONTROL", "dual_control_status", "—"),
            ("TOKEN FRESH", "token_fresh_status", "—"),
            ("SESSION LEFT", "session_remaining", "--:--"),
            ("TOKEN JTI", "token_jti_display", "—"),
        ]
        for col, (label, key, default) in enumerate(items_row1):
            self._add_state_item(grid, 1, col, label, key, default)
        
        layout.addLayout(grid)
    
    def _add_state_item(self, grid, row, col, label_text, key, default):
        """Add a labeled state item to the grid."""
        container = QVBoxLayout()
        container.setSpacing(2)
        
        label = QLabel(label_text)
        label.setStyleSheet(f"color: {TEXT_FAINT}; font-size: 8px; font-weight: 600; letter-spacing: 1px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container.addWidget(label)
        
        value = QLabel(default)
        value.setFont(numeric_font(11, QFont.Weight.DemiBold))
        value.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {TEXT}; background: transparent;"
        )
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container.addWidget(value)
        
        grid.addLayout(container, row, col)
        self.state_items[key] = value
    
    def update_state(self, auth: Optional[AuthContext] = None, 
                     pipeline=None, metrics: Dict = None):
        """Update all state items with current data."""
        if auth:
            # MFA
            self.state_items["mfa_status"].setText("OTP VERIFIED" if auth.mfa_verified else "STANDARD")
            self.state_items["mfa_status"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {OK if auth.mfa_verified else WARN}; background: transparent;"
            )
            
            # Supervisor
            self.state_items["supervisor_status"].setText("AUTHORIZED" if auth.supervisor_approved else "STANDARD")
            self.state_items["supervisor_status"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {OK if auth.supervisor_approved else TEXT_DIM}; background: transparent;"
            )
            
            # Dual Control
            dc = auth.dual_control_satisfied()
            self.state_items["dual_control_status"].setText("SATISFIED" if dc else "PENDING")
            self.state_items["dual_control_status"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {OK if dc else WARN}; background: transparent;"
            )
            
            # Token Fresh
            tf = auth.token_fresh()
            self.state_items["token_fresh_status"].setText("FRESH" if tf else "STALE")
            self.state_items["token_fresh_status"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {OK if tf else ALARM}; background: transparent;"
            )
            
            # Session remaining
            remaining = int(auth.seconds_until_expiry())
            mins, secs = divmod(remaining, 60)
            self.state_items["session_remaining"].setText(f"{mins:02d}:{secs:02d}")
            self.state_items["session_remaining"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {ALARM if remaining < 60 else (WARN if remaining < 300 else OK)}; background: transparent;"
            )
            
            # Token JTI
            jti = auth.token_jti
            if jti:
                self.state_items["token_jti_display"].setText(jti[:12] + "...")
                self.state_items["token_jti_display"].setStyleSheet(
                    f"font-family: '{resolve_mono_family()}'; color: {TEXT_DIM}; background: transparent;"
                )
        
        if pipeline and metrics:
            # Plant state - aggregate from all subsystems
            states = []
            risk_levels = []
            quarantined = 0
            restricted = 0
            
            for sub_id, m in metrics.items():
                sub = pipeline.state_store.get(sub_id)
                states.append(sub.state.value)
                risk_levels.append(m.get("risk_level", "LOW"))
                if sub.state.value == "QUARANTINED":
                    quarantined += 1
                elif sub.state.value == "RESTRICTED":
                    restricted += 1
            
            # Overall plant state
            if "QUARANTINED" in states:
                plant_state = "QUARANTINED"
                plant_color = ALARM
            elif "RESTRICTED" in states:
                plant_state = "RESTRICTED"
                plant_color = RESTRICTED
            elif "DEGRADED" in states:
                plant_state = "DEGRADED"
                plant_color = WARN
            else:
                plant_state = "RUNNING"
                plant_color = OK
            
            self.state_items["plant_state"].setText(plant_state)
            self.state_items["plant_state"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; color: {plant_color}; background: transparent;"
            )
            
            # Overall risk (highest)
            risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
            max_risk = max(risk_levels, key=lambda r: risk_order.get(r, 0)) if risk_levels else "LOW"
            risk_colors = {"LOW": OK, "MEDIUM": WARN, "HIGH": ALARM, "CRITICAL": ALARM}
            self.state_items["overall_risk"].setText(max_risk)
            self.state_items["overall_risk"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; color: {risk_colors.get(max_risk, OK)}; background: transparent;"
            )
            
            # Quarantined/Restricted counts
            self.state_items["quarantined_count"].setText(str(quarantined))
            self.state_items["quarantined_count"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; color: {ALARM if quarantined > 0 else OK}; background: transparent;"
            )
            self.state_items["restricted_count"].setText(str(restricted))
            self.state_items["restricted_count"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; color: {RESTRICTED if restricted > 0 else OK}; background: transparent;"
            )
            
            # Active alarms
            alarm_count = quarantined + restricted
            self.state_items["active_alarms"].setText(str(alarm_count))
            self.state_items["active_alarms"].setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; color: {ALARM if alarm_count > 0 else OK}; background: transparent;"
            )


# ===========================================================================
# Main dashboard window
# ===========================================================================

class SecureGuardDashboard(QMainWindow):
    """
    Main SecureGuard operator console.

    Owns the governance pipeline, the five operator tabs, and the timer network
    that keeps them synchronised. Long-running work is metered through
    ``timeout_utils`` so slow hosts degrade gracefully instead of tripping
    upstream idle timeouts.
    """

    def __init__(self, parent=None, auth: Optional[AuthContext] = None, token: Optional[str] = None):
        super().__init__(parent)

        self.setWindowTitle("SecureGuard Governance Model")
        
        # Responsive scaling: calculate minimum and initial window size based on screen geometry
        app = QApplication.instance()
        screen = app.primaryScreen() if app else None
        if screen:
            avail = screen.availableGeometry()
            # Allow clean resizing even on 1366x768 or 1080p displays with 125%/150% scaling
            min_w = min(1180, int(avail.width() * 0.82))
            min_h = min(700, int(avail.height() * 0.82))
            self.setMinimumSize(min_w, min_h)
            init_w = min(1480, int(avail.width() * 0.95))
            init_h = min(900, int(avail.height() * 0.92))
            self.resize(init_w, init_h)
        else:
            self.setMinimumSize(1180, 700)
            self.resize(1400, 880)

        # Backend
        self.pipeline = SecureGuardPipeline()
        self.spec = self.pipeline.twin.spec
        self._auth = auth
        self._token = token

        # Command history feeding the charts tab
        self.command_history: Dict[str, List[Dict]] = {}
        # Live telemetry samples feeding the same charts. Without this the
        # trend charts only moved when a command was submitted, so they looked
        # frozen during normal running.
        self.trend_history: Dict[str, List[Dict]] = {}
        self.alarms: Dict[str, Dict] = {}

        # Thresholds
        self.thresholds = RiskThresholds()
        self._load_thresholds()

        # UI state
        self._heartbeat_on = False
        self._metrics: Dict[str, Dict[str, float]] = {}
        self._tab_status: Dict[str, str] = {}
        # False until the first live sample has been plotted, so the charts tab
        # is never blank while waiting for its first 30 s repaint.
        self._charts_painted = False

        self._init_ui()
        self._setup_timers()

        # Use pre-authenticated context if provided; otherwise show unauthenticated state
        if self._auth is not None:
            self.identity_card.update_auth(self._auth)
            self.statusBar.showMessage(f"Authenticated as {self._auth.username}", 4000)
        else:
            self.statusBar.showMessage("Not authenticated - restart app to sign in", 8000)
        
        self.refresh_subsystems()
        self.evidence_tab.reload()

    # -- construction -------------------------------------------------------

    def _init_ui(self):
        # No window-level stylesheet here on purpose. apply_theme(app) in main()
        # already installs INDUSTRIAL_QSS application-wide; re-applying the same
        # sheet on the QMainWindow merged it with the app sheet, so every widget
        # inherited its rules twice - which is how gradients and corner radii
        # survived a rewrite of the sheet they came from.
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Identity strip
        self.identity_card = IdentityCard()
        root.addWidget(self.identity_card)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)

        self._build_overview_tab()
        self._build_charts_tab()
        self._build_evidence_tab()
        self._build_stream_tab()
        self._build_view3d_tab()
        self._build_push_commands_tab()

        root.addWidget(self.tabs, 1)

        # Toolbar
        toolbar = self.addToolBar("Actions")
        toolbar.setMovable(False)
        refresh = QAction("Refresh", self)
        refresh.triggered.connect(self.refresh_all)
        toolbar.addAction(refresh)
        verify = QAction("Verify Chain", self)
        verify.triggered.connect(self.evidence_tab._on_verify)
        toolbar.addAction(verify)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        # Live telemetry strip. The status bar only ever carried transient
        # showMessage() text and a clock, so nothing on the window said what the
        # plant was doing right now - an operator had to read a tile to learn
        # that telemetry had stopped arriving. Fed from the same sample as the
        # tiles, so it cannot disagree with them.
        self.telemetry_label = QLabel("TEL —")
        self.telemetry_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {TEXT_DIM}; background: transparent;"
        )
        self.heartbeat_label = QLabel("")
        self.heartbeat_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {TEXT_DIM}; font-weight: bold; background: transparent;"
        )
        self.clock_label = QLabel("")
        self.statusBar.addPermanentWidget(self.telemetry_label)
        self.statusBar.addPermanentWidget(self.heartbeat_label)
        self.statusBar.addPermanentWidget(self.clock_label)
        self.statusBar.showMessage("Ready")

    def _build_overview_tab(self):
        """Overview tab: system state, motor tiles, risk gauge, safety panels.

        Every section is a proper QWidget with Preferred/Expanding policy so
        the QScrollArea can measure and stack them without overlap.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        page = QWidget()
        page.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(12)

        # ── Title ──────────────────────────────────────────────────────────
        heading = QLabel("SUBSYSTEM OVERVIEW")
        heading.setStyleSheet(
            f"font-family: '{FONT_DISPLAY}'; font-size: 14px; font-weight: 700;"
            f" letter-spacing: 2px; color: {TEXT}; background: transparent;"
        )
        heading.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(heading)

        # ── System State Panel ─────────────────────────────────────────────
        # Streamlined 2-row consolidated overview status banner (~80 px)
        self.system_state_panel = SystemStatePanel()
        self.system_state_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.system_state_panel.setMinimumHeight(80)
        layout.addWidget(self.system_state_panel)

        # ── Motor tiles ────────────────────────────────────────────────────
        # Each SubsystemTile manages its minimum size (168px). Container breathes naturally.
        tile_row = QHBoxLayout()
        tile_row.setSpacing(8)
        self.tiles: Dict[str, SubsystemTile] = {}
        for subsystem_id in DEFAULT_SUBSYSTEMS:
            tile = SubsystemTile(subsystem_id)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.tiles[subsystem_id] = tile
            tile_row.addWidget(tile, 1)
        tile_container = QWidget()
        tile_container.setLayout(tile_row)
        tile_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(tile_container)

        # ── Risk gauge + command form ──────────────────────────────────────
        # RiskGauge min is 280×280; CommandForm is a small group box.
        # Neither row imposes a maximum — let them fill naturally.
        mid_row = QHBoxLayout()
        mid_row.setSpacing(12)

        self.risk_gauge = RiskGauge()
        self.risk_gauge.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.risk_gauge.setMinimumWidth(280)
        self.risk_gauge.setMaximumWidth(340)
        mid_row.addWidget(self.risk_gauge)

        self.command_form = CommandForm(DEFAULT_SUBSYSTEMS)
        self.command_form.command_submitted.connect(self._on_command_submitted)
        self.command_form.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        mid_row.addWidget(self.command_form, 1)

        mid_container = QWidget()
        mid_container.setLayout(mid_row)
        mid_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(mid_container)

        # ── Safety envelope + risk thresholds ─────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        safety_panel = SafetyEnvelopePanel(self.spec)
        safety_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        bottom_row.addWidget(safety_panel, 1)

        self.risk_config = RiskConfigWidget(self.thresholds)
        self.risk_config.thresholds_changed.connect(self._on_thresholds_changed)
        self.risk_config.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        bottom_row.addWidget(self.risk_config, 1)

        bottom_container = QWidget()
        bottom_container.setLayout(bottom_row)
        bottom_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(bottom_container)

        layout.addStretch(1)

        scroll.setWidget(page)
        self.tabs.addTab(scroll, "  OVERVIEW  ")

    def _build_charts_tab(self):
        self.charts_tab = ChartsTab()
        self.tabs.addTab(self.charts_tab, "  TREND CHARTS  ")

    def _build_evidence_tab(self):
        self.evidence_tab = EvidenceLogTab()
        self.tabs.addTab(self.evidence_tab, "  EVIDENCE LOG  ")

    def _build_stream_tab(self):
        self.stream_tab = StreamTab()
        self.tabs.addTab(self.stream_tab, "  LIVE STREAM  ")

    def _build_view3d_tab(self):
        self.view3d_tab = View3DTab()
        self.tabs.addTab(self.view3d_tab, "  3D VIEW  ")

    def _build_push_commands_tab(self):
        self.push_commands_tab = PushCommandsTab(self.pipeline, DEFAULT_SUBSYSTEMS)
        self.push_commands_tab.command_submitted.connect(self._on_push_command_submitted)
        self.tabs.addTab(self.push_commands_tab, "  PUSH COMMANDS  ")

        # Settings tab
        self._build_settings_tab()

        # Opening the ledger should show current records, not whatever was on
        # disk when the window was built.
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _build_settings_tab(self):
        """PLC-style settings panel: comms, motion, safety, UI preferences."""
        from industrial_theme import (
            BG_DEEP, BG_PANEL, BG_PANEL_HI, BG_INSET,
            BORDER, BORDER_HI, TEXT, TEXT_DIM, TEXT_FAINT,
            ACCENT, FONT_UI, FONT_DISPLAY, GAP, PAD_X, PAD_Y, BORDER_W,
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(PAD_X + 8, PAD_Y + 8, PAD_X + 8, PAD_Y + 8)
        root.setSpacing(12)

        # Title
        title = QLabel("SETTINGS")
        title.setStyleSheet(
            f"font-family: '{FONT_DISPLAY}'; font-size: 16px; font-weight: 700;"
            f" letter-spacing: 3px; color: {ACCENT}; background: transparent;"
        )
        root.addWidget(title)

        sub_title = QLabel("PLC CONFIGURATION & OPERATOR PREFERENCES")
        sub_title.setStyleSheet(
            f"color: {TEXT_FAINT}; font-size: 9px; letter-spacing: 2px; background: transparent;"
        )
        root.addWidget(sub_title)

        # ── Helper to build a settings section ────────────────────────────
        def make_section(label_text):
            gb = QGroupBox(label_text)
            return gb

        def add_row(grid, row, label_text, widget, tooltip=""):
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
            if tooltip:
                lbl.setToolTip(tooltip)
                widget.setToolTip(tooltip)
            grid.addWidget(lbl, row, 0)
            grid.addWidget(widget, row, 1)

        def labeled_grid(group):
            g = QGridLayout(group)
            g.setContentsMargins(PAD_X, PAD_Y + 4, PAD_X, PAD_Y)
            g.setSpacing(8)
            g.setColumnStretch(0, 1)
            g.setColumnStretch(1, 2)
            return g

        columns = QHBoxLayout()
        columns.setSpacing(12)

        # ── LEFT column ────────────────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(12)

        # PLC COMMUNICATIONS
        sec_comms = make_section("PLC COMMUNICATIONS")
        g = labeled_grid(sec_comms)
        self._settings = {}  # store widget refs

        self._settings["plc_ip"] = QLineEdit("192.168.1.100")
        self._settings["plc_ip"].setPlaceholderText("e.g. 192.168.1.100")
        add_row(g, 0, "PLC IP Address:", self._settings["plc_ip"], "Modbus/TCP host address")

        self._settings["plc_port"] = QSpinBox()
        self._settings["plc_port"].setRange(1, 65535)
        self._settings["plc_port"].setValue(502)
        add_row(g, 1, "Modbus Port:", self._settings["plc_port"], "Default Modbus/TCP port is 502")

        self._settings["poll_rate"] = QSpinBox()
        self._settings["poll_rate"].setRange(100, 10000)
        self._settings["poll_rate"].setValue(1000)
        self._settings["poll_rate"].setSuffix(" ms")
        add_row(g, 2, "Poll Rate:", self._settings["poll_rate"], "Telemetry poll interval")

        self._settings["conn_timeout"] = QSpinBox()
        self._settings["conn_timeout"].setRange(1, 60)
        self._settings["conn_timeout"].setValue(5)
        self._settings["conn_timeout"].setSuffix(" s")
        add_row(g, 3, "Connection Timeout:", self._settings["conn_timeout"])

        self._settings["auto_reconnect"] = QCheckBox("Auto-reconnect on loss")
        self._settings["auto_reconnect"].setChecked(True)
        g.addWidget(self._settings["auto_reconnect"], 4, 0, 1, 2)
        left.addWidget(sec_comms)

        # MOTION CONTROL
        sec_motion = make_section("MOTION CONTROL")
        gm = labeled_grid(sec_motion)

        self._settings["default_accel"] = QDoubleSpinBox()
        self._settings["default_accel"].setRange(1.0, 500.0)
        self._settings["default_accel"].setValue(100.0)
        self._settings["default_accel"].setSuffix(" %/s")
        self._settings["default_accel"].setSingleStep(10.0)
        add_row(gm, 0, "Default Accel Rate:", self._settings["default_accel"])

        self._settings["default_decel"] = QDoubleSpinBox()
        self._settings["default_decel"].setRange(1.0, 500.0)
        self._settings["default_decel"].setValue(150.0)
        self._settings["default_decel"].setSuffix(" %/s")
        self._settings["default_decel"].setSingleStep(10.0)
        add_row(gm, 1, "Default Decel Rate:", self._settings["default_decel"])

        self._settings["jog_speed"] = QDoubleSpinBox()
        self._settings["jog_speed"].setRange(10.0, 500.0)
        self._settings["jog_speed"].setValue(100.0)
        self._settings["jog_speed"].setSuffix(" RPM")
        add_row(gm, 2, "Jog Speed:", self._settings["jog_speed"])

        self._settings["max_speed_cap"] = QDoubleSpinBox()
        self._settings["max_speed_cap"].setRange(100.0, 2000.0)
        self._settings["max_speed_cap"].setValue(1500.0)
        self._settings["max_speed_cap"].setSuffix(" RPM")
        add_row(gm, 3, "Max Speed Cap:", self._settings["max_speed_cap"])

        self._settings["direction_default"] = QComboBox()
        self._settings["direction_default"].addItems(["FWD", "REV"])
        add_row(gm, 4, "Default Direction:", self._settings["direction_default"])

        self._settings["ctrl_mode_default"] = QComboBox()
        self._settings["ctrl_mode_default"].addItems(["VELOCITY", "TORQUE"])
        add_row(gm, 5, "Default Control Mode:", self._settings["ctrl_mode_default"])
        left.addWidget(sec_motion)
        left.addStretch()
        columns.addLayout(left, 1)

        # ── RIGHT column ───────────────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(12)

        # SAFETY & GOVERNANCE
        sec_safety = make_section("SAFETY & GOVERNANCE")
        gs = labeled_grid(sec_safety)

        self._settings["estop_lockout"] = QCheckBox("E-Stop requires supervisor reset")
        self._settings["estop_lockout"].setChecked(True)
        gs.addWidget(self._settings["estop_lockout"], 0, 0, 1, 2)

        self._settings["dual_ctrl_speed"] = QDoubleSpinBox()
        self._settings["dual_ctrl_speed"].setRange(0.0, 2000.0)
        self._settings["dual_ctrl_speed"].setValue(800.0)
        self._settings["dual_ctrl_speed"].setSuffix(" RPM")
        add_row(gs, 1, "Dual-Control Threshold:", self._settings["dual_ctrl_speed"],
                "Speed above which dual-control approval is required")

        self._settings["mfa_timeout"] = QSpinBox()
        self._settings["mfa_timeout"].setRange(60, 3600)
        self._settings["mfa_timeout"].setValue(3600)
        self._settings["mfa_timeout"].setSuffix(" s")
        add_row(gs, 2, "MFA Session TTL:", self._settings["mfa_timeout"])

        self._settings["quarantine_auto_reset"] = QCheckBox("Auto-recover from QUARANTINE after clear")
        self._settings["quarantine_auto_reset"].setChecked(False)
        gs.addWidget(self._settings["quarantine_auto_reset"], 3, 0, 1, 2)

        self._settings["audit_retention_days"] = QSpinBox()
        self._settings["audit_retention_days"].setRange(7, 3650)
        self._settings["audit_retention_days"].setValue(365)
        self._settings["audit_retention_days"].setSuffix(" days")
        add_row(gs, 4, "Evidence Retention:", self._settings["audit_retention_days"])
        right.addWidget(sec_safety)

        # DISPLAY & TELEMETRY
        sec_display = make_section("DISPLAY & TELEMETRY")
        gd = labeled_grid(sec_display)

        self._settings["refresh_rate"] = QComboBox()
        self._settings["refresh_rate"].addItems(["1 s", "2 s", "5 s", "10 s"])
        self._settings["refresh_rate"].setCurrentIndex(2)
        add_row(gd, 0, "Tile Refresh Rate:", self._settings["refresh_rate"])

        self._settings["chart_window"] = QComboBox()
        self._settings["chart_window"].addItems(["5 min", "15 min", "30 min", "1 hr", "4 hr"])
        self._settings["chart_window"].setCurrentIndex(2)
        add_row(gd, 1, "Chart Time Window:", self._settings["chart_window"])

        self._settings["status_bar_detail"] = QComboBox()
        self._settings["status_bar_detail"].addItems(["Minimal", "Standard", "Verbose"])
        self._settings["status_bar_detail"].setCurrentIndex(1)
        add_row(gd, 2, "Status Bar Detail:", self._settings["status_bar_detail"])

        self._settings["alarm_sound"] = QCheckBox("Enable alarm sounds")
        self._settings["alarm_sound"].setChecked(False)
        gd.addWidget(self._settings["alarm_sound"], 3, 0, 1, 2)

        self._settings["show_3d"] = QCheckBox("Show 3D View tab")
        self._settings["show_3d"].setChecked(True)
        gd.addWidget(self._settings["show_3d"], 4, 0, 1, 2)
        right.addWidget(sec_display)

        # NETWORK / KEYCLOAK
        sec_auth = make_section("AUTHENTICATION SERVER")
        ga = labeled_grid(sec_auth)

        self._settings["kc_url"] = QLineEdit("http://localhost:8080")
        add_row(ga, 0, "Keycloak URL:", self._settings["kc_url"])

        self._settings["kc_realm"] = QLineEdit("secureguard")
        add_row(ga, 1, "Realm:", self._settings["kc_realm"])

        self._settings["kc_client"] = QLineEdit("sg-dashboard")
        add_row(ga, 2, "Client ID:", self._settings["kc_client"])
        right.addWidget(sec_auth)
        right.addStretch()
        columns.addLayout(right, 1)

        root.addLayout(columns)

        # ── Action row ─────────────────────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.addStretch()

        btn_reset = QPushButton("RESTORE DEFAULTS")
        btn_reset.setToolTip("Restore all settings to factory defaults")
        action_row.addWidget(btn_reset)

        btn_apply = QPushButton("APPLY")
        btn_apply.setProperty("action", "primary")
        btn_apply.style().unpolish(btn_apply)
        btn_apply.style().polish(btn_apply)
        btn_apply.setToolTip("Apply and save settings")
        btn_apply.clicked.connect(self._on_settings_apply)
        action_row.addWidget(btn_apply)

        root.addLayout(action_row)

        scroll.setWidget(page)
        self.tabs.addTab(scroll, "  SETTINGS  ")

    def _on_settings_apply(self):
        """Apply settings from the Settings tab."""
        # Update telemetry poll rate
        try:
            poll_ms = self._settings["poll_rate"].value()
            if hasattr(self, "subsystem_timer"):
                self.subsystem_timer.setInterval(poll_ms)
        except Exception:
            pass
        self.statusBar.showMessage("Settings applied.", 3000)

    def _on_tab_changed(self, index: int):
        """Refresh data that is expensive to keep continuously live."""
        try:
            if index >= 0 and self.tabs.widget(index) is self.evidence_tab:
                self.evidence_tab.reload()
        except Exception:  # pragma: no cover - defensive
            pass

    def _setup_timers(self):
        timeouts = app_config.timeouts

        # Wall clock and the session countdown. One second because the countdown
        # is displayed as mm:ss - a slower tick would visibly skip.
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(timeouts.get_clock_interval())

        # Liveness blinker in the status bar.
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._tick_heartbeat)
        self.heartbeat_timer.start(timeouts.get_heartbeat_interval())

        # The telemetry tick: one sample per conveyor, repainting the tiles, the
        # risk gauge, the command form and the status strip, and appending one
        # point per conveyor to the trend history. It is NOT the chart repaint -
        # see SecureGuardDashboard.refresh_charts and the 30 s
        # ChartsTab.chart_refresh_timer.
        self.subsystem_timer = QTimer(self)
        self.subsystem_timer.timeout.connect(self.refresh_subsystems)
        self.subsystem_interval_ms = timeouts.get_subsystem_refresh_interval()
        self.subsystem_timer.start(self.subsystem_interval_ms)

        self._tick_clock()

    # -- timers -------------------------------------------------------------

    def _tick_clock(self):
        self.clock_label.setText(time.strftime("%Y-%m-%d %H:%M:%S"))
        # Session countdown must tick, otherwise it freezes at its login value.
        try:
            self.identity_card.tick_session()
        except Exception:  # pragma: no cover - defensive
            pass

    def _tick_heartbeat(self):
        self._heartbeat_on = not self._heartbeat_on
        # Token green / offline grey. The old neon terminal green is not in the
        # palette at all; a heartbeat is a state, so it borrows the same
        # OK/OFFLINE tokens as every other state readout.
        colour = OK if self._heartbeat_on else OFFLINE
        self.heartbeat_label.setText("LIVE" if self._heartbeat_on else "")
        self.heartbeat_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {colour}; font-weight: bold; background: transparent;"
        )

    # -- data flow ----------------------------------------------------------

    def refresh_subsystems(self):
        """Poll telemetry for every subsystem and repaint the overview."""
        try:
            telemetry = self.pipeline._get_telemetry()
        except Exception as exc:  # pragma: no cover - defensive
            self.statusBar.showMessage(f"Telemetry unavailable: {exc}", 6000)
            return

        for subsystem_id in DEFAULT_SUBSYSTEMS:
            subsystem = self.pipeline.state_store.get(subsystem_id)
            state_value = subsystem.state.value
            consecutive = subsystem.consecutive_low_risk

            metrics = self._read_metrics(telemetry, subsystem_id)
            self._metrics[subsystem_id] = metrics

            # Threshold verdict augments the governance state for colour only.
            verdict, driver = self.thresholds.severity(metrics)
            if verdict in ("RESTRICTED", "QUARANTINED") and state_value == "NORMAL":
                display_state = verdict
            else:
                display_state = state_value

            tile = self.tiles.get(subsystem_id)
            if tile:
                tile.update_data(subsystem_id, display_state, metrics, consecutive)
                if driver:
                    tile.setToolTip(f"Threshold pressure: {driver}")

            # Feed the command form from live telemetry. The "Current:" readout
            # was only ever written by record_result() after a command, so
            # between commands it showed the speed the drive had when the window
            # opened (0 RPM forever, on a freshly built console) and every
            # SET_SPEED was submitted with from_speed_rpm = 0 regardless of what
            # the motor was actually doing. Unconditional, including a genuine
            # zero: a belt that has stopped must read 0 RPM here too, or this
            # panel and the tile beside it disagree.
            speed = metrics.get("motor_speed_rpm")
            if speed is not None:
                self.command_form.record_result(subsystem_id, float(speed))
                # Also update the Push Commands tab with live speed
                if hasattr(self, 'push_commands_tab'):
                    self.push_commands_tab.update_current_speed(subsystem_id, float(speed))

            if verdict == "QUARANTINED" and self.alarms.get(subsystem_id, {}).get("level") != "QUARANTINED":
                self.alarms[subsystem_id] = {"level": "QUARANTINED", "driver": driver}

        self._refresh_risk_gauge()
        self._update_telemetry_status()
        self._sample_trends()
        self._publish_chart_history()
        # Update the System State panel
        if hasattr(self, 'system_state_panel'):
            self.system_state_panel.update_state(
                auth=self._auth,
                pipeline=self.pipeline,
                metrics=self._metrics
            )
        if not self._charts_painted:
            # First live sample: paint once so the tab is not blank until the
            # first 30 s repaint tick lands. After that the charts belong to
            # their own timer.
            self.charts_tab.refresh_charts()
            self._charts_painted = True

    def _update_telemetry_status(self):
        """Push the live sample summary into the status bar."""
        live = [m for m in self._metrics.values() if m]
        if not live:
            self.telemetry_label.setText("TEL —")
            return
        peak_speed = max((m.get("motor_speed_rpm") or 0.0) for m in live)
        peak_current = max((m.get("motor_current_amps") or 0.0) for m in live)
        peak_temp = max((m.get("temperature_c") or 0.0) for m in live)
        level = self.risk_gauge.level
        score = self.risk_gauge.value
        text = (
            f"TEL {len(live)}/{len(DEFAULT_SUBSYSTEMS)}"
            f"  {peak_speed:.0f} RPM"
            f"  {peak_current:.1f} A"
            f"  {peak_temp:.1f} degC"
            f"  RISK {level} {score:.1f}"
        )
        if text == self.telemetry_label.text():
            return
        self.telemetry_label.setText(text)
        self.telemetry_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {risk_color(level)}; background: transparent;"
        )

    def _sample_trends(self):
        """Append one live telemetry point per subsystem for the trend charts."""
        now = time.time()
        for subsystem_id, metrics in self._metrics.items():
            if not metrics:
                continue
            point = {
                "timestamp": now,
                "source": "telemetry",
                "motor_speed_rpm": metrics.get("motor_speed_rpm"),
                "motor_current_amps": metrics.get("motor_current_amps"),
                "temperature_c": metrics.get("temperature_c"),
                "box_rate_per_min": metrics.get("box_rate_per_min"),
                # Risk is only produced by command assessment, so the risk
                # chart holds its previous value across telemetry samples.
                "risk_score": None,
            }
            series = self.trend_history.setdefault(subsystem_id, [])
            series.append(point)
            # Bounded so a long session cannot grow the series without limit.
            if len(series) > 240:
                del series[: len(series) - 240]

    def _read_metrics(self, telemetry, subsystem_id: str) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
        try:
            reading = telemetry.read_telemetry(subsystem_id)
            trajectory = reading.trajectory
            metrics = {
                "motor_speed_rpm": float(getattr(trajectory, "motor_speed_rpm", 0.0) or 0.0),
                "motor_current_amps": float(getattr(trajectory, "motor_current_amps", 0.0) or 0.0),
                "temperature_c": float(getattr(trajectory, "temperature_c", 0.0) or 0.0),
                "box_rate_per_min": float(getattr(trajectory, "box_rate_per_min", 0.0) or 0.0),
                "conveyor_state": str(getattr(trajectory, "conveyor_state", "UNKNOWN")),
            }
        except Exception as exc:  # pragma: no cover - defensive
            self.statusBar.showMessage(f"{subsystem_id} telemetry read failed: {exc}", 4000)
        return metrics

    def _refresh_risk_gauge(self):
        if not self._metrics:
            return
        currents = [m.get("motor_current_amps", 0.0) for m in self._metrics.values()]
        temps = [m.get("temperature_c", 0.0) for m in self._metrics.values()]
        peak_current = max(currents) if currents else 0.0
        peak_temp = max(temps) if temps else 0.0

        current_ratio = peak_current / max(self.thresholds.over_current_a, 1e-6)
        temp_ratio = peak_temp / max(self.thresholds.over_temperature_c, 1e-6)
        score = min(100.0, max(current_ratio, temp_ratio) * 100.0)

        level = ("CRITICAL" if score >= 75 else "HIGH" if score >= 50
                 else "MEDIUM" if score >= 25 else "LOW")
        self.risk_gauge.set_value(score, level)

    def _publish_chart_history(self):
        """
        Hand the merged command + telemetry history to the charts tab.

        This is the 5 s half of the chart path: it only assigns the data. The
        repaint is on the charts tab's own 30 s timer, so a 5 s sample append
        costs one list concatenation instead of a five-panel redraw. Without the
        split, "sample every 5 s" and "redraw every 30 s" were the same event and
        the plots were repainted twelve times more often than the cadence asked
        for.
        """
        try:
            merged: Dict[str, List[Dict]] = {}
            for subsystem_id in set(self.command_history) | set(self.trend_history):
                combined = (
                    list(self.command_history.get(subsystem_id, []))
                    + list(self.trend_history.get(subsystem_id, []))
                )
                combined.sort(key=lambda r: r.get("timestamp", 0))
                merged[subsystem_id] = combined
            self.charts_tab.command_history = merged
        except Exception as exc:  # pragma: no cover - defensive
            self.statusBar.showMessage(f"Chart history update failed: {exc}", 4000)

    def refresh_charts(self):
        """
        Publish the history and redraw the plots now.

        Used for the operator-driven redraws - a submitted command, the toolbar
        Refresh action, the subsystem/range selectors - where waiting up to 30 s
        for the next repaint would look like the console had missed the event.
        """
        self._publish_chart_history()
        try:
            self.charts_tab.refresh_charts()
        except Exception as exc:  # pragma: no cover - defensive
            self.statusBar.showMessage(f"Chart refresh failed: {exc}", 4000)
        self._charts_painted = True

    def refresh_all(self):
        """Operator-initiated refresh: poll telemetry, then redraw every surface."""
        self.refresh_subsystems()
        self.refresh_charts()

    # -- commands -----------------------------------------------------------

    def _on_thresholds_changed(self, values: Dict[str, float]):
        self._save_thresholds(values)
        self.refresh_subsystems()

    def _on_command_submitted(self, subsystem_id: str, from_rpm: float, to_rpm: float):
        if self._auth is None:
            # Still record the attempt. A command refused for want of
            # authentication is exactly the event an auditor looks for, and
            # returning here silently would leave a hole in the ledger.
            try:
                from evidence_log import log_auth_rejection
                log_auth_rejection(
                    subsystem=subsystem_id,
                    command=f"SET_SPEED = {to_rpm:.0f} RPM",
                    reason="Command refused: operator not authenticated",
                )
                self.evidence_tab.reload()
            except Exception as exc:  # pragma: no cover - defensive
                self.statusBar.showMessage(f"Auth rejection log failed: {exc}", 6000)
            self.statusBar.showMessage("Command rejected locally: not authenticated", 5000)
            return

        self.statusBar.showMessage(f"Submitting {to_rpm:.0f} RPM to {subsystem_id} ...")
        self.command_form.submit_btn.setEnabled(False)

        try:
            result = self.pipeline.process_command(
                subsystem_id=subsystem_id,
                from_speed_rpm=from_rpm,
                to_speed_rpm=to_rpm,
                auth=self._auth,
            )
        except TimeoutError as exc:
            self.statusBar.showMessage(f"Command timed out: {exc}", 10000)
            return
        except Exception as exc:
            self.statusBar.showMessage(f"Command failed: {exc}", 10000)
            return
        finally:
            self.command_form.submit_btn.setEnabled(True)

        if result.accepted:
            self.statusBar.showMessage(
                f"ACCEPTED - {subsystem_id} -> {result.new_state.value if result.new_state else 'n/a'}",
                6000,
            )
        else:
            self.statusBar.showMessage(f"REJECTED - {result.reason}", 8000)

        self._record_command(subsystem_id, result, to_rpm)
        # One refresh: poll the new telemetry sample, publish the history and
        # redraw the plots so the point this command just recorded is on screen.
        # _record_command already reloaded the evidence table, and the repaint is
        # otherwise up to 30 s away, so a submitted command would look ignored.
        self.refresh_all()

    def _on_push_command_submitted(self, subsystem_id: str, command: dict):
        """Handle commands from the Push Commands tab."""
        if self._auth is None:
            try:
                from evidence_log import log_auth_rejection
                cmd_desc = f"{command.get('cmd_type', 'UNKNOWN')} = {command.get('to_speed_rpm', 0):.0f} RPM"
                log_auth_rejection(
                    subsystem=subsystem_id,
                    command=cmd_desc,
                    reason="Command refused: operator not authenticated",
                )
                self.evidence_tab.reload()
            except Exception as exc:  # pragma: no cover - defensive
                self.statusBar.showMessage(f"Auth rejection log failed: {exc}", 6000)
            self.statusBar.showMessage("Command rejected locally: not authenticated", 5000)
            return

        self.statusBar.showMessage(f"Submitting {command.get('cmd_type', 'CMD')} to {subsystem_id} ...")

        try:
            result = self.pipeline.process_command(
                subsystem_id=subsystem_id,
                from_speed_rpm=command.get("from_speed_rpm", 0.0),
                to_speed_rpm=command.get("to_speed_rpm", 0.0),
                cmd_type=command.get("cmd_type", "SET_SPEED"),
                accel_rate=command.get("accel_rate", 100.0),
                decel_rate=command.get("decel_rate", 150.0),
                torque_limit=command.get("torque_limit", 100.0),
                direction=command.get("direction", "FWD"),
                ctrl_mode=command.get("ctrl_mode", "VELOCITY"),
                auth=self._auth,
            )
        except TimeoutError as exc:
            self.statusBar.showMessage(f"Command timed out: {exc}", 10000)
            return
        except Exception as exc:
            self.statusBar.showMessage(f"Command failed: {exc}", 10000)
            return

        if result.accepted:
            self.statusBar.showMessage(
                f"ACCEPTED - {subsystem_id} -> {result.new_state.value if result.new_state else 'n/a'}",
                6000,
            )
        else:
            self.statusBar.showMessage(f"REJECTED - {result.reason}", 8000)

        self._record_command(subsystem_id, result, command.get("to_speed_rpm"))
        self.refresh_all()

    def _record_command(self, subsystem_id: str, result, to_rpm: Optional[float] = None):
        observed = getattr(result, "observed", None)
        predicted = getattr(result, "predicted", None)
        risk = getattr(result, "risk", None)

        entry: Dict[str, Any] = {
            "timestamp": time.time(),
            "accepted": bool(result.accepted),
            "risk_score": float(getattr(risk, "overall_risk_score", 0.0) or 0.0) if risk else 0.0,
            "risk_level": getattr(risk, "overall_risk_level", "LOW") if risk else "LOW",
            "reason": str(result.reason),
        }

        for source, prefix in ((observed, ""), (predicted, "pred_")):
            if source is None:
                continue
            for key in ("motor_speed_rpm", "motor_current_amps",
                        "temperature_c", "box_rate_per_min"):
                value = getattr(source, key, None)
                if value is not None:
                    entry[prefix + key] = float(value)

        history = self.command_history.setdefault(subsystem_id, [])
        history.append(entry)
        if len(history) > self.charts_tab._max_points:
            del history[: len(history) - self.charts_tab._max_points]

        if observed is not None:
            speed = float(getattr(observed, "motor_speed_rpm", 0.0) or 0.0)
            self.command_form.record_result(subsystem_id, speed)

        self._write_evidence(subsystem_id, result, to_rpm)

        # The ledger gained a row for this command; keep the browser current so
        # the tab does not look stale until RELOAD is pressed by hand.
        try:
            self.evidence_tab.reload()
        except Exception:  # pragma: no cover - defensive
            pass

    def _write_evidence(self, subsystem_id: str, result, to_rpm: Optional[float]):
        """Append this command to the tamper-evident forensic ledger.

        The Evidence Log tab reads ``evidence_log.read_all_evidence()``, so an
        in-memory history update alone leaves the operator staring at a stale
        ledger. Both accepted and rejected decisions are recorded: a rejection
        is exactly the event an auditor needs to find.
        """
        try:
            from evidence_log import log_evidence
        except ImportError as exc:  # pragma: no cover - defensive
            self.statusBar.showMessage(f"Evidence ledger unavailable: {exc}", 6000)
            return

        risk = getattr(result, "risk", None)
        observed = getattr(result, "observed", None)
        predicted = getattr(result, "predicted", None)
        previous_state = getattr(result, "previous_state", None)
        new_state = getattr(result, "new_state", None)
        accepted = bool(getattr(result, "accepted", False))
        reason = str(getattr(result, "reason", "") or "")

        try:
            from evidence_log import classify_decision
            decision = classify_decision(result)
        except ImportError:  # pragma: no cover - defensive
            decision = "ACCEPTED" if accepted else "REJECTED_SAFETY"

        target = "unknown" if to_rpm is None else f"{float(to_rpm):.0f} RPM"

        auth = self._auth
        try:
            log_evidence(
                subsystem=subsystem_id,
                command=f"SET_SPEED = {target}",
                previous_state=previous_state.value if previous_state else "UNKNOWN",
                predicted_trajectory=asdict(predicted) if predicted is not None else {},
                observed_trajectory=asdict(observed) if observed is not None else {},
                residual=0.0,
                risk_score=float(getattr(risk, "overall_risk_score", 0.0) or 0.0)
                if risk is not None
                else None,
                risk_level=str(getattr(risk, "overall_risk_level", "LOW")) if risk is not None else None,
                new_state=new_state.value if new_state else "UNKNOWN",
                authorization_path=reason,
                xai_explanation=str(getattr(result, "explanation", "") or ""),
                user=getattr(auth, "username", "unknown") if auth else "unknown",
                roles=sorted(getattr(auth, "roles", frozenset())) if auth else [],
                mfa_verified=bool(getattr(auth, "mfa_verified", False)) if auth else False,
                supervisor_approved=bool(getattr(auth, "supervisor_approved", False)) if auth else False,
                final_decision=decision,
                rejection_reason="" if accepted else reason,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.statusBar.showMessage(f"Evidence write failed: {exc}", 8000)

    # -- threshold persistence ---------------------------------------------

    def _thresholds_path(self) -> str:
        # Must use the same persistent data directory as the ledger and the
        # SQLite stores. os.getcwd() is arbitrary in a frozen build and may be
        # read-only, which silently discarded operator threshold edits.
        from app_paths import data_file
        return str(data_file("risk_thresholds.json"))

    def _load_thresholds(self):
        import json
        try:
            with open(self._thresholds_path(), "r", encoding="utf-8") as handle:
                self.thresholds = RiskThresholds.from_dict(json.load(handle))
        except (OSError, ValueError):
            pass  # defaults are fine

    def _save_thresholds(self, values: Dict[str, float]):
        import json
        try:
            with open(self._thresholds_path(), "w", encoding="utf-8") as handle:
                json.dump(values, handle, indent=2)
        except OSError as exc:  # pragma: no cover - defensive
            self.statusBar.showMessage(f"Could not persist thresholds: {exc}", 4000)

    # -- lifecycle ----------------------------------------------------------

    def _tear_down(self):
        """
        Release GPU/thread resources in a Qt-safe order.

        pyqtgraph.opengl widgets must be destroyed *before* the QApplication is
        torn down; otherwise the GL context is finalised against a dead Qt
        object tree and the process aborts with STATUS_STACK_BUFFER_OVERRUN
        (0xC0000409). Deferred deletion also has to be flushed explicitly,
        because ``processEvents`` alone does not deliver DeferredDelete.
        """
        if getattr(self, "_torn_down", False):
            return
        self._torn_down = True

        for timer_name in ("clock_timer", "heartbeat_timer", "subsystem_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()

        # Stop the telemetry worker thread before anything else.
        streamer = None
        try:
            streamer = getattr(self.stream_tab, "_streamer", None)
            if streamer is not None:
                streamer.request_stop()
                if not streamer.stop():
                    streamer.wait(10000)
        except Exception:  # pragma: no cover - defensive
            pass

        # Retire any shared worker threads while the QApplication is still alive.
        # A live QThread at interpreter exit aborts the process (0xC0000409).
        try:
            from dashboard_sync import shutdown_dashboard_sync
            shutdown_dashboard_sync()
        except Exception:  # pragma: no cover - defensive
            pass

        # Detach tabs from the tab widget, then retire the OpenGL view while the
        # QApplication is still alive.
        for name in ("view3d_tab", "charts_tab", "stream_tab", "evidence_tab"):
            tab = getattr(self, name, None)
            if tab is None:
                continue
            index = self.tabs.indexOf(tab)
            if index >= 0:
                self.tabs.removeTab(index)
            try:
                tab.close()
                tab.setParent(None)
                tab.deleteLater()
            except Exception:  # pragma: no cover - defensive
                pass
            setattr(self, name, None)

        app = QApplication.instance()
        if app is not None:
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()

    def closeEvent(self, event):
        self._tear_down()
        super().closeEvent(event)


def main(argv: Optional[List[str]] = None, auth: Optional[AuthContext] = None, token: Optional[str] = None):
    """Launch the SecureGuard operator console."""
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("SecureGuard Governance Model")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("SecureGuard")
    app.setOrganizationDomain("secureguard.io")
    # Deliberately no app.setFont() here: apply_theme() below owns the single
    # UI size (10pt). This line used to set 9pt and was immediately overridden,
    # so the two competing sizes made numeric columns look ragged to anyone who
    # read the pre-apply_theme value while debugging.

    # Industrial HMI styling must be installed before widgets are constructed,
    # otherwise Fusion resets part of the palette underneath us.
    from industrial_theme import apply_theme, apply_plot_theme
    apply_theme(app)
    apply_plot_theme(pg)

    window = SecureGuardDashboard(auth=auth, token=token)
    window.show()

    # Belt-and-braces: if the window is destroyed by other means (or the
    # interpreter starts shutting down without a close event), still retire the
    # OpenGL context in time.
    app.aboutToQuit.connect(window._tear_down)

    return app, window


if __name__ == "__main__":
    from startup_profile import run_startup_profile_gate
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    _app = QApplication.instance() or QApplication(sys.argv)
    _auth, _token = run_startup_profile_gate(_app)
    if _auth is None:
        sys.exit(0)
    _app, _window = main(auth=_auth, token=_token)
    sys.exit(_app.exec())