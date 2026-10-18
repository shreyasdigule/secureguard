"""
SecureGuard Governance Model - PySide6 Dashboard (3D View Tab)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QDoubleSpinBox, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

# Appearance is delegated to the design system, like every other tab: colour,
# density and the display face all come from the theme, so this tab cannot drift
# away from the other four.
from industrial_theme import (
    TEXT, TEXT_DIM, TEXT_FAINT, FONT_DISPLAY, PAD_X, PAD_Y, GAP,
)

try:
    from qt_view3d import Conveyor3DView
    QT_VIEW3D_AVAILABLE = True
except ImportError:
    QT_VIEW3D_AVAILABLE = False


class View3DTab(QWidget):
    """3D Conveyor Belt Visualization Tab"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._view3d = None
        self._view3d_running = False
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        # Same gutter as every other tab (Overview / Evidence / Live Stream /
        # Trend Charts). This tab used GAP on all four sides, which made its
        # content sit 4px left of the others when the operator switched tabs.
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(GAP)
        
        # Header
        header = QHBoxLayout()
        header.setSpacing(GAP)
        title = QLabel("3D CONVEYOR BELT VIEW")
        # Same display-face treatment as the charts, evidence-log and overview
        # headings: a fixed-weight label must not inherit a proportional or
        # monospaced face by accident. The legacy sheet here was 18px in an
        # off-token blue, so this title did not match any other tab.
        title.setStyleSheet(
            f"font-family: '{FONT_DISPLAY}'; font-size: 15px; font-weight: 700;"
            f" letter-spacing: 3px; color: {TEXT}; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch()
        
        if QT_VIEW3D_AVAILABLE:
            # Controls
            ctrl = QHBoxLayout()
            ctrl.setSpacing(GAP)
            ctrl.addWidget(QLabel("Belt Speed (RPM):"))
            
            self.view3d_speed_entry = QDoubleSpinBox()
            self.view3d_speed_entry.setRange(0, 2000)
            self.view3d_speed_entry.setValue(500)
            self.view3d_speed_entry.setDecimals(0)
            self.view3d_speed_entry.setSingleStep(50)
            self.view3d_speed_entry.setMinimumWidth(90)
            # Applied live, not only on START. The spin box is the operator's
            # setpoint control; if it only took effect after the next start, the
            # status strip and the belt would both report a speed the operator
            # had already changed.
            self.view3d_speed_entry.valueChanged.connect(self._on_view3d_speed)
            ctrl.addWidget(self.view3d_speed_entry)
            
            self.view3d_btn = QPushButton("  START 3D VIEW  ")
            self._set_view3d_action("primary")
            self.view3d_btn.clicked.connect(self._toggle_3d_view)
            ctrl.addWidget(self.view3d_btn)
            
            self.view3d_anomaly = QCheckBox("Inject Belt-Jam Anomaly")
            self.view3d_anomaly.setStyleSheet(
                f"color: {TEXT}; background: transparent;"
            )
            self.view3d_anomaly.stateChanged.connect(self._on_view3d_anomaly)
            ctrl.addWidget(self.view3d_anomaly)
            
            ctrl.addStretch()
            header.addLayout(ctrl)
        else:
            # Not available message. Informational text, so it wears TEXT_DIM:
            # an amber caution colour on a "you need to pip install something"
            # notice reads as a process warning the operator has to act on.
            msg = QLabel("3D View requires PySide6 + pyqtgraph with OpenGL support.\nRun: pip install PySide6 pyqtgraph pyqtgraph[opengl]")
            msg.setStyleSheet(
                f"color: {TEXT_DIM}; background: transparent;"
                f" padding: {PAD_Y}px {PAD_X}px;"
            )
            msg.setWordWrap(True)
            header.addWidget(msg)
        
        layout.addLayout(header)
        
        # 3D View canvas
        if QT_VIEW3D_AVAILABLE:
            self._view3d = Conveyor3DView(self)
            layout.addWidget(self._view3d, 1)
        else:
            placeholder = QLabel("3D View unavailable - install PySide6 + pyqtgraph[opengl]")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # The 40px padding this used to carry was the worst density
            # violation in the app: a disabled panel with a 40px cushion around
            # one line of text. Token padding only, so the panel tiles like the
            # rest of the window.
            placeholder.setStyleSheet(
                f"color: {TEXT_FAINT}; background: transparent;"
                f" padding: {PAD_Y}px {PAD_X}px;"
            )
            layout.addWidget(placeholder, 1)

    def _set_view3d_action(self, action: str) -> None:
        """
        Move the belt button between the theme's primary and danger actions.

        Qt only re-reads a dynamic property after the widget is unpolished, so
        without the repolish a button that has switched to STOP keeps the colours
        of the state it had when the tab was built - a running animation
        advertised in the colours of a stopped one.
        """
        self.view3d_btn.setProperty("action", action)
        self.view3d_btn.style().unpolish(self.view3d_btn)
        self.view3d_btn.style().polish(self.view3d_btn)
    
    def _toggle_3d_view(self):
        if not QT_VIEW3D_AVAILABLE or not hasattr(self, '_view3d'):
            return
        
        if self._view3d_running:
            self.stop_3d_view()
        else:
            self.start_3d_view()
    
    def start_3d_view(self):
        """Start 3D view animation."""
        if not QT_VIEW3D_AVAILABLE or not hasattr(self, '_view3d'):
            return
        try:
            spd = float(self.view3d_speed_entry.value())
        except:
            spd = 500.0
        self._view3d.start_animation(set_speed_rpm=spd)
        self._view3d_running = True
        self.view3d_btn.setText("  STOP 3D VIEW  ")
        self._set_view3d_action("danger")
    
    def stop_3d_view(self):
        """Stop 3D view animation."""
        if hasattr(self, '_view3d') and self._view3d_running:
            self._view3d.stop_animation()
            self._view3d_running = False
            self.view3d_btn.setText("  START 3D VIEW  ")
            self._set_view3d_action("primary")
    
    def _on_view3d_anomaly(self, state):
        if hasattr(self, '_view3d'):
            self._view3d.set_anomaly(state == Qt.CheckState.Checked.value)

    def _on_view3d_speed(self, rpm: float):
        """Push the setpoint into the 3D view so its readout stays truthful."""
        if getattr(self, '_view3d', None) is not None:
            self._view3d.set_speed(float(rpm))
    
    def closeEvent(self, event):
        if hasattr(self, '_view3d') and self._view3d_running:
            self._view3d.stop_animation()
        super().closeEvent(event)
    
# This file provides the 3D view tab for the PySide6 dashboard
# It integrates with the qt_view3d.py module
