"""
SecureGuard Governance Model - UI Constants
Shared constants for PyQt6 dashboard
"""

from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

# Design tokens (ISA-101 high-performance HMI palette)
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

RISK_LEVEL_TO_STATE = {
    "LOW": "NORMAL", "MEDIUM": "DEGRADED",
    "HIGH": "RESTRICTED", "CRITICAL": "QUARANTINED",
}

ALARM_STATES = {"RESTRICTED", "QUARANTINED"}

# IdentityCard class needs to be available
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

class IdentityCard:
    """Identity card widget for the toolbar"""
    def __init__(self):
        from PyQt6.QtWidgets import QPushButton
        self.profile_btn = QPushButton()
        self.profile_btn.setVisible(False)