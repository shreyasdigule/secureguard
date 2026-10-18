"""
SecureGuard Governance Model - UI Constants
Shared constants for PySide6 dashboard
"""

# Design tokens (ISA-101 high-performance HMI palette)
from PySide6.QtGui import QColor

BG = QColor("#2b2f36")
PANEL_BG = QColor("#363c44")
HEADER_BG = QColor("#22262c")
INPUT_BG = QColor("#1e2226")
TEXT = QColor("#c9ced4")
TEXT_DIM = QColor("#8a919a")
ACCENT = QColor("#5b9bd5")
LED_GREEN = QColor("#39ff6a")
GOLD = QColor("#ffd700")

STATE_COLORS = {
    "NORMAL": QColor("#4caf50"),
    "DEGRADED": QColor("#ffc107"),
    "RESTRICTED": QColor("#ff9800"),
    "QUARANTINED": QColor("#f44336"),
}

RISK_LEVEL_TO_STATE = {
    "LOW": "NORMAL", "MEDIUM": "DEGRADED",
    "HIGH": "RESTRICTED", "CRITICAL": "QUARANTINED",
}

ALARM_STATES = {"RESTRICTED", "QUARANTINED"}

PARAM_LABELS = [
    ("motor_speed_rpm",    "Motor Speed",   "RPM"),
    ("motor_current_amps", "Motor Current", "A"),
    ("temperature_c",      "Temperature",   "deg C"),
    ("box_rate_per_min",   "Box Rate",      "items/min"),
    ("conveyor_state",     "Conv. State",   ""),
]

# IdentityCard class needs to be available
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

class IdentityCard(QFrame):
    """Identity card widget for the toolbar"""
    def __init__(self):
        super().__init__()
        self.profile_btn = QPushButton("Switch Profile")
        self.profile_btn.setVisible(False)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        
        # Avatar
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(32, 32)
        self.avatar_label.setStyleSheet("background: #5b9bd5; border-radius: 16px; color: #0a0a0a; font-weight: bold; font-size: 14px;")
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setText("?")
        layout.addWidget(self.avatar_label)
        
        # User info
        user_info = QVBoxLayout()
        user_info.setSpacing(0)
        user_info.setContentsMargins(0, 0, 0, 0)
        self.username_label = QLabel("Not authenticated")
        self.username_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #c9ced4;")
        self.roles_label = QLabel("Roles: —")
        self.roles_label.setStyleSheet("font-size: 10px; color: #8a919a;")
        user_info.addWidget(self.username_label)
        user_info.addWidget(self.roles_label)
        layout.addLayout(user_info)
        
        layout.addStretch()
        
        # Status indicators
        self.mfa_indicator = self._create_status_indicator("MFA", "—", "#ffc107")
        self.sup_indicator = self._create_status_indicator("SUP", "—", "#8a919a")
        self.dc_indicator = self._create_status_indicator("DUAL", "—", "#8a919a")
        self.expiry_label = QLabel("--:--")
        self.expiry_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #4caf50; font-family: 'Consolas', monospace;")
        self.expiry_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.expiry_label.setMinimumWidth(60)
        
        layout.addWidget(self.mfa_indicator)
        layout.addWidget(self.sup_indicator)
        layout.addWidget(self.dc_indicator)
        layout.addWidget(self.expiry_label)
        layout.addWidget(self.profile_btn)
    
    def _create_status_indicator(self, label: str, value: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        frame.setStyleSheet("background-color: #1e2226; border-radius: 4px; border: 1px solid #404854;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)
        
        label_widget = QLabel(label)
        label_widget.setStyleSheet("font-size: 7px; color: #8a919a; font-weight: bold;")
        label_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        
        value_label = QLabel(value)
        value_label.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {color};")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(value_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        return frame
