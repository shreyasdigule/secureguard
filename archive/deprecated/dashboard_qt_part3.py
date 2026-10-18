"""
SecureGuard Governance Model - PySide6 Dashboard (Tab Implementations)
Continuation from dashboard_qt.py
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QLabel, QPushButton, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QMenu,
    QTreeWidget, QTreeWidgetItem, QProgressBar
)
from PySide6.QtCore import Qt, QTimer, Signal, QDateTime, QSortFilterProxyModel
from PySide6.QtGui import QFont, QColor, QBrush, QPen

import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional

# Import existing modules
from pipeline import SecureGuardPipeline
from multi_dimensional_risk import MultiDimensionalRisk, RiskDimension
from evidence_log import read_all_evidence
from keycloak_auth import AuthContext
from causal_xai import CausalXAIEngine, CausalExplanation
from qt_view3d import Conveyor3DView
from physics_digital_twin import Trajectory

# ============================================================
# OVERVIEW TAB - Subsystem Tiles
# ============================================================

def _build_overview_tab(self):
    """Build the Overview tab with subsystem tiles and command form"""
    layout = QVBoxLayout(self.overview_tab)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(12)
    
    # Scroll area for subsystem tiles
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; } QScrollBar:vertical { width: 8px; }")
    
    self.subsystem_frame = QWidget()
    self.subsystem_frame.setStyleSheet("background: transparent;")
    self.subsystem_layout = QFlowLayout()
    self.subsystem_layout.setSpacing(12)
    self.subsystem_frame.setLayout(self.subsystem_layout)
    
    scroll.setWidget(self.subsystem_frame)
    layout.addWidget(scroll, 1)
    
    # Command form at bottom
    self._build_command_form(layout)


class QFlowLayout(QLayout):
    """Flow layout for subsystem tiles"""
    def __init__(self, parent=None, margin=12, spacing=12):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(12)
        self._items = []
    
    def addItem(self, item):
        self._items.append(item)
    
    def count(self):
        return len(self._items)
    
    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None
    
    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None
    
    def expandingDirections(self):
        return Qt.Orientation(0)
    
    def hasHeightForWidth(self):
        return True
    
    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)
    
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)
    
    def sizeHint(self):
        return self.minimumSize()
    
    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size + QSize(20, 20)
    
    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        row_height = 0
        spacing = self.spacing()
        
        for item in self._items:
            widget = item.widget()
            if widget:
                w = widget.sizeHint().width()
                h = widget.sizeHint().height()
                
                if x + widget.sizeHint().width() > self.geometry().width() and x > rect.x():
                    x = self.geometry().x()
                    y = y + row_height + self.spacing()
                    row_height = 0
                
                if not test_only:
                    item.setGeometry(QRect(x, y, widget.sizeHint().width(), widget.sizeHint().height()))
                
                x += widget.sizeHint().width() + spacing
                row_height = max(row_height, h)
        
        return y + row_height - rect.y()


# Monkey-patch QFlowLayout onto the dashboard class
def _build_overview_tab(self):
    layout = QVBoxLayout(self.overview_tab)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(12)
    
    # Header with refresh button
    header = QHBoxLayout()
    title = QLabel("SUBSYSTEM OVERVIEW")
    title.setStyleSheet("font-size: 18px; font-weight: bold; color: #5b9bd5;")
    header.addWidget(title)
    header.addStretch()
    
    refresh_btn = QPushButton("Refresh")
    refresh_btn.setFixedSize(100, 36)
    refresh_btn.clicked.connect(self.refresh_subsystems)
    header.addWidget(refresh_btn)
    layout.addLayout(header)
    
    # Scroll area for subsystem tiles
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; } QScrollBar:vertical { width: 8px; }")
    
    self.subsystem_container = QWidget()
    self.subsystem_container.setStyleSheet("background: transparent;")
    self.subsystem_flow = QHBoxLayout()  # Simple horizontal flow for now
    self.subsystem_flow.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    self.subsystem_flow.setSpacing(12)
    self.subsystem_flow.setContentsMargins(0, 0, 0, 0)
    self.subsystem_container.setLayout(self.subsystem_flow)
    
    scroll.setWidget(self.subsystem_container)
    layout.addWidget(scroll, 1)
    
    # Command form
    self._build_command_form(layout)


def _build_command_form(self, parent_layout):
    """Build the command input form at bottom of overview tab"""
    form_frame = QFrame()
    form_frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
    form_frame.setStyleSheet("""
        QFrame {
            background-color: #363c44;
            border: 1px solid #404854;
            border-radius: 8px;
        }
    """)
    
    layout = QGridLayout()
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)
    
    # Row 0: Subsystem ID, Command Type
    layout.addWidget(QLabel("Subsystem ID:"), 0, 0)
    self.subsystem_entry = QLineEdit()
    self.subsystem_entry.setPlaceholderText("e.g., Conveyor_Motor_01")
    layout.addWidget(self.subsystem_entry, 0, 1)
    
    layout.addWidget(QLabel("Command Type:"), 0, 2)
    self.cmd_type_combo = QComboBox()
    self.cmd_type_combo.addItems(["SET_SPEED", "SET_TORQUE", "SET_POSITION", "JOG", "EMERGENCY_STOP"])
    layout.addWidget(self.cmd_type_combo, 0, 3)
    
    # Row 1: Speeds
    layout.addWidget(QLabel("From Speed (RPM):"), 1, 0)
    self.from_speed_entry = QDoubleSpinBox()
    self.from_speed_entry.setRange(0, 2000)
    self.from_speed_entry.setDecimals(1)
    self.from_speed_entry.setValue(0)
    layout.addWidget(self.from_speed_entry, 1, 1)
    
    layout.addWidget(QLabel("To Speed (RPM):"), 1, 2)
    self.to_speed_entry = QDoubleSpinBox()
    self.to_speed_entry.setRange(0, 2000)
    self.to_speed_entry.setDecimals(1)
    self.to_speed_entry.setValue(500)
    layout.addWidget(self.to_speed_entry, 1, 3)
    
    # Row 2: Accel/Decel
    layout.addWidget(QLabel("Accel Rate (RPM/s²):"), 2, 0)
    self.accel_entry = QDoubleSpinBox()
    self.accel_entry.setRange(0, 500)
    self.accel_entry.setDecimals(1)
    self.accel_entry.setValue(100)
    layout.addWidget(self.accel_entry, 1, 1)
    
    layout.addWidget(QLabel("Decel Rate (RPM/s²):"), 2, 2)
    self.decel_entry = QDoubleSpinBox()
    self.decel_entry.setRange(0, 500)
    self.decel_entry.setDecimals(1)
    self.decel_entry.setValue(150)
    layout.addWidget(self.decel_entry, 2, 3)
    
    # Row 3: Torque, Direction, Mode
    layout.addWidget(QLabel("Torque Limit (%):"), 3, 0)
    self.torque_limit_entry = QDoubleSpinBox()
    self.torque_limit_entry.setRange(10, 150)
    self.torque_limit_entry.setDecimals(1)
    self.torque_limit_entry.setValue(100)
    layout.addWidget(self.torque_limit_entry, 1, 1)
    
    layout.addWidget(QLabel("Direction:"), 3, 2)
    self.direction_combo = QComboBox()
    self.direction_combo.addItems(["FWD", "REV"])
    layout.addWidget(self.direction_combo, 3, 3)
    
    layout.addWidget(QLabel("Control Mode:"), 4, 0)
    self.ctrl_mode_combo = QComboBox()
    self.ctrl_mode_combo.addItems(["VELOCITY", "TORQUE", "POSITION"])
    layout.addWidget(self.ctrl_mode_combo, 4, 3)
    
    # Submit button
    submit_btn = QPushButton("SUBMIT COMMAND")
    submit_btn.setFixedHeight(44)
    submit_btn.setStyleSheet("""
        QPushButton {
            background-color: #5b9bd5;
            color: #0a0a0a;
            font-weight: bold;
            font-size: 14px;
            border: none;
            border-radius: 6px;
            padding: 12px;
        }
        QPushButton:hover { background-color: #4a8bc4; }
        QPushButton:pressed { background-color: #3a7bc4; }
    """)
    layout.addWidget(submit_btn, 5, 0, 1, 4)
    submit_btn.clicked.connect(self.submit_command)
    
    self.command_frame = QFrame()
    self.command_frame.setLayout(layout)
    return self.command_frame


def submit_command(self):
    """Handle command submission from the dashboard"""
    if self._auth is None:
        QMessageBox.warning(self, "Not Authenticated", "Please log in using 'Switch Profile' first.")
        return
    
    try:
        subsystem_id = self.subsystem_entry.text().strip()
        if not subsystem_id:
            QMessageBox.warning(self, "Input Error", "Subsystem ID is required")
            return
        
        from_speed = self.from_speed_entry.value()
        to_speed = self.to_speed_entry.value()
        cmd_type = self.cmd_type_combo.currentText()
        accel_rate = 100  # self.accel_entry.value()
        decel_rate = 150  # self.decel_entry.value()
        torque_limit = self.torque_limit_entry.value()
        direction = "FWD"  # self.direction_combo.currentText()
        ctrl_mode = "VELOCITY"  # self.ctrl_mode_combo.currentText()
        
        auth = self._auth
        
        result = self.pipeline.process_command(
            subsystem_id=subsystem_id,
            from_speed_rpm=0,
            to_speed_rpm=self.to_speed_entry.value(),
            cmd_type="SET_SPEED",
            accel_rate=100,
            decel_rate=150,
            torque_limit=100,
            direction="FWD",
            ctrl_mode="VELOCITY",
            auth=self._auth
        )
        
        # Update UI
        if result.accepted:
            self.statusBar.showMessage(f"✓ ACCEPTED: {result.reason}", 5000)
            self.status_label.setText(f"ACCEPTED: {result.reason}")
            self.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        else:
            self.statusBar.showMessage(f"✗ REJECTED: {result.reason}", 5000)
            self.status_label.setText(f"REJECTED: {result.reason}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
        
        # Update gauge
        if hasattr(self, 'risk_gauge') and result.risk:
            self.risk_gauge.set_value(result.risk.overall_risk_score, result.risk.overall_risk_level)
        
        # Update mimic
        if hasattr(self, 'mimic') and result.predicted:
            pred_dict = {
                "conveyor_state": result.predicted.conveyor_state,
                "motor_speed_rpm": result.predicted.motor_speed_rpm,
                "motor_current_amps": result.predicted.motor_current_amps,
                "temperature_c": result.predicted.temperature_c,
                "box_rate_per_min": result.predicted.box_rate_per_min
            }
            obs_dict = {}
            if result.observed:
                obs_dict = {
                    "conveyor_state": result.observed.conveyor_state,
                    "motor_speed_rpm": result.observed.motor_speed_rpm,
                    "motor_current_amps": result.observed.motor_current_amps,
                    "temperature_c": result.observed.temperature_c,
                    "box_rate_per_min": result.observed.box_rate_per_min,
                }
            self.mimic.update_view(
                subsystem_id=self.subsystem_entry.text().strip(),
                state=result.new_state.value if result.new_state else "BLOCKED",
                running=result.accepted,
                readout={
                    "speed": result.observed.motor_speed_rpm if result.observed else result.predicted.motor_speed_rpm,
                    "current": result.observed.motor_current_amps if result.observed else result.predicted.motor_current_amps,
                    "temp": result.observed.temperature_c if result.observed else result.predicted.temperature_c,
                    "box_rate": result.observed.box_rate_per_min if result.observed else result.predicted.box_rate_per_min,
                }
            )
        
        # Update evidence log
        self.refresh_evidence()
        
        # Refresh subsystem tiles
        self.refresh_subsystems()
        
    except ValueError as e:
        QMessageBox.critical(self, "Input Error", f"Invalid input: {e}")
    except Exception as e:
        QMessageBox.critical(self, "Error", f"Command failed: {e}")


def refresh_subsystems(self):
    """Refresh subsystem tiles in overview tab"""
    # Clear existing tiles
    while self.subsystem_flow.count():
        item = self.subsystem_flow.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
    
    # Load from persistence
    try:
        import persistence
        rows = persistence.load_all_subsystem_states()
        
        if not rows:
            label = QLabel("No subsystems yet — submit a command below.")
            label.setStyleSheet("color: #8a919a; font-size: 14px; padding: 20px;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.subsystem_flow.addWidget(label)
            return
        
        for subsystem_id, state, consecutive in rows:
            color = STATE_COLORS.get(state, "gray")
            tile = SubsystemTile(subsystem_id)
            tile.update_data(subsystem_id, state, {}, consecutive)
            self.subsystem_flow.addWidget(tile)
            
    except Exception as e:
        print(f"Error refreshing subsystems: {e}")


# Continue with other tab implementations...
