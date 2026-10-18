"""
SecureGuard Governance Model - PySide6 Dashboard (Main Window)
Main entry point tying all tabs together
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
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
    QMenu, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QScrollArea, QTreeWidget, QTreeWidgetItem,
    QProgressBar, QSlider, QTextEdit, QTreeWidget,
    QTreeWidgetItem, QProgressBar, QSlider, QTextEdit,
    QTreeWidget, QTreeWidgetItem, QProgressBar, QSlider,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QProgressBar,
    QSlider, QTextEdit, QSplitter, QScrollArea, QSizePolicy,
    QMenuBar, QToolBar, QStatusBar, QDockWidget, QListWidget,
    QListWidgetItem, QCompleter, QStyledItemDelegate
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

    QDateTimeAxis, QBarSeries, QBarSet, QPieSeries
)
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np

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
from qt_view3d import Conveyor3DView
from charts_tab import ChartsTab
from evidence_tab import EvidenceLogTab, EvidenceDetailDialog
from evidence_tab import StreamTab
from view3d_tab import View3DTab

# Set test mode
os.environ.setdefault("SECUREGUARD_TEST_MODE", "1")

# Constants
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

RISK_LEVEL_TO_STATE = {
    "LOW": "NORMAL", "MEDIUM": "DEGRADED",
    "HIGH": "RESTRICTED", "CRITICAL": "QUARANTINED",
}

# ============================================================
# Main Dashboard Window
# ============================================================

class SecureGuardDashboard(QMainWindow):
    """Main dashboard window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SecureGuard Governance Model")
        self.setMinimumSize(1400, 900)
        
        # Initialize pipeline
        self.pipeline = SecureGuardPipeline()
        
        # Auth state
        self._auth = None
        self._token = None
        
        # Pipeline command history for charts
        self.command_history: Dict[str, List[Dict]] = {}
        
        # Streamer
        self._streamer = None
        self._stream_mode = False
        self._stream_history: List[Dict] = []
        self._stream_max_points = 60
        
        # Evidence log cache
        self._evidence_records_cache: list = []
        
        # 3D view
        self._view3d = None
        self._view3d_running = False
        self._view3d_history: list = []
        
        # Alarms
        self.alarms: Dict[str, Dict] = {}
        
        # Pipeline command history for charts
        self.command_history: Dict[str, List[Dict]] = {}
        
        self._init_ui()
        self._setup_timers()
        
        # Load initial subsystem states
        self.refresh_subsystems()
    
    def _init_ui(self):
        self.setWindowTitle("SecureGuard Governance Model")
        self.setMinimumSize(1400, 900)
        
        # Set dark theme palette
        self._setup_dark_palette()
        
        # Central widget with tabbed interface
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header/Identity Card
        self.identity_card = IdentityCard()
        self.identity_card.profile_btn.clicked.connect(self._show_profile_switcher)
        
        # Toolbar
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._create_toolbar())
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._create_identity_toolbar())
        
        # Main content with tabs
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setMovable(True)
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #404854; background: #2b2f36; }
            QTabBar::tab { background: #2b2f36; color: #8a919a; padding: 10px 24px; border: 1px solid #404854; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; min-width: 120px; }
            QTabBar::tab:selected { background: #5b9bd5; color: #0a0a0a; }
            QTabBar::tab:hover { background: #363c44; }
        """)
        
        # Create tabs
        self.overview_tab = QWidget()
        self.charts_tab = QWidget()
        self.evidence_tab = QWidget()
        self.stream_tab = QWidget()
        self.view3d_tab = QWidget()
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setMovable(True)
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #404854; background: #2b2f36; }
            QTabBar::tab { background: #2b2f36; color: #8a919a; padding: 10px 24px; border: 1px solid #404854; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; min-width: 120px; }
            QTabBar::tab:selected { background: #5b9bd5; color: #0a0a0a; }
            QTabBar::tab:hover { background: #363c44; }
        """)
        
        self.tab_widget.addTab(self.overview_tab, "  OVERVIEW  ")
        self.tab_widget.addTab(self.charts_tab, "  TREND CHARTS  ")
        self.tab_widget.addTab(self.evidence_tab, "  EVIDENCE LOG  ")
        self.tab_widget.addTab(self.stream_tab, "  LIVE STREAM  ")
        self.tab_widget.addTab(self.view3d_tab, "  3D VIEW  ")
        
        # Build each tab
        self._build_overview_tab()
        self._build_charts_tab()
        self._build_evidence_tab()
        self._build_stream_tab()
        self._build_3d_view_tab()
        
        main_layout = QVBoxLayout(self.centralWidget())
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.tab_widget)
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")
        
        # Apply stylesheet
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2f36; }
            QWidget { background-color: #2b2f36; color: #c9ced4; font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; font-size: 13px; }
            QFrame { background-color: #363c44; }
            QLabel { color: #c9ced4; }
            QPushButton { background-color: #363c44; color: #c9ced4; border: 1px solid #404854; border-radius: 4px; padding: 8px 16px; font-weight: 500; }
            QPushButton:hover { background-color: #404854; }
            QPushButton:pressed { background-color: #5b9bd5; }
            QPushButton:disabled { background-color: #1e2226; color: #8a919a; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {
                background: #1e2226; color: #c9ced4; border: 1px solid #404854; border-radius: 4px; padding: 6px 12px; selection-background-color: #5b9bd5;
            }
            QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { subcontrol-origin: border; width: 16px; }
            QTabWidget::pane { border: 1px solid #404854; background: #2b2f36; }
            QTabBar::tab { background: #2b2f36; color: #8a919a; padding: 10px 24px; border: 1px solid #404854; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; min-width: 120px; }
            QTabBar::tab:selected { background: #5b9bd5; color: #0a0a0a; }
            QTabBar::tab:hover { background: #363c44; }
            QTableWidget { background: #1e2226; color: #c9ced4; gridline-color: #404854; border: 1px solid #404854; selection-background-color: #5b9bd5; }
            QHeaderView::section { background: #22262c; color: #5b9bd5; padding: 8px; border: none; border-right: 1px solid #404854; font-weight: bold; }
            QTableWidget::item { padding: 8px; }
            QTableWidget::item:selected { background: #5b9bd5; color: #0a0a0a; }
            QProgressBar { border: 1px solid #404854; border-radius: 4px; background: #1e2226; text-align: center; }
            QProgressBar::chunk { background: #5b9bd5; }
            QSlider::groove:horizontal { height: 6px; background: #1e2226; border-radius: 3px; }
            QSlider::handle:horizontal { background: #5b9bd5; width: 16px; height: 16px; margin: -4px 0; border-radius: 8px; }
            QCheckBox { color: #c9ced4; spacing: 8px; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #404854; border-radius: 3px; background: #1e2226; }
            QCheckBox::indicator:checked { background: #5b9bd5; border: 1px solid #5b9bd5; }
        """)
    
    def _setup_dark_palette(self):
        """Setup dark color palette"""
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(BG))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.Base, QColor(INPUT_BG))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_BG))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.Button, QColor(PANEL_BG))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.BrightText, QColor("#f44336"))
        palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0a0a0a"))
        palette.setColor(QPalette.ColorRole.Disabled, QPalette.ColorGroup.Text, QColor(TEXT_DIM))
        palette.setColor(QPalette.ColorRole.Disabled, QPalette.ColorGroup.ButtonText, QColor(TEXT_DIM))
        self.setPalette(palette)
    
    def _create_toolbar(self) -> QToolBar:
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setStyleSheet("QToolBar { background: #22262c; border: none; spacing: 8px; padding: 4px; } QToolButton { background: transparent; border: none; padding: 8px; border-radius: 4px; } QToolButton:hover { background: #404854; }")
        
        # Actions
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh_subsystems)
        toolbar.addAction(refresh_action)
        
        toolbar.addSeparator()
        
        export_action = QAction("Export Evidence", self)
        export_action.triggered.connect(self._export_evidence)
        toolbar.addAction(export_action)
        
        clear_action = QAction("Clear Alarms", self)
        clear_action.triggered.connect(self._clear_alarms)
        toolbar.addAction(clear_action)
        
        toolbar.addSeparator()
        
        settings_action = QAction("Settings", self)
        toolbar.addAction(settings_action)
        
        return toolbar
    
    def _create_identity_toolbar(self) -> QToolBar:
        """Identity card as a toolbar"""
        toolbar = QToolBar("Identity")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setStyleSheet("QToolBar { background: #22262c; border: none; border-bottom: 1px solid #404854; spacing: 4px; padding: 4px 8px; } QToolButton { background: transparent; border: none; padding: 4px 8px; border-radius: 4px; } QToolButton:hover { background: #404854; }")
        
        # Identity widget
        identity_widget = QWidget()
        identity_layout = QHBoxLayout(identity_widget)
        identity_layout.setContentsMargins(8, 4, 8, 4)
        identity_layout.setSpacing(8)
        
        # Avatar
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(32, 32)
        self.avatar_label.setStyleSheet("background: #5b9bd5; border-radius: 16px; color: #0a0a0a; font-weight: bold; font-size: 14px;")
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setText("?")
        
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
        user_info.setSpacing(0)
        
        identity_layout = QHBoxLayout()
        identity_layout.setContentsMargins(8, 4, 8, 4)
        identity_layout.setSpacing(8)
        
        # Avatar
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(32, 32)
        self.avatar_label.setStyleSheet("background: #5b9bd5; border-radius: 16px; color: #0a0a0a; font-weight: bold; font-size: 14px;")
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setText("?")
        
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
        user_info.setSpacing(0)
        
        # Status indicators
        self.mfa_indicator = self._create_status_indicator("MFA", "—", "#ffc107")
        self.sup_indicator = self._create_status_indicator("SUP", "—", "#8a919a")
        self.dc_indicator = self._create_status_indicator("DUAL", "—", "#8a919a")
        self.expiry_label = QLabel("--:--")
        self.expiry_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #4caf50; font-family: 'Consolas', monospace;")
        self.expiry_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.expiry_label.setMinimumWidth(60)
        
        profile_btn = QPushButton("Switch Profile")
        profile_btn.setFixedHeight(32)
        profile_btn.clicked.connect(self._show_profile_switcher)
        
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        layout.addWidget(self.avatar_label)
        layout.addLayout(self._create_user_info())
        layout.addStretch()
        identity_layout.addWidget(self.mfa_indicator)
        identity_layout.addWidget(self.sup_indicator)
        identity_layout.addWidget(self.dc_indicator)
        identity_layout.addWidget(self._create_expiry())
        identity_layout.addSpacing(8)
        identity_layout.addWidget(profile_btn)
        
        toolbar.addWidget(identity_widget)
        toolbar.addSeparator()
        
        # Quick actions
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh_subsystems)
        toolbar.addAction(refresh_action)
        
        export_action = QAction("Export Evidence", self)
        export_action.triggered.connect(self._export_evidence)
        toolbar.addAction(export_action)
        
        return toolbar
    
    def _create_user_info(self):
        layout = QVBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.username_label = QLabel("Not authenticated")
        self.username_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #c9ced4;")
        self.roles_label = QLabel("Roles: —")
        self.roles_label.setStyleSheet("font-size: 10px; color: #8a919a;")
        layout.addWidget(self.username_label)
        layout.addWidget(self.roles_label)
        container = QWidget()
        container.setLayout(layout)
        return container
    
    def _create_avatar(self):
        label = QLabel()
        label.setFixedSize(32, 32)
        label.setStyleSheet("background: #5b9bd5; border-radius: 16px; color: #0a0a0a; font-weight: bold; font-size: 14px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setText("?")
        return label
    
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
    
    def _create_expiry(self):
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        frame.setStyleSheet("background-color: #1e2226; border-radius: 4px; border: 1px solid #404854;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)
        
        label = QLabel("EXPIRES")
        label.setStyleSheet("font-size: 7px; color: #8a919a; font-weight: bold;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.expiry_label = QLabel("--:--")
        self.expiry_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #4caf50; font-family: 'Consolas', monospace;")
        self.expiry_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.expiry_label, alignment=Qt.AlignmentFlag.AlignCenter)
        return frame
    
    def _update_identity_card(self):
        """Update identity card with current auth info"""
        if self._auth is None:
            self.username_label.setText("Not authenticated")
            self.roles_label.setText("Roles: —")
            self.mfa_value.setText("—")
            self.mfa_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #ffc107;")
            self.sup_value.setText("—")
            self.sup_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #8a919a;")
            self.dc_value.setText("—")
            self.dc_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #8a919a;")
            self.expiry_label.setText("--:--")
            return
        
        auth = self._auth
        self.username_label.setText(auth.username)
        self.roles_label.setText(f"Roles: {', '.join(sorted(auth.roles))}")
        
        if auth.mfa_verified:
            self.mfa_value.setText("OTP VERIFIED")
            self.mfa_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #4caf50;")
        else:
            self.mfa_value.setText("STANDARD")
            self.mfa_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #ffc107;")
        
        if auth.supervisor_approved:
            self.sup_value.setText("AUTHORIZED")
            self.sup_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #4caf50;")
        else:
            self.sup_value.setText("STANDARD")
            self.sup_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #8a919a;")
        
        if auth.token_jti:
            pass  # JTI display would go here
        
        if auth.dual_control_satisfied():
            self.dc_value.setText("SATISFIED")
            self.dc_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #4caf50;")
        else:
            self.dc_value.setText("PENDING")
            self.dc_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #ffc107;")
        
        if auth.token_fresh():
            self.fresh_value.setText("FRESH")
            self.fresh_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #4caf50;")
        else:
            self.fresh_value.setText("STALE")
            self.fresh_value.setStyleSheet("font-size: 11px; font-weight: bold; color: #f44336;")
        
        if auth.token_issued_at:
            age = time.time() - auth.token_issued_at
            remaining = max(0, 900 - age)
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            if remaining < 60:
                color = "#f44336"
            elif remaining < 300:
                color = "#ffc107"
            else:
                color = "#4caf50"
            self.expiry_label.setText(f"{mins:02d}:{secs:02d}")
            self.expiry_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color}; font-family: 'Consolas', monospace;")
        else:
            self.expiry_label.setText("--:--")
    
    def _show_profile_switcher(self):
        dialog = ProfileSwitcherDialog(self, self._on_auth_callback)
        dialog.exec()
    
    def _on_auth_callback(self, auth: AuthContext, token: str):
        """Callback when authentication succeeds"""
        self._auth = auth
        self._token = token
        self._update_identity_card()
        self.statusBar.showMessage(f"Authenticated as {auth.username}", 3000)
    
    def _setup_timers(self):
        """Setup periodic timers"""
        # Clock update
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1000)
        
        # Heartbeat
        self.heartbeat_timer = QTimer()
        self.heartbeat_timer.timeout.connect(self._tick_heartbeat)
        self.heartbeat_timer.start(600)
        
        # Chart refresh
        self.chart_timer = QTimer()
        self.chart_timer.timeout.connect(self.refresh_charts)
        self.chart_timer.start(5000)
        
        # Stream refresh
        self.stream_timer = QTimer()
        self.stream_timer.timeout.connect(self._update_stream)
        self.stream_timer.start(1000)
    
    def _tick_clock(self):
        self.clock_label.setText(time.strftime("%Y-%m-%d  %H:%M:%S"))
    
    def _tick_heartbeat(self):
        self.heartbeat_on = not self.heartbeat_on
        self.heartbeat_dot.setStyleSheet(f"color: {'#39ff6a' if self.heartbeat_on else '#22262c'}; font-size: 16px;")
    
    def _setup_timers(self):
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1000)
        
        self.heartbeat_timer = QTimer()
        self.heartbeat_timer.timeout.connect(self._tick_heartbeat)
        self.heartbeat_timer.start(600)
        
        self.chart_timer = QTimer()
        self.chart_timer.timeout.connect(self.refresh_charts)
        self.chart_timer.start(5000)
        
        self.stream_timer = QTimer()
        self.stream_timer.timeout.connect(self._update_stream)
        self.stream_timer.start(1000)


# This is getting very long. The key components are:
# 1. IdentityCard - for authentication display
# 2. ProfileSwitcherDialog - for user switching
# 3. SubsystemTile - for overview tab
# 3. RiskGauge - risk visualization
# 5. Command form
# 6. Tabs (Overview, Charts, Evidence, Stream, 3D View)

# Let me create the final main entry point and complete the dashboard
