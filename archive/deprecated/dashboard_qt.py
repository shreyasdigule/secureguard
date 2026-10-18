"""
SecureGuard Governance Model - PySide6 Dashboard
Modern industrial control panel with PySide6 + pyqtgraph
"""

import os
import sys
import time
from typing import Optional, Dict, List, Any

# Set test mode before any imports
os.environ.setdefault("SECUREGUARD_TEST_MODE", "1")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QLineEdit, QComboBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QSplitter,
    QScrollArea, QGridLayout, QFormLayout, QGroupBox,
    QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QProgressBar, QSlider, QTextEdit, QTreeWidget,
    QTreeWidgetItem, QSplitter, QScrollArea, QSizePolicy,
    QMenuBar, QToolBar, QStatusBar, QDockWidget,
    QListWidget, QListWidgetItem, QCompleter, QStyledItemDelegate
)
from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, Slot, QSize,
    QRect, QPoint, QPropertyAnimation, QEasingCurve,
    QDateTime, QLocale, QSettings, QTranslator
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QIcon, QPixmap, QBrush,
    QPen, QFontDatabase, QAction, QKeySequence, QCursor
)
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np
import pyqtgraph.opengl as gl

# Import existing modules
from pipeline import SecureGuardPipeline
from keycloak_auth import validate_access_token, AuthContext
from keycloak_client import create_test_token
from physics_digital_twin import PhysicsBasedDigitalTwin, ConveyorSpecification, Trajectory
from multi_dimensional_risk import MultiDimensionalRiskEngine, MultiDimensionalRisk, RiskDimension
from evidence_log import read_all_evidence, log_evidence
from keycloak_auth import dual_control_required
from dual_control_store import check_dual_control
from digital_twin import SafetyEnvelope

# Set test mode
os.environ.setdefault("SECUREGUARD_TEST_MODE", "1")


class RiskGauge(QWidget):
    """Industrial risk gauge widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(120)
        self._value = 0
        self._level = "LOW"
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#1e2226')
        self.plot_widget.setMaximumHeight(100)
        self.plot_widget.hideButtons()
        self.plot_widget.hideAxis('left')
        self.plot_widget.hideAxis('bottom')
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)
        layout.addWidget(self.plot_widget)
        
        self.bar_item = pg.BarGraphItem(x=[0], height=[0], width=0.8, brush='#4caf50')
        self.plot_widget.addItem(self.bar_item)
        
        self.level_label = QLabel("RISK LEVEL: LOW")
        self.level_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.level_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #4caf50;")
        layout.addWidget(self.level_label)
        
        self.value_label = QLabel("0.0")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #5b9bd5;")
        layout.addWidget(self.value_label)
        
        self.setFixedHeight(130)
    
    def set_value(self, value: float, level: str):
        self._value = value
        self._level = level
        
        # Update bar
        self.bar_item.setOpts(height=[value], width=0.8)
        
        # Color based on level
        colors = {
            "LOW": "#4caf50",
            "MEDIUM": "#ffc107", 
            "HIGH": "#ff9800",
            "CRITICAL": "#f44336"
        }
        color = colors.get(level, "#4caf50")
        self.bar_item.setOpts(brush=color)
        
        # Update labels
        self.value_label.setText(f"{value:.1f}")
        self.value_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color};")
        self.level_label.setText(f"RISK LEVEL: {level}")
        self.level_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color};")


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
    """Subsystem status tile"""
    
    def __init__(self, subsystem_id: str, parent=None):
        super().__init__(parent)
        self.subsystem_id = subsystem_id
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setFixedWidth(280)
        self.setMinimumHeight(140)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Header with colored bar
        self.color_bar = QFrame()
        self.color_bar.setFixedHeight(6)
        self.color_bar.setStyleSheet("background-color: #4caf50;")
        self.color_bar.setMaximumWidth(1000)
        
        header_layout = QHBoxLayout()
        self.id_label = QLabel()
        self.id_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #c9ced4;")
        self.state_label = QLabel()
        self.state_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(self.id_label)
        header_layout.addStretch()
        header_layout.addWidget(self.state_label)
        
        layout.addWidget(self.color_bar)
        layout.addLayout(header_layout)
        
        # Metrics
        metrics_layout = QGridLayout()
        self.metric_labels = {}
        metrics = [
            ("Speed", "motor_speed_rpm", "RPM"),
            ("Current", "motor_current_amps", "A"),
            ("Temp", "temperature_c", "°C"),
            ("Box Rate", "box_rate_per_min", "/min"),
        ]
        for i, (label, key, unit) in enumerate(metrics):
            label_widget = QLabel(label)
            label_widget.setStyleSheet("color: #8a919a; font-size: 10px;")
            value_label = QLabel("--")
            value_label.setStyleSheet("font-weight: bold; color: #c9ced4; font-size: 14px;")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.metric_labels[key] = (value_label, unit)
            metrics_layout.addWidget(label_widget, i // 2, (i % 2) * 2)
            metrics_layout.addWidget(value_label, i // 2, (i % 2) * 2 + 1)
        
        layout.addLayout(metrics_layout)
        layout.addStretch()
        
        self.setStyleSheet("""
            QFrame {
                background-color: #363c44;
                border: 1px solid #404854;
                border-radius: 8px;
            }
            QFrame:hover {
                border: 1px solid #5b9bd5;
            }
        """)
    
    def update_data(self, subsystem_id: str, state: str, metrics: Dict, consecutive: int):
        self.subsystem_id = subsystem_id
        self.id_label.setText(subsystem_id)
        self.state_label.setText(state)
        
        color = STATE_COLORS.get(state, "gray")
        self.color_bar.setStyleSheet(f"background-color: {color};")
        self.state_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {color};")
        
        for key, (label, unit) in self.metric_labels.items():
            value = metrics.get(key)
            if value is not None:
                if isinstance(value, float):
                    label.setText(f"{value:.1f} {unit}")
                else:
                    label.setText(f"{value} {unit}")


class IdentityCard(QFrame):
    """User identity card with security context"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setStyleSheet("""
            QFrame {
                background-color: #363c44;
                border: 1px solid #404854;
                border-radius: 8px;
            }
        """)
        self._auth = None
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("IDENTITY & ACCESS")
        title.setStyleSheet("font-size: 12px; font-weight: bold; color: #8a919a;")
        header.addWidget(title)
        header.addStretch()
        
        self.profile_btn = QPushButton("Switch Profile")
        self.profile_btn.setStyleSheet("""
            QPushButton {
                background-color: #5b9bd5;
                color: #0a0a0a;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4a8bc4;
            }
        """)
        header.addWidget(self.profile_btn)
        layout.addLayout(header)
        
        # User info
        self.user_info = QLabel("No session")
        self.user_info.setStyleSheet("font-size: 24px; font-weight: bold; color: #c9ced4;")
        layout.addWidget(self.user_info)
        
        # Roles
        roles_layout = QHBoxLayout()
        self.roles_label = QLabel("Roles: —")
        self.roles_label.setStyleSheet("color: #5b9bd5; font-weight: bold;")
        roles_layout.addWidget(QLabel("Roles:"))
        roles_layout.addWidget(self.roles_label)
        roles_layout.addStretch()
        layout.addLayout(roles_layout)
        
        # Security status row
        status_layout = QHBoxLayout()
        
        # MFA Status
        self.mfa_frame = self._create_status_item("MFA", "—", "#ffc107")
        status_layout.addWidget(self.mfa_frame)
        
        # Supervisor
        self.sup_frame = self._create_status_item("SUPERVISOR", "—", "#8a919a")
        status_layout.addWidget(self.sup_frame)
        
        # Device
        self.device_frame = self._create_status_item("DEVICE", "—", "#8a919a")
        status_layout.addWidget(self.device_frame)
        
        # Token JTI
        self.jti_frame = self._create_status_item("TOKEN JTI", "—", "#8a919a")
        status_layout.addWidget(self.jti_frame)
        
        # Dual Control
        self.dc_frame = self._create_status_item("DUAL CTRL", "—", "#8a919a")
        status_layout.addWidget(self.dc_frame)
        
        # Token Fresh
        self.fresh_frame = self._create_status_item("TOKEN FRESH", "—", "#8a919a")
        status_layout.addWidget(self.fresh_frame)
        
        layout.addLayout(status_layout)
        
        # Session expiry
        expiry_layout = QHBoxLayout()
        expiry_label = QLabel("SESSION EXPIRES:")
        expiry_label.setStyleSheet("color: #8a919a; font-size: 10px;")
        self.expiry_label = QLabel("--:--")
        self.expiry_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #4caf50;")
        expiry_layout.addWidget(expiry_label)
        expiry_layout.addWidget(self.expiry_label)
        expiry_layout.addStretch()
        layout.addLayout(expiry_layout)
        
        self.setFixedHeight(220)
    
    def _create_status_item(self, label: str, value: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        frame.setStyleSheet("background-color: #1e2226; border-radius: 4px;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        
        label_widget = QLabel(label)
        label_widget.setStyleSheet("font-size: 9px; color: #8a919a; font-weight: bold;")
        layout.addWidget(label_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        
        value_label = QLabel(value)
        value_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color};")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(value_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        return frame
    
    def update_auth(self, auth: Optional[AuthContext]):
        self._auth = auth
        if auth is None:
            self.user_info.setText("No session")
            self.roles_label.setText("Roles: —")
            self._set_status(self.mfa_frame, "—", "#ffc107")
            self._set_status(self.sup_frame, "—", "#8a919a")
            self._set_status(self.device_frame, "—", "#8a919a")
            self._set_status(self.jti_frame, "—", "#8a919a")
            self._set_status(self.dc_frame, "—", "#8a919a")
            self._set_status(self.fresh_frame, "—", "#8a919a")
            self.expiry_label.setText("--:--")
            return
        
        self.user_info.setText(auth.username)
        self.roles_label.setText(f"Roles: {', '.join(sorted(auth.roles))}")
        
        # MFA
        if auth.mfa_verified:
            self._set_status(self.mfa_frame, "OTP VERIFIED", "#4caf50")
        else:
            self._set_status(self.mfa_frame, "STANDARD", "#ffc107")
        
        # Supervisor
        if auth.supervisor_approved:
            self._set_status(self.sup_frame, "AUTHORIZED", "#4caf50")
        else:
            self._set_status(self.sup_frame, "STANDARD", "#8a919a")
        
        # Device
        fp = auth.device_fingerprint
        self._set_status(self.device_frame, fp[:8] + "..." if fp != "unknown" else "—", "#c9ced4")
        
        # Token JTI
        jti = auth.token_jti
        self._set_status(self.jti_frame, jti[:8] + "..." if jti else "—", "#c9ced4")
        
        # Dual Control
        if auth.dual_control_satisfied():
            self._set_status(self.dc_frame, "SATISFIED", "#4caf50")
        else:
            self._set_status(self.dc_frame, "PENDING", "#ffc107")
        
        # Token Fresh
        if auth.token_fresh():
            self._set_status(self.fresh_frame, "FRESH", "#4caf50")
        else:
            self._set_status(self.fresh_frame, "STALE", "#f44336")
        
        # Expiry
        if auth.token_issued_at:
            age = time.time() - auth.token_issued_at
            remaining = max(0, 900 - age)  # 15 min default
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            self.expiry_label.setText(f"{mins:02d}:{secs:02d}")
            if remaining < 60:
                self.expiry_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #f44336;")
            elif remaining < 300:
                self.expiry_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffc107;")
            else:
                self.expiry_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #4caf50;")
        else:
            self.expiry_label.setText("--:--")
    
    def _set_status(self, frame: QFrame, value: str, color: str):
        for child in frame.findChildren(QLabel):
            if child.font().pointSize() == 12:
                child.setText(value)
                child.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color};")


class ProfileSwitcherDialog(QDialog):
    """Profile switcher dialog for quick operator switching"""
    
    def __init__(self, parent, on_auth_callback):
        super().__init__(parent)
        self.on_auth_callback = on_auth_callback
        self.setWindowTitle("Identity & Access — Profile Switcher")
        self.setFixedSize(560, 420)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog { background-color: #2b2f36; }
            QLabel { color: #c9ced4; }
            QPushButton {
                background-color: #363c44;
                color: #c9ced4;
                border: 1px solid #404854;
                border-radius: 6px;
                padding: 12px 24px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #404854; }
            QPushButton:pressed { background-color: #5b9bd5; }
            QTabWidget::pane { border: 1px solid #404854; background: #2b2f36; }
            QTabBar::tab { background: #2b2f36; color: #8a919a; padding: 8px 16px; }
            QTabBar::tab:selected { background: #5b9bd5; color: #0a0a0a; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header = QLabel("  SELECT OPERATOR PROFILE")
        header.setStyleSheet("font-size: 12px; font-weight: bold; color: #5b9bd5; padding: 12px; background: #22262c; border-bottom: 2px solid #5b9bd5;")
        layout.addWidget(header)
        
        notebook = QTabWidget()
        layout.addWidget(notebook)
        
        # Quick Profile tab
        tab_quick = QWidget()
        tab_quick_layout = QVBoxLayout(tab_quick)
        tab_quick_layout.setContentsMargins(16, 16, 16, 16)
        
        label = QLabel("Click a profile to authenticate instantly:")
        label.setStyleSheet("color: #8a919a; margin-bottom: 12px;")
        tab_quick_layout.addWidget(label)
        
        profiles = [
            ("operator01 (Standard)", "operator01", ["operator"], False),
            ("supervisor01 (MFA + Super)", "supervisor01", ["supervisor", "operator"], True),
            ("engineer01 (Standard)", "engineer01", ["engineer"], False),
            ("auditor01 (Read-only)", "auditor01", ["auditor"], False),
        ]
        
        for label_text, username, roles, mfa in profiles:
            btn = QPushButton(label_text)
            btn.setMinimumHeight(48)
            btn.clicked.connect(lambda checked, u=username, r=roles, m=mfa: self._login_test_profile(u, r, m))
            layout.addWidget(btn)
        
        notebook.addTab(tab_quick, "Quick Profile")
        
        # Manual Token tab
        tab_manual = QWidget()
        tab_manual_layout = QVBoxLayout(tab_manual)
        tab_manual_layout.setContentsMargins(16, 16, 16, 16)
        
        label = QLabel("Paste a JWT token manually:")
        label.setStyleSheet("color: #8a919a; margin-bottom: 8px;")
        tab_manual_layout.addWidget(label)
        
        self.manual_token = QTextEdit()
        self.manual_token.setPlaceholderText("Paste JWT token here...")
        self.manual_token.setMaximumHeight(100)
        self.manual_token.setStyleSheet("""
            QTextEdit {
                background: #1e2226;
                color: #c9ced4;
                border: 1px solid #404854;
                border-radius: 4px;
                padding: 8px;
                font-family: Consolas;
            }
        """)
        tab_manual_layout.addWidget(self.manual_token)
        
        manual_login = QPushButton("LOGIN WITH TOKEN")
        manual_login.clicked.connect(self._login_manual_token)
        manual_login.setStyleSheet("background-color: #5b9bd5; color: #0a0a0a; font-weight: bold; padding: 12px;")
        tab_manual_layout.addWidget(manual_login)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #ffc107; margin-top: 8px;")
        tab_manual_layout.addWidget(self.status_label)
        tab_manual_layout.addStretch()
        
        notebook.addTab(tab_manual, "Manual Token")
        layout.addWidget(notebook)
    
    def _login_test_profile(self, username: str, roles: List[str], mfa: bool):
        try:
            token = create_test_token(username, roles, mfa_verified=mfa)
            auth = validate_access_token(token)
            self.on_auth_callback(auth, token)
            self.accept()
        except Exception as e:
            self.status_label.setText(f"Error: {e}")
    
    def _login_manual_token(self):
        token = self.manual_token.toPlainText().strip()
        if not token:
            self.status_label.setText("Please enter a token")
            return
        try:
            auth = validate_access_token(token)
            self.on_auth_callback(auth, token)
            self.accept()
        except Exception as e:
            self.status_label.setText(f"Error: {e}")


# Color constants
BG = "#2b2f36"
PANEL_BG = "#363c44"
HEADER_BG = "#22262c"
INPUT_BG = "#1e2226"
TEXT = "#c9ced4"
TEXT_DIM = "#8a919a"
ACCENT = "#5b9bd5"
LED_GREEN = "#39ff6a"
GOLD = "#ffd700"

STATE_COLORS = {
    "NORMAL": "#4caf50",
    "DEGRADED": "#ffc107",
    "RESTRICTED": "#ff9800",
    "QUARANTINED": "#f44336",
}

# ... rest of the file would continue with the main window class


# This is a partial migration. The full dashboard would be quite long.
# Let me create the main window structure next.
