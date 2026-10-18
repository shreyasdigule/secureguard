"""
qt_view3d.py - PySide6 + pyqtgraph 3D Conveyor View
Drop-in replacement for the matplotlib 3D view.
Run standalone: python qt_view3d.py
"""

import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, 
    QLabel, QDoubleSpinBox, QApplication
)
from PySide6.QtCore import QTimer, Qt, QElapsedTimer
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import MeshData
import pyqtgraph as pg
from config import app_config
# Colour comes from the design system, not from literals in this file: the 3D
# view sits inside the dashboard, and a panel that invents its own palette is
# how a green belt and an amber belt end up meaning different things in two
# places.
from industrial_theme import (
    ACCENT_HI, ALARM, BG_DEEP, BG_PANEL_HI, BLUE, BORDER_HI, OK, VIOLET, CYAN,
    ACCENT, GAP, PAD_X, PAD_Y, TEXT_DIM,
    numeric_font, resolve_mono_family,
)


# Belt-motion calibration.
#
# The loop has always advanced the belt by `speed / 6000` belt-length units per
# rendered frame, at a 33 ms frame budget. BELT_UNITS_DIVISOR keeps that literal;
# BELT_CALIBRATION_FRAME_MS pins the cadence it was measured at, so the pair
# together define a RATE in belt-length units per second:
#
#     units_per_second = (speed / BELT_UNITS_DIVISOR) / (BELT_CALIBRATION_FRAME_MS / 1000)
#
# 500 RPM therefore covers (500/6000)/0.033 = 2.525 units, and the 12-unit belt
# takes ~4.75 s.
BELT_UNITS_DIVISOR = 6000.0

# The frame budget the historical calibration was measured at: 30 FPS, 33 ms.
#
# Deliberately a fixed constant rather than something re-derived from the
# configured frame rate. Normalising on the live interval (as this file used to)
# makes the belt's apparent speed inversely proportional to the frame rate: 60
# FPS would halve it, so "raise the FPS for a smoother view" silently becomes
# "run the simulation slower". Motion is therefore units_per_second * elapsed
# seconds, where units_per_second comes from this constant - which is also why
# changing SG_VIEW3D_FPS cannot change how fast the belt appears to travel.
BELT_CALIBRATION_FRAME_MS = 33.0

# Belt slab length in scene units. One definition, because the geometry builder
# sizes the slab and the animation loop maps a 0..1 belt position onto it: two
# literals here is how the boxes quietly stop reaching the end of the belt.
BELT_LENGTH = 12.0


class Conveyor3DView(QWidget):
    """
    3D Conveyor Belt Visualization using PySide6 + pyqtgraph OpenGL.

    The animation cadence is configuration, not a literal: ``SG_VIEW3D_FPS``
    (default 30, i.e. a 33 ms frame budget) sets the QTimer interval. The belt's
    travel rate is calibrated separately and deliberately does NOT follow that
    interval, so changing the FPS changes only how smoothly the belt is drawn.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("3D Conveyor View")
        self.resize(1000, 700)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        layout.setSpacing(GAP)
        
        # Control panel
        ctrl = QHBoxLayout()
        ctrl.setSpacing(GAP)
        
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0, 2000)
        self.speed_spin.setValue(500)
        self.speed_spin.setSuffix(" RPM")
        self.speed_spin.setDecimals(0)
        self.speed_spin.setSingleStep(50)
        self.speed_spin.setMinimumWidth(140)
        self.speed_spin.valueChanged.connect(self.set_speed)
        
        self.start_btn = QPushButton("START 3D VIEW")
        self.start_btn.clicked.connect(self.toggle_animation)
        
        self.anomaly_chk = QCheckBox("Inject Belt-Jam Anomaly")
        self.anomaly_chk.stateChanged.connect(self.on_anomaly_toggle)
        
        ctrl.addWidget(QLabel("Speed:"))
        ctrl.addWidget(self.speed_spin)
        ctrl.addWidget(self.start_btn)
        ctrl.addWidget(self.anomaly_chk)
        ctrl.addStretch()
        
        layout.addLayout(ctrl)

        # Live status strip. The 3D panel used to have no text layer at all, so
        # the only thing an operator could read off it was the belt itself - and
        # a stopped animation was indistinguishable from one whose frames had
        # silently stopped firing. Every number here is telemetry, so it is
        # monospaced; the family is named in the widget's own sheet as well as
        # set on the font, because the application sheet's generic QWidget rule
        # outranks a programmatic setFont().
        self.status_label = QLabel("STOPPED")
        self.status_label.setFont(numeric_font(10))
        self.status_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {TEXT_DIM}; background: transparent;"
        )
        layout.addWidget(self.status_label)
        
        # 3D View
        self.view = gl.GLViewWidget()
        self.view.setCameraPosition(distance=18, elevation=25, azimuth=45)
        self.view.setBackgroundColor(BG_DEEP)
        layout.addWidget(self.view)
        
        # Scene setup. Belt geometry state is built here rather than after the
        # call so there is exactly one definition of it.
        self._box_positions = [i * 0.15 for i in range(6)]
        # Box fills cycle the chart-series tokens, so a box on the belt and a
        # trace on the trends tab are recognisably the same palette. OK / ALARM /
        # WARN are deliberately excluded: those are reserved for machine state,
        # and an alarm-red box riding a healthy conveyor reads as a fault that is
        # not there.
        self._box_colors = [pg.mkColor(c) for c in (BLUE, CYAN, ACCENT, VIOLET)]
        self._setup_scene()
        
        # Animation state first, then the timer that drives it: _start_animation
        # arms both frame clocks, so it cannot run before they exist.
        self._running = False
        self._anomaly = False
        self._speed = 500.0
        # Wall-clock source for belt motion. A per-frame constant made the
        # apparent conveyor speed a function of how often the timer actually
        # fired, so the same RPM setting moved the belt at different speeds on a
        # busy machine and an idle one.
        self._frame_clock = QElapsedTimer()
        # Accumulated seconds since the last box spawn, so injection cadence is
        # also time-based rather than "every N frames".
        self._spawn_elapsed = 0.0
        # Live counters behind the status strip.
        self._frame_count = 0
        self._fps_clock = QElapsedTimer()
        self._fps_elapsed_ms = 0
        self._measured_fps = 0.0

        # Animation timer. The interval is the configured frame budget, so the
        # cadence lives in config (SG_VIEW3D_FPS) instead of in a literal here.
        timeouts = app_config.timeouts
        self.fps = timeouts.get_view3d_fps()
        self.frame_interval_ms = timeouts.get_view3d_frame_interval_ms()
        self.timer = QTimer()
        self.timer.timeout.connect(self._animate)
        self.timer.setInterval(self.frame_interval_ms)
        self._update_status()

    def _start_animation(self):
        """
        Arm the frame clock and start the timer at the configured interval.

        Every path that begins animating goes through here (toggle, explicit
        start, resume), because starting the timer without restarting the clock
        bills the whole pause to the first frame after it and jumps the belt
        forward.
        """
        self._frame_clock.start()
        self._fps_clock.start()
        self._frame_count = 0
        self._fps_elapsed_ms = 0
        self._measured_fps = 0.0
        self.timer.start(self.frame_interval_ms)
        
    def _setup_scene(self):
        """Configure the 3D scene with grid, belt, rollers, motor, supports, boxes."""
        # Grid. The library defaults are translucent white at ~30% alpha with
        # antialias=True, which switches on GL_LINE_SMOOTH / GL_NICEST and
        # renders a soft glowing floor. The contract is a crisp 1px slate grid.
        grid = gl.GLGridItem(color=pg.mkColor(BORDER_HI), antialias=False, glOptions='opaque')
        grid.scale(1, 1, 1)
        grid.setSize(20, 20, 1)
        self.view.addItem(grid)
        
        # Belt surface
        belt = gl.GLBoxItem()
        belt.setSize(x=BELT_LENGTH, y=1.5, z=0.3)
        belt.translate(5, 0, 0.15)
        # One step above the BG_DEEP backdrop so the slab reads as a solid
        # surface rather than dissolving into the background.
        belt.setColor(pg.mkColor(BG_PANEL_HI))
        self.view.addItem(belt)
        self._belt = belt
        
        # Rollers (drive and return). smooth=True built per-vertex normals and
        # interpolated them across every face, i.e. Gouraud shading - the
        # smoothest-looking treatment the contract bans. smooth=False gives
        # per-face normals, so each facet stays distinct and the cylinder reads
        # as machined. The colour must also be a QColor: pyqtgraph unpacks the
        # mesh colour into a float4 at paint time, so the hex strings this used
        # to pass raised there.
        for x, color in [(-0.5, BLUE), (10.5, OK)]:
            roller = gl.GLMeshItem(
                meshdata=MeshData.cylinder(rows=20, cols=20, radius=(0.3, 0.3), length=1.5),
                smooth=False, color=pg.mkColor(color), shader='shaded', glOptions='opaque'
            )
            roller.translate(x, 0, 0.3)
            roller.rotate(90, 0, 1, 0)
            self.view.addItem(roller)
        
        # Motor housing
        motor = gl.GLBoxItem()
        motor.setSize(1.5, 1.0, 1.0)
        motor.translate(11.5, 0, 0.8)
        motor.setColor(pg.mkColor(BLUE))
        self.view.addItem(motor)
        self._motor = motor
        
        # Support frames
        for i in range(0, 11, 2):
            for y in [-0.9, 0.9]:
                support = gl.GLBoxItem()
                support.setSize(0.2, 0.2, 0.3)
                support.translate(i - 0.5, y, 0)
                support.setColor(pg.mkColor(BORDER_HI))
                self.view.addItem(support)
        
        # Boxes on belt
        self._boxes = []
        
        for i in range(6):
            box = gl.GLBoxItem()
            box.setSize(0.4, 0.4, 0.3)
            box.setColor(self._box_colors[i % len(self._box_colors)])
            self.view.addItem(box)
            self._boxes.append(box)
        
        self.view.setCameraPosition(distance=18, elevation=25, azimuth=45)

    def set_speed(self, rpm: float):
        self._speed = rpm
        self._update_status()

    def toggle_animation(self):
        if self._running:
            self._running = False
            self.timer.stop()
            self.start_btn.setText("START 3D VIEW")
            self._update_status()
        else:
            self._running = True
            self._start_animation()
            self.start_btn.setText("STOP 3D VIEW")
            self._update_status()

    def on_anomaly_toggle(self, state: int):
        self._anomaly = state == Qt.CheckState.Checked.value
        self._update_status()

    def _animate(self):
        if not self._running:
            return
        
        # Elapsed wall-clock time since the previous frame, in seconds. Clamped
        # to 100ms so a stalled frame (window drag, debugger break, a long GC)
        # cannot teleport the belt half its length when it resumes.
        if self._frame_clock.isValid():
            dt = min(self._frame_clock.restart(), 100.0) / 1000.0
        else:
            self._frame_clock.start()
            dt = 0.0
        
        # Move boxes along belt. The historical advance was speed / 6000 per
        # rendered frame at a 33 ms cadence; expressed as a rate against that
        # fixed calibration point it becomes units_per_second, and the per-frame
        # advance is that rate times the elapsed time since the previous frame.
        # At the default 30 FPS the two are the same number to the last bit, and
        # at any other configured FPS the belt still covers the same distance
        # per second - it is simply drawn with more or fewer steps to get there.
        units_per_second = (
            self._speed / BELT_UNITS_DIVISOR
        ) / (BELT_CALIBRATION_FRAME_MS / 1000.0)
        step = units_per_second * dt
        # Modulo wrap, so a long stall cannot leave a box stranded past the end
        # of the belt.
        self._box_positions = [(pos + step) % 1.0 for pos in self._box_positions]
        
        # Add new boxes occasionally, on elapsed time rather than a frame count.
        # At the documented cadence this still fires every 1.0s, as the old
        # "every 30 frames" did.
        self._spawn_elapsed += dt
        spawn_due = self._spawn_elapsed >= 1.0
        if spawn_due:
            self._spawn_elapsed -= 1.0
        if spawn_due and len(self._box_positions) < 8:
            self._box_positions.append(0.0)
            # Add visual box. Bright amber marks it as newly injected, which is
            # a different signal from any machine state a box could represent.
            if len(self._boxes) < 8:
                box = gl.GLBoxItem()
                box.setSize(0.4, 0.4, 0.3)
                box.setColor(pg.mkColor(ACCENT_HI))
                self.view.addItem(box)
                self._boxes.append(box)
        
        # Update box positions - use resetTransform for performance
        for box, pos in zip(self._boxes, self._box_positions):
            x = -1 + pos * BELT_LENGTH
            # Fixed lateral position. The previous sin(tick * 0.1) bob was a
            # continuously interpolated oscillation - exactly the smooth,
            # non-quantised motion the contract forbids - and it also drifted
            # the boxes off the belt centreline.
            box.resetTransform()
            box.translate(x, 0.0, 0.45)
        
        # Anomaly visual feedback. The injected jam is signalled by colour only; the
        # belt keeps its setpoint speed so the scenario does not change what the
        # operator is being asked to look at.
        if self._anomaly:
            self._belt.setColor(pg.mkColor(ALARM))
            self._motor.setColor(pg.mkColor(ALARM))
        else:
            self._belt.setColor(pg.mkColor(OK))
            self._motor.setColor(pg.mkColor(BLUE))

        # Live counters. The measured rate is averaged over a full second of wall
        # clock rather than read off the interval, so a host that cannot hold the
        # configured FPS says so instead of reporting the target back at itself.
        self._frame_count += 1
        window_ms = self._fps_clock.restart() if self._fps_clock.isValid() else 0
        self._fps_elapsed_ms += window_ms
        if self._fps_elapsed_ms >= 1000:
            self._measured_fps = (self._frame_count * 1000.0) / self._fps_elapsed_ms
            self._frame_count = 0
            self._fps_elapsed_ms = 0
        self._update_status()

    def _update_status(self):
        """
        Repaint the status strip.

        Called from every state change and once per frame, so it only touches the
        label when the text would actually change: a per-frame setText on a
        repainted label is pure overhead at 30 FPS.
        """
        if not self._running:
            parts = ["STOPPED", f"{self._speed:.0f} RPM", f"{self.fps:.0f} FPS TARGET"]
        else:
            parts = [
                "RUNNING",
                f"{self._speed:.0f} RPM",
                f"{self.fps:.0f} FPS TARGET",
                f"{self._measured_fps:.1f} FPS",
                f"{len(self._box_positions)} BOX",
            ]
        if self._anomaly:
            parts.append("ANOMALY INJECTED")
        text = "  ".join(parts)
        if text == self.status_label.text():
            return
        colour = ALARM if self._anomaly else (OK if self._running else TEXT_DIM)
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {colour}; background: transparent;"
        )

    # Properties for external access
    @property
    def running(self) -> bool:
        return self._running
    
    def start_animation(self, set_speed_rpm: float = 500.0):
        self._speed = set_speed_rpm
        self._running = True
        self._start_animation()
        self.start_btn.setText("STOP 3D VIEW")
        self._update_status()

    def stop_animation(self):
        self._running = False
        self.timer.stop()
        self.start_btn.setText("START 3D VIEW")
        self._update_status()

    def set_anomaly(self, active: bool):
        self._anomaly = active
        self.anomaly_chk.setChecked(active)
        self._update_status()


# Standalone test
if __name__ == '__main__':
    from industrial_theme import apply_theme, apply_plot_theme

    # The same bootstrap dashboard_qt uses. Run standalone without it this
    # window picks up default Windows chrome, so the HMI contract would not hold
    # for anyone checking the view outside the app.
    app = QApplication(sys.argv)
    apply_theme(app)
    apply_plot_theme(pg)

    view = Conveyor3DView()
    view.show()
    sys.exit(app.exec())
