"""
SecureGuard Governance Model - PySide6 Dashboard (Live Stream Tab)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QFrame, QGridLayout, QLineEdit, QComboBox, QDoubleSpinBox,
    QDialog, QScrollArea, QGroupBox, QTableWidget,
    QTableWidgetItem, QTextEdit
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, Slot
from PySide6.QtGui import QFont, QColor
import pyqtgraph as pg
import numpy as np
from collections import deque
from typing import List, Dict, Optional, Tuple
import atexit
import threading
import time

from timeout_utils import TELEMETRY_INTERVAL, STREAM_REFRESH_MS
from config import app_config
# No FONT_MONO here: it is a value captured at industrial_theme import time, so a
# module that imports it before apply_theme() runs keeps the pre-resolution
# default. Call resolve_mono_family() / numeric_font() instead.
from industrial_theme import (
    BG_PANEL, BG_INSET, BORDER, BORDER_HI,
    TEXT, TEXT_DIM, BLUE, VIOLET, WARN, OK, ALARM,
    BORDER_W, PAD_X, PAD_Y, GAP,
    apply_label, numeric_font, resolve_mono_family,
    style_plot, style_table, trace_pen,
)

from hardware_telemetry import get_global_telemetry, SimulatedHardwareTelemetry, TelemetryReading
from keycloak_auth import validate_access_token, AuthContext
from keycloak_client import create_test_token
from digital_twin import Trajectory


STREAM_SUBSYSTEM = "stream_telemetry"

# Every streamer ever created, so a crash or early exit can still stop the
# threads. A QThread destroyed while running aborts the whole process
# (0xC0000409), which used to take the app down when the Live Stream tab was
# open.
_LIVE_STREAMERS = set()


@atexit.register
def _stop_all_streamers():
    for streamer in list(_LIVE_STREAMERS):
        try:
            streamer.request_stop()
            streamer.wait(3000)
        except Exception:  # pragma: no cover - best effort
            pass


# ---------------------------------------------------------------------------
# Shared presentation helpers
# ---------------------------------------------------------------------------
# Every widget in this file that needs a readout, a panel edge or a chart range
# goes through one of these. Qt's setStyleSheet REPLACES the sheet a widget
# already had rather than merging into it, so a rule set spelled out in two
# places will eventually disagree with itself — and the cell that loses its
# font-family quietly falls back to the proportional UI face, which is how a
# 17px telemetry value ends up rendering as 10px Segoe UI.


def _flat_panel(object_name: str) -> str:
    """
    Build the only panel treatment used here: flat fill, 1px border, no radius.

    The old frame used a Raised shadow plus a vertical gradient with an 8px
    radius, i.e. three of the four things the industrial contract forbids. A
    bevel is especially wrong on a safety display: it implies a physical
    control, and these are read-only instruments.
    """
    return (
        f"QFrame#{object_name} {{"
        f" background-color: {BG_PANEL};"
        f" border: {BORDER_W}px solid {BORDER};"
        "}"
    )


def _mono_pixel_font(size_px: int, weight=None) -> QFont:
    """
    Monospace font at an exact *pixel* size.

    Every stylesheet in this file states sizes in px, but QFont treats a bare
    size argument as points, so numeric_font(17) would paint about 13% smaller
    than the sheet asks for. Setting the pixel size explicitly keeps the sheet
    and the widget font in agreement — and the widget font is what the widget
    actually lays out and measures text with.
    """
    font = numeric_font(size_px, weight)
    font.setPixelSize(size_px)
    return font


def _readout_value_style(colour: str) -> str:
    """
    Style sheet for a live telemetry readout value.

    The anomaly cell recolours itself on every tick, so the complete rule set
    has to be produced here both at build time and at update time. Setting only
    `color` on the update path replaces the whole sheet and drops the
    monospace family, the 17px size and the 700 weight — the cell then renders
    as body text in the proportional UI face.
    """
    return (
        f"font-family: '{resolve_mono_family()}';"
        f" font-size: 17px; font-weight: 700;"
        f" color: {colour};"
        " background: transparent;"
    )


def _value_window(values, headroom: float = 0.15) -> Tuple[float, float]:
    """
    Return an inclusive (low, high) window that shows every value in ``values``.

    SAFETY: this function exists so no plot can ever be drawn outside its own
    view. It anchors at zero because all four channels (RPM, A, °C, /min) are
    non-negative and an absolute scale is what an operator reads against a
    trip limit. ``headroom`` keeps a value at the top of the data inside the
    window with room to spare, so the step edge stays legible instead of
    sitting on the frame. A flat series has zero span, which pyqtgraph cannot
    frame at all, so it is grown to a one-unit window first.
    """
    finite = [float(v) for v in values if isinstance(v, (int, float)) and np.isfinite(v)]
    if not finite:
        return 0.0, 1.0

    low, high = min(finite), max(finite)
    if high - low <= 0.0:
        low, high = min(low, 0.0), max(high, 1.0)

    pad = (high - low) * headroom
    return low - pad, high + pad


def _mono_text_area(edit, size_px: int) -> None:
    """
    Apply the inset, tokenised, monospace treatment to a read-only text area.

    QTextEdit is dense chrome: sharp 1px border, token padding, no radius. The
    widget font is set as well as the sheet because a rich-text document takes
    its default character format from the widget font — a sheet alone leaves
    setHtml() content in the proportional face, which is how a risk score
    rendered without a fixed digit advance.
    """
    edit.setStyleSheet(
        "QTextEdit {"
        f" background: {BG_INSET};"
        f" color: {TEXT};"
        f" border: {BORDER_W}px solid {BORDER_HI};"
        f" padding: {PAD_Y}px {PAD_X}px;"
        f" font-family: '{resolve_mono_family()}';"
        f" font-size: {size_px}px;"
        "}"
    )
    edit.setFont(_mono_pixel_font(size_px))


def _value_label_style(size_px: int = 9, colour: str = TEXT) -> str:
    """
    Style sheet for a read-only forensic value: id, timestamp, hash or verdict.

    The family has to be named in the sheet as well as handed over through
    setFont(). The application sheet declares font-family on the generic
    QWidget rule, and that rule is applied over the widget font when Qt polishes
    the widget — so a label styled only with setFont() reverts to the
    proportional UI face the instant the dialog is shown. A widget-level sheet
    outranks the application sheet, which is what makes the monospace face
    stick; that matters most here because these are the values an operator
    reads out and compares character by character.
    """
    return (
        f"color: {colour}; background: transparent;"
        f" font-family: '{resolve_mono_family()}';"
        f" font-size: {size_px}px;"
    )


def _mono_cell(text: str) -> QTableWidgetItem:
    """
    Build a table cell that renders in the telemetry face.

    A cell with no explicit FontRole is painted from the APPLICATION's font for
    QTableView, not from the table's own font, so neither the setFont() inside
    style_table() nor a table-level font-family rule reaches the items. The
    numeric columns here (Predicted / Observed / Delta, e.g. "85.00 (20.0%)")
    therefore have to be given the font cell by cell, or they stay proportional
    and their digits re-flow as values change width.
    """
    item = QTableWidgetItem(text)
    item.setFont(numeric_font(9))
    return item


def _make_step_curve(plot, color: str):
    """
    Build one telemetry trace in the industrial contract.

    ``stepMode='right'`` holds each reading until the next one arrives, which is
    what sampled telemetry actually means: between two reads the value is the
    last value read, not an interpolation. Diagonal interpolation invents
    intermediate values that were never measured and hides the exact sample at
    which a step happened. ``connect='finite'`` breaks the line at a NaN instead
    of drawing straight through a gap, and ``antialias=False`` keeps the 1px
    step hairline crisp instead of smearing it into something that reads as a
    2px trace.

    Downsampling is pinned to one point and never auto-enabled: peak decimation
    would drop exactly the transient peak this panel exists to show, so the
    history length is bounded in ``_on_stream_tick`` instead.
    """
    curve = plot.plot(
        pen=trace_pen(color),
        stepMode="right",
        connect="finite",
        antialias=False,
    )
    curve.setDownsampling(1, False, "peak")
    # One polyline end to end. Letting the item clip itself would let a
    # transient just outside the visible range be trimmed out of the paint.
    curve.setClipToView(False)
    return curve


class TelemetryStreamer(QThread):
    """
    Background thread streaming telemetry at a configurable period.

    Threading rules this class must keep:
    * never override ``QThread.start`` - PySide6 calls it internally, so the
      entry point is ``start_streaming()`` instead;
    * ``run`` waits on a ``threading.Event`` rather than ``msleep``, because a
      single long ``msleep`` ignored ``stop()`` and let the caller drop the last
      reference to a still-running thread, which aborts the process
      ("QThread: Destroyed while thread is still running");
    * ``stop()`` reports whether the thread really finished so callers never
      destroy a live QThread.
    """

    tick = Signal(dict)
    failed = Signal(str)

    def __init__(self, telemetry_interface=None, parent=None):
        super().__init__(parent)
        self._stop_event = threading.Event()
        self._telemetry = telemetry_interface or get_global_telemetry()
        self._set_speed = 500.0
        self._period = TELEMETRY_INTERVAL
        self._anomaly = False
        self._anomaly_data: Optional[Trajectory] = None

    # -- lifecycle --------------------------------------------------------

    def start_streaming(self, set_speed_rpm: float = 500.0, period: Optional[float] = None):
        """Begin streaming. Connect signals before calling this."""
        if self.isRunning():
            return
        self._set_speed = set_speed_rpm
        if period is not None:
            self._period = max(0.5, float(period))
        self._stop_event.clear()
        _LIVE_STREAMERS.add(self)
        super().start()

    def request_stop(self):
        """Ask the thread to finish without blocking the UI."""
        self._stop_event.set()

    def stop(self, timeout_ms: int = 3000) -> bool:
        """Stop the thread. Returns False if it is still running."""
        self._stop_event.set()
        if self.isRunning() and not self.wait(timeout_ms):
            return False
        _LIVE_STREAMERS.discard(self)
        return True

    @property
    def is_streaming(self) -> bool:
        return self.isRunning()

    # -- controls ---------------------------------------------------------

    def inject_anomaly(self, active: bool):
        self._anomaly = active

    def set_anomaly_data(self, data: Trajectory):
        self._anomaly_data = data

    def set_setpoint(self, rpm: float):
        """Apply a belt-speed setpoint to the simulated source."""
        self._set_speed = float(rpm)

    def run(self):
        while not self._stop_event.is_set():
            start = time.time()
            try:
                if self._anomaly and self._anomaly_data is not None:
                    reading = self._telemetry.read_telemetry("stream_anomaly")
                    reading.trajectory = self._anomaly_data
                else:
                    # Drive the simulated source from the setpoint so the trace
                    # moves; without this the source reports a stopped belt.
                    if hasattr(self._telemetry, "set_commanded_state"):
                        rpm = self._set_speed
                        self._telemetry.set_commanded_state(
                            STREAM_SUBSYSTEM,
                            Trajectory(
                                conveyor_state="RUNNING" if rpm > 0 else "STOPPED",
                                motor_speed_rpm=rpm,
                                motor_current_amps=round(rpm / 105.0, 2),
                                temperature_c=25.0 + rpm / 60.0,
                                box_rate_per_min=round(rpm / 25.0, 1),
                            ),
                        )
                    reading = self._telemetry.read_telemetry(STREAM_SUBSYSTEM)
            except Exception as exc:
                # A telemetry backend hiccup must not kill the process; report
                # it and keep the loop alive for the next sample.
                self.failed.emit(str(exc))
                self._stop_event.wait(min(self._period, 1.0))
                continue

            self.tick.emit({
                "tick": int(time.time()),
                "motor_speed_rpm": reading.trajectory.motor_speed_rpm,
                "motor_current_amps": reading.trajectory.motor_current_amps,
                "temperature_c": reading.trajectory.temperature_c,
                "box_rate_per_min": reading.trajectory.box_rate_per_min,
                "anomaly": self._anomaly,
            })

            # Event.wait returns immediately when stop() is called.
            elapsed = time.time() - start
            self._stop_event.wait(max(0.05, self._period - elapsed))


class StreamTab(QWidget):
    """Live telemetry stream tab with pyqtgraph real-time charts"""
    
    def __init__(self, parent=None):
        super().__init__()
        self._streamer = None
        self._stream_mode = False
        self._stream_history: List[Dict] = []
        self._stream_max_points = 60
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        # Density comes from the shared tokens, so this tab tiles like every
        # other panel instead of carrying its own 12px margins and 12px gaps -
        # and it uses the same tab gutter (see dashboard_qt._build_overview_tab)
        # so switching tabs does not shift the content sideways.
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(GAP)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("LIVE TELEMETRY STREAM")
        # The role property rather than a local sheet: one definition of the
        # display face means this title cannot drift away from the other tabs.
        title.setProperty("role", "title")
        header.addWidget(title)
        header.addStretch()

        # Controls
        self.stream_btn = QPushButton("  START STREAM  ")
        # State is carried by the theme's own button properties instead of three
        # near-identical per-widget sheets. They are already tokenised: 1px
        # border, sharp corners and the shared button padding.
        self._set_stream_button_action("primary")
        self.stream_btn.clicked.connect(self._toggle_stream)
        header.addWidget(self.stream_btn)
        
        # Commanded belt speed used by the simulated telemetry source.
        header.addWidget(QLabel("Setpoint (RPM):"))
        self.stream_speed_spin = QDoubleSpinBox()
        self.stream_speed_spin.setRange(0, 2000)
        self.stream_speed_spin.setValue(500)
        self.stream_speed_spin.setDecimals(0)
        self.stream_speed_spin.setSingleStep(50)
        self.stream_speed_spin.setSuffix(" RPM")
        self.stream_speed_spin.setMinimumWidth(110)
        self.stream_speed_spin.setToolTip("Belt speed setpoint applied to the telemetry source")
        header.addWidget(self.stream_speed_spin)
        
        # Sampling period - deliberately generous so slow hosts stay responsive.
        header.addWidget(QLabel("Sample (s):"))
        self.stream_period_spin = QDoubleSpinBox()
        self.stream_period_spin.setRange(0.5, 60.0)
        self.stream_period_spin.setDecimals(1)
        self.stream_period_spin.setSingleStep(1.0)
        self.stream_period_spin.setValue(TELEMETRY_INTERVAL)
        self.stream_period_spin.setMinimumWidth(80)
        self.stream_period_spin.setToolTip("Telemetry sampling period in seconds")
        header.addWidget(self.stream_period_spin)

        self.anomaly_chk = QCheckBox("Inject Belt-Jam Anomaly")
        self.anomaly_chk.stateChanged.connect(self._on_anomaly_toggle)
        header.addWidget(self.anomaly_chk)
        header.addStretch()

        self.status_lbl = QLabel("IDLE")
        # A state word is read as text and compared against other states, so it
        # gets the fixed digit advance like every other readout here.
        self.status_lbl.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent;"
            f" font-family: '{resolve_mono_family()}';"
            " font-size: 11px; letter-spacing: 1px;"
        )
        self.status_lbl.setFont(_mono_pixel_font(11))
        header.addWidget(self.status_lbl)

        layout.addLayout(header)

        # Readout panel
        readout_frame = QFrame()
        readout_frame.setObjectName("readout_panel")
        readout_frame.setFrameShape(QFrame.Shape.NoFrame)
        readout_frame.setStyleSheet(_flat_panel("readout_panel"))
        readout_layout = QGridLayout(readout_frame)
        readout_layout.setSpacing(GAP)
        readout_layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        
        self.stream_labels = {}
        stream_params = [
            ("tick", "Tick #", ""),
            ("motor_speed_rpm", "Motor Speed", "RPM"),
            ("motor_current_amps", "Motor Current", "A"),
            ("temperature_c", "Temperature", "°C"),
            ("box_rate_per_min", "Box Rate", "/min"),
            ("anomaly", "Anomaly", ""),
        ]
        
        for row, (key, label, unit) in enumerate(stream_params):
            lbl = QLabel(label)
            lbl.setProperty("role", "caption")
            val_lbl = QLabel("—")
            val_lbl.setStyleSheet(_readout_value_style(OK))
            val_lbl.setFont(_mono_pixel_font(17, QFont.Weight.Bold))
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if unit:
                unit_lbl = QLabel(unit)
                unit_lbl.setProperty("role", "caption")
                readout_layout.addWidget(lbl, row, 0)
                readout_layout.addWidget(val_lbl, row, 1)
                readout_layout.addWidget(unit_lbl, row, 2)
            else:
                readout_layout.addWidget(lbl, row, 0)
                readout_layout.addWidget(val_lbl, row, 1)
            self.stream_labels[key] = val_lbl

        layout.addWidget(readout_frame)

        # Charts
        charts_frame = QFrame()
        charts_frame.setObjectName("charts_panel")
        charts_frame.setFrameShape(QFrame.Shape.NoFrame)
        charts_frame.setStyleSheet(_flat_panel("charts_panel"))
        charts_layout = QHBoxLayout(charts_frame)
        # No margin of its own: the tab layout owns spacing so panels tile
        # edge-to-edge instead of floating in their own padding.
        charts_layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)

        self.stream_fig = pg.GraphicsLayoutWidget()
        self.stream_fig.setBackground(BG_INSET)

        # Four plots, tiled 2x2. style_plot() owns every background, grid, axis
        # pen, tick font and frame decision, so these four cannot drift apart
        # from the charts in charts_tab.
        self.speed_plot = self.stream_fig.addPlot(row=0, col=0)
        self.current_plot = self.stream_fig.addPlot(row=0, col=1)
        self.temp_plot = self.stream_fig.addPlot(row=1, col=0)
        self.box_plot = self.stream_fig.addPlot(row=1, col=1)

        for plot, title, y_label in (
            (self.speed_plot, "Motor Speed (RPM)", "RPM"),
            (self.current_plot, "Motor Current (A)", "A"),
            (self.temp_plot, "Temperature (°C)", "°C"),
            (self.box_plot, "Box Rate (/min)", "/min"),
        ):
            # The X axis is a sample index, not wall-clock seconds, so it is
            # labelled as a sample count rather than claiming a time unit. Mouse
            # panning stays locked in both directions: these are live safety
            # traces and an operator must not be able to scroll one away from
            # the range its own data occupies.
            style_plot(
                plot, title=title, y_label=y_label, x_label="Sample",
                mouse_x=False, mouse_y=False,
            )

        # Series colours. Temperature takes ALARM because it is the only channel
        # with a trip limit this display must make unmissable (80 °C envelope),
        # so it must be the trace an operator finds first. ACCENT and RESTRICTED
        # were rejected: they sit within a few degrees of hue of WARN on the
        # current trace and the two would be indistinguishable at a glance,
        # which is exactly the confusion the palette tokens exist to prevent.
        self.speed_curve = _make_step_curve(self.speed_plot, BLUE)
        self.current_curve = _make_step_curve(self.current_plot, WARN)
        self.temp_curve = _make_step_curve(self.temp_plot, ALARM)
        self.box_curve = _make_step_curve(self.box_plot, VIOLET)

        # No translucent under-curve fill on any plot. A 25%-alpha wash greyed
        # out the grid it was drawn over and softened the foot of the line, and
        # it carried no information the step line did not already carry. On a
        # safety display the trace has to dominate; the fill was decoration
        # competing with the one thing the operator is looking for.

        charts_layout.addWidget(self.stream_fig)
        layout.addWidget(charts_frame, 1)

        # Anomaly injection control
        anomaly_frame = QFrame()
        anomaly_frame.setObjectName("anomaly_panel")
        anomaly_frame.setFrameShape(QFrame.Shape.NoFrame)
        anomaly_frame.setStyleSheet(_flat_panel("anomaly_panel"))
        anomaly_layout = QHBoxLayout(anomaly_frame)
        anomaly_layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        anomaly_layout.addWidget(QLabel("Anomaly Injection:"))
        self.anomaly_type = QComboBox()
        self.anomaly_type.addItems(["Belt Jam (High Current)", "Bearing Failure (High Temp)", "Belt Slip (Speed Drop)", "Motor Overload"])
        anomaly_layout.addWidget(self.anomaly_type)

        inject_btn = QPushButton("INJECT ANOMALY")
        inject_btn.setProperty("action", "danger")
        inject_btn.clicked.connect(self._inject_anomaly)
        anomaly_layout.addWidget(inject_btn)
        anomaly_layout.addStretch()
        layout.addWidget(anomaly_frame)

        # Initialize streamer
        self._streamer = None
        self._stream_mode = False
        self._stream_history: List[Dict] = []
        self._stream_max_points = 60

        # Timer for UI updates. The cadence is the configured stream refresh
        # rather than a literal: the old 500 ms repainted four times per
        # configured period, and since samples only arrive every
        # TELEMETRY_INTERVAL (5 s) nearly all of those repaints redrew an
        # identical trace. Reading the interval from config keeps the redraw rate
        # tunable in one place for the whole app.
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self._update_stream_ui)
        self.ui_timer.start(app_config.timeouts.get_stream_refresh_interval())

    def _set_stream_button_action(self, action: str) -> None:
        """
        Move the stream button between the theme's primary and danger actions.

        Qt only re-evaluates a dynamic property after the widget is unpolished,
        so without the repolish the button keeps the colours of the state it had
        when the tab was built. A stopped stream that still looks like a running
        one is exactly the wrong default to be wrong about, so the repolish is
        load-bearing and not decoration.
        """
        self.stream_btn.setProperty("action", action)
        self.stream_btn.style().unpolish(self.stream_btn)
        self.stream_btn.style().polish(self.stream_btn)

    def _toggle_stream(self):
        if not self._stream_mode:
            self._start_stream()
        else:
            self._stop_stream()

    def closeEvent(self, event):
        """Guarantee the streamer thread is gone before the widget is destroyed."""
        self.ui_timer.stop()
        try:
            if self._stream_mode:
                self._stop_stream()
            elif self._streamer is not None:
                self._streamer.request_stop()
                if not self._streamer.stop():
                    self._streamer.wait(10000)
                if not self._streamer.isRunning():
                    self._streamer = None
        except Exception:  # pragma: no cover - defensive
            pass
        super().closeEvent(event)
    
    def _start_stream(self):
        from hardware_telemetry import get_global_telemetry
        # Never abandon a previous thread before it has actually stopped.
        if self._streamer is not None:
            if not self._streamer.stop():
                self._streamer.wait(5000)

        speed = self.stream_speed_spin.value()
        period = max(0.5, self.stream_period_spin.value())

        streamer = TelemetryStreamer(get_global_telemetry())
        # Connect BEFORE starting, otherwise the first samples are emitted with
        # no receiver attached and are silently dropped.
        streamer.tick.connect(self._on_stream_tick)
        streamer.failed.connect(self._on_stream_failed)
        streamer.set_setpoint(speed)
        streamer.start_streaming(set_speed_rpm=speed, period=period)

        self._streamer = streamer
        self._stream_mode = True
        self.stream_btn.setText("  STOP STREAM  ")
        self._set_stream_button_action("danger")

    def _stop_stream(self):
        streamer = self._streamer
        self._stream_mode = False
        if streamer is not None:
            streamer.request_stop()
            if not streamer.stop():
                # Still busy: block until it is genuinely finished. Dropping the
                # reference here would destroy a running QThread and abort.
                streamer.wait(10000)
            streamer.tick.disconnect(self._on_stream_tick)
            try:
                streamer.failed.disconnect(self._on_stream_failed)
            except (RuntimeError, TypeError):
                pass
            if not streamer.isRunning():
                self._streamer = None

        self.stream_btn.setText("  START STREAM  ")
        self._set_stream_button_action("primary")

    def _on_stream_failed(self, message: str):
        """Surface a telemetry backend error without tearing down the UI."""
        self.status_lbl.setText(f"TELEMETRY ERROR: {message}")
    
    def _on_anomaly_toggle(self, state):
        if self._streamer:
            self._streamer.inject_anomaly(state == Qt.CheckState.Checked.value)
    
    def _inject_anomaly(self):
        if not self._streamer:
            return
        
        anomaly_type = self.anomaly_type.currentText()
        
        if "Belt Jam" in anomaly_type:
            anomaly = Trajectory(
                conveyor_state='RUNNING',
                motor_speed_rpm=200.0,
                motor_current_amps=25.0,
                temperature_c=90.0,
                box_rate_per_min=5.0
            )
        elif "Bearing" in anomaly_type:
            anomaly = Trajectory(
                conveyor_state='RUNNING',
                motor_speed_rpm=500.0,
                motor_current_amps=8.0,
                temperature_c=95.0,
                box_rate_per_min=20.0
            )
        elif "Slip" in anomaly_type:
            anomaly = Trajectory(
                conveyor_state='RUNNING',
                motor_speed_rpm=200.0,
                motor_current_amps=4.0,
                temperature_c=40.0,
                box_rate_per_min=5.0
            )
        else:  # Motor Overload
            anomaly = Trajectory(
                conveyor_state='RUNNING',
                motor_speed_rpm=500.0,
                motor_current_amps=20.0,
                temperature_c=80.0,
                box_rate_per_min=20.0
            )
        
        self._streamer.set_anomaly_data(anomaly)
        self._streamer.inject_anomaly(True)
    
    @Slot(dict)
    def _on_stream_tick(self, data: dict):
        """Called from streamer thread on each tick"""
        self._stream_history.append(data)
        if len(self._stream_history) > self._stream_max_points:
            self._stream_history = self._stream_history[-self._stream_max_points:]
    
    def _update_stream_ui(self):
        if not self._stream_history:
            return

        latest = self._stream_history[-1]

        # Update readouts
        for key, label in self.stream_labels.items():
            val = latest.get(key, "—")
            if key == "anomaly":
                label.setText("YES" if val else "NO")
                # Only the colour differs between the two states. setStyleSheet
                # REPLACES the widget's previous sheet, so this has to go through
                # the same builder _init_ui used; re-declaring just `color` here
                # used to drop font-family, the 17px size and the 700 weight,
                # silently collapsing this cell to 10px body text on every tick.
                label.setStyleSheet(_readout_value_style(ALARM if val else OK))
            elif isinstance(val, float):
                label.setText(f"{val:.1f}")
            else:
                label.setText(str(val))

        # Update charts
        history = self._stream_history
        xs = list(range(len(history)))

        speeds = [d.get("motor_speed_rpm", 0) for d in history]
        currents = [d.get("motor_current_amps", 0) for d in history]
        temps = [d.get("temperature_c", 0) for d in history]
        boxes = [d.get("box_rate_per_min", 0) for d in history]

        for curve, values in (
            (self.speed_curve, speeds),
            (self.current_curve, currents),
            (self.temp_curve, temps),
            (self.box_curve, boxes),
        ):
            # The step/connect/antialias contract is restated on every update
            # rather than only at build time. setData() merges its keyword
            # arguments into the item's options, so the build-time values would
            # survive today — but a trace contract that lives in one call and is
            # silently inherited by another is one refactor away from coming
            # back as a smoothed diagonal line.
            curve.setData(
                xs, values,
                stepMode="right", connect="finite", antialias=False,
            )

        self._fit_plot_ranges((
            (self.speed_plot, speeds),
            (self.current_plot, currents),
            (self.temp_plot, temps),
            (self.box_plot, boxes),
        ))

    def _fit_plot_ranges(self, series) -> None:
        """
        Re-derive every plot's X/Y range from the data actually on it.

        SAFETY: this is the fix for a range that could hide an excursion. The
        old code called enableAutoRange('xy', False) on every tick and never
        issued setXRange/setYRange, so each plot kept whatever window its very
        first auto-range produced, and mouse panning was locked, so the operator
        could not scroll back either. An injected over-temperature anomaly
        (95 °C, against an 80 °C envelope) was therefore plotted outside the
        frozen window and simply invisible — the readout said YES while the
        trace said nothing, which is the worst possible failure on a safety
        display. Deriving the range from the live data on every refresh is the
        only way a locked plot cannot hide a transient, and it costs a min/max
        over at most 60 points per plot.

        Auto-range is disabled explicitly rather than left on: pyqtgraph's
        auto-range only fits the data extent with no headroom, which puts the
        newest step exactly on the top frame line where it is least readable.
        The X window is a fixed sweep of _stream_max_points samples so the axis
        ticks do not re-scale on every tick.
        """
        window = max(2, self._stream_max_points)
        for plot, values in series:
            low, high = _value_window(values)
            plot.enableAutoRange(x=False, y=False)
            plot.setXRange(0, window - 1, padding=0)
            plot.setYRange(low, high, padding=0)
    
# Evidence detail dialog
class EvidenceDetailDialog(QDialog):
    """Forensic detail dialog for evidence records"""

    def __init__(self, parent, record: Dict):
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("Forensic Evidence Detail")
        # 760, not 700: this dialog's own minimumSizeHint().height() is 742, so
        # a 700px hard minimum put the window 42px BELOW its layout minimum.
        # Qt then squeezed the forensic content into less room than it needs -
        # the CHAIN INTEGRITY grid rows landed at 9px against the 14px their
        # labels require, and the Base64 signature label got 9px against a 32px
        # hint, i.e. 23px of a signature was never painted. A hard minimum below
        # the layout minimum is the one way to make a dialog lie about its
        # contents, so the minimum has to sit above it.
        self.setMinimumSize(900, 760)
        # No dialog-level stylesheet. The old one installed a complete second
        # legacy palette (its own body, rule and header greys) which overrode the
        # application theme for this whole subtree, rounded every group box by
        # 6px, and left the values in a proportional face. A dialog must read as
        # part of the same instrument as the tab that opened it, so the app theme
        # styles it and only genuinely local rules appear below.

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        layout.setSpacing(GAP)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("FORENSIC EVIDENCE DETAIL")
        title.setProperty("role", "title")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # The theme already makes a scroll area borderless and transparent;
        # repeating it here would only add a second rule that can disagree.
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(GAP)
        content_layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)

        # Identity section
        identity_group = QGroupBox("IDENTITY & AUTHORIZATION")
        ident_layout = QGridLayout(identity_group)
        ident_layout.setSpacing(GAP)
        
        fields = [
            ("Event ID", "event_id"),
            ("Timestamp", "timestamp"),
            ("User", "user"),
            ("Roles", "roles"),
            ("MFA Verified", "mfa_verified"),
            ("Supervisor", "supervisor_approved"),
            ("Device FP", "device_fingerprint"),
            ("Token JTI", "token_jti"),
            ("Dual Control", "dual_control_satisfied"),
        ]
        
        for i, (label, key) in enumerate(fields):
            label_widget = QLabel(label + ":")
            apply_label(label_widget, size=9, color=TEXT_DIM, bold=True)
            value = self.record.get(key, "—")
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            elif isinstance(value, bool):
                value = "YES" if value else "NO"
            elif key == "timestamp":
                value = str(value)[:26]
            value_widget = QLabel(str(value))
            # Timestamps, ids and signatures are the columns an operator copies
            # out of this dialog, so they get the fixed digit advance rather
            # than the UI face.
            value_widget.setStyleSheet(_value_label_style())
            value_widget.setFont(_mono_pixel_font(9))
            # No word wrap: every value here is pre-truncated to a length that
            # fits one line at the dialog's width, so the wrapped sizeHint only
            # inflated this dialog's minimum height and pushed the layout into
            # squeezing rows it had already paid for.
            ident_layout.addWidget(label_widget, i // 2, (i % 2) * 2)
            ident_layout.addWidget(value_widget, i // 2, (i % 2) * 2 + 1)

        # Command section
        cmd_group = QGroupBox("COMMAND DETAILS")
        cmd_layout = QGridLayout(cmd_group)
        cmd_layout.setSpacing(GAP)

        cmd_fields = [
            ("Command", "command"),
            ("Subsystem", "subsystem"),
            ("Previous State", "previous_state"),
            ("New State", "new_state"),
            ("Risk Score", "risk_score"),
            ("Risk Level", "risk_level"),
            ("Final Decision", "final_decision"),
            ("Rejection Reason", "rejection_reason"),
        ]

        for i, (label, key) in enumerate(cmd_fields):
            label_widget = QLabel(label + ":")
            apply_label(label_widget, size=9, color=TEXT_DIM, bold=True)
            value = self.record.get(key, "—")
            value_widget = QLabel(str(value))
            value_widget.setStyleSheet(_value_label_style())
            value_widget.setFont(_mono_pixel_font(9))
            # No word wrap, same reason as the identity grid above.
            cmd_layout.addWidget(label_widget, i // 2, (i % 2) * 2)
            cmd_layout.addWidget(value_widget, i // 2, (i % 2) * 2 + 1)

        # Trajectories section
        traj_group = QGroupBox("TRAJECTORY COMPARISON")
        traj_layout = QVBoxLayout(traj_group)

        traj_table = QTableWidget()
        traj_table.setColumnCount(5)
        traj_table.setHorizontalHeaderLabels(["Parameter", "Predicted", "Observed", "Delta", "Status"])
        traj_table.horizontalHeader().setStretchLastSection(True)
        # style_table() owns the 1px grid, the row height, the hidden vertical
        # header and the monospace face. The old per-widget sheet replaced the
        # app rules for this subtree, which cost the table its 1px outer frame
        # and its cell padding and left Predicted/Observed/Delta ("85.00 (20.0%)")
        # in a proportional font — a numeric column whose digits re-flow.
        style_table(traj_table)
        # The family is named in a sheet as well, for the same reason as
        # _value_label_style(): the application sheet's generic QWidget
        # font-family rule wins over the setFont() inside style_table() at polish
        # time, which would leave Predicted/Observed/Delta proportional.
        traj_table.setStyleSheet(
            "QTableWidget, QTableView {"
            f" font-family: '{resolve_mono_family()}'; font-size: 9px; }}"
        )
        
        traj_fields = [
            ("Conveyor State", "conveyor_state", ""),
            ("Motor Speed (RPM)", "motor_speed_rpm", "RPM"),
            ("Motor Current (A)", "motor_current_amps", "A"),
            ("Temperature (°C)", "temperature_c", "°C"),
            ("Box Rate (/min)", "box_rate_per_min", "/min"),
        ]
        
        traj_table.setRowCount(len(traj_fields))
        
        for i, (label, key, unit) in enumerate(traj_fields):
            pred_val = self.record.get("predicted_trajectory", {}).get(key, "—")
            obs_val = self.record.get("observed_trajectory", {}).get(key, "—")
            
            traj_table.setItem(i, 0, _mono_cell(label))
            traj_table.setItem(i, 1, _mono_cell(f"{pred_val} {unit}"))
            traj_table.setItem(i, 2, _mono_cell(f"{obs_val} {unit}"))

            # Delta
            try:
                if pred_val != "—" and obs_val != "—":
                    p = float(str(pred_val).replace(',', ''))
                    o = float(str(obs_val).replace(',', ''))
                    delta = abs(o - p)
                    pct = (delta / max(abs(p), 1)) * 100
                    traj_table.setItem(i, 3, _mono_cell(f"{delta:.2f} ({pct:.1f}%)"))

                    if pct > 20:
                        status = "⚠ DEVIATION"
                        color = ALARM
                    elif pct > 10:
                        status = "⚠ WARNING"
                        color = WARN
                    else:
                        status = "✓ OK"
                        color = OK
                    status_item = _mono_cell(status)
                    status_item.setForeground(QColor(color))
                    traj_table.setItem(i, 4, status_item)
                else:
                    traj_table.setItem(i, 3, _mono_cell("—"))
                    traj_table.setItem(i, 4, _mono_cell("—"))
            except (ValueError, TypeError):
                traj_table.setItem(i, 3, _mono_cell("—"))
                traj_table.setItem(i, 4, _mono_cell("—"))

        traj_table.verticalHeader().setVisible(False)
        traj_layout.addWidget(traj_table)

        # XAI Explanation
        xai_group = QGroupBox("CAUSAL EXPLANATION (XAI)")
        xai_layout = QVBoxLayout(xai_group)
        xai_text = QTextEdit()
        xai_text.setReadOnly(True)
        _mono_text_area(xai_text, 12)
        xai_text.setPlainText(self.record.get("xai_explanation", "No explanation available"))
        xai_layout.addWidget(xai_text)

        # Risk factors
        risk_group = QGroupBox("RISK FACTORS")
        risk_layout = QVBoxLayout(risk_group)
        risk_text = QTextEdit()
        risk_text.setReadOnly(True)
        risk_text.setMaximumHeight(120)
        # Style and font go in BEFORE setHtml(): a rich-text document takes its
        # default character format from the widget font, so this is what makes
        # "Overall Risk Score: 85.0" monospaced rather than proportional.
        _mono_text_area(risk_text, 11)

        risk_score = self.record.get("risk_score", 0)
        risk_level = self.record.get("risk_level", "LOW")
        safety_violations = self.record.get("safety_violations", [])
        
        risk_html = f"""
        <b>Overall Risk Score:</b> {risk_score:.1f} ({risk_level})<br/>
        <b>Safety Violations:</b> {len(safety_violations)}<br/>
        """
        if safety_violations:
            for v in safety_violations:
                risk_html += f"• {v}<br/>"
        
        risk_text.setHtml(risk_html)
        risk_layout.addWidget(risk_text)
        
        # Hash chain
        hash_group = QGroupBox("CHAIN INTEGRITY")
        hash_layout = QGridLayout(hash_group)
        
        hash_fields = [
            ("Event ID", "event_id"),
            ("Previous Hash", "previous_record_hash"),
            ("Chain Hash", "chain_hash"),
            ("Signature", "signature"),
            ("Key ID", "key_id"),
        ]
        
        for i, (label, key) in enumerate([
            ("Event ID", "event_id"),
            ("Previous Hash", "previous_record_hash"),
            ("Chain Hash", "chain_hash"),
            ("Signature", "signature"),
            ("Key ID", "key_id"),
        ]):
            label_widget = QLabel(label + ":")
            apply_label(label_widget, size=9, color=TEXT_DIM, bold=True)
            value = str(self.record.get(key, "—"))[:64] + ("..." if len(str(self.record.get(key, ""))) > 64 else "")
            value_widget = QLabel(value)
            # Hashes are compared character by character, so they must not be
            # rendered in a face where similar glyphs differ by width.
            value_widget.setStyleSheet(_value_label_style())
            value_widget.setFont(_mono_pixel_font(9))
            # No word wrap: a hash is 64 hex characters, already clipped to 64
            # here, and a wrapped hint made the signature label demand 32px of
            # height for text that occupies one line.
            hash_layout.addWidget(label_widget, i, 0)
            hash_layout.addWidget(value_widget, i, 1)

        # Layout assembly
        layout.addWidget(identity_group)
        layout.addWidget(cmd_group)
        layout.addWidget(traj_group)
        layout.addWidget(xai_group)
        layout.addWidget(risk_group)
        layout.addWidget(hash_group)
        layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addStretch()
        close_btn = QPushButton("CLOSE")
        close_btn.setMinimumWidth(96)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
