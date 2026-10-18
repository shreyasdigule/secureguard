"""
SecureGuard Governance Model - PySide6 Dashboard (Charts Tab)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFrame, QGridLayout
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
import pyqtgraph as pg
import numpy as np
from datetime import datetime
from typing import Dict, List
import time
from config import app_config
# Chart appearance is delegated to the design system instead of being hand-rolled
# here. The theme owns colour, density and the monospace telemetry face, so a
# panel that styles its own plot is a panel that will drift away from the rest of
# the app the first time a token changes.
from industrial_theme import (
    BG_INSET, BG_PANEL, BORDER, BORDER_HI, TEXT, TEXT_DIM, ACCENT, OK, WARN,
    VIOLET, ROSE, SERIES, FONT_UI, FONT_DISPLAY, BORDER_W, PAD_X, PAD_Y, GAP,
    LABEL_PT, style_plot, trace_pen,
)


# Samples held in the visible X window. At the 5 s sampling cadence this is
# exactly the five minutes the "Last 5 min" range selector offers, so the default
# view and the default range agree instead of the window silently showing a
# fraction of the selected range.
VISIBLE_SAMPLE_WINDOW = 60

# History points retained per subsystem. Bounded rather than trimmed to the
# window so panning back inside a longer range still has data to draw.
MAX_HISTORY_POINTS = 100


class ChartsTab(QWidget):
    """Trend charts tab with pyqtgraph real-time plotting"""
    
    def __init__(self, parent=None):
        super().__init__()
        self._max_points = MAX_HISTORY_POINTS
        self.current_subsystem = "All"
        # Populated by SecureGuardDashboard.refresh_charts() from the shared
        # pipeline. Charts are driven by the dashboard's single pipeline rather
        # than a second one so command history and charts never disagree.
        self.command_history: Dict[str, List[Dict]] = {}
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        # Same gutter as Overview / Evidence / Live Stream. This tab used the
        # tighter GAP margin, so switching tabs shifted every panel 4px sideways
        # and the charts' own left border sat 4px right of every other tab's.
        layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        layout.setSpacing(GAP)
        
        # Header
        header = QHBoxLayout()
        header.setSpacing(GAP)
        title = QLabel("TREND CHARTS")
        title.setStyleSheet(f"font-family: '{FONT_DISPLAY}'; font-size: 15px; font-weight: 700; letter-spacing: 3px; color: {TEXT}; background: transparent;")
        header.addWidget(title)
        header.addStretch()
        
        # Subsystem selector
        self.chart_subsystem = QComboBox()
        self.chart_subsystem.addItems(["All", "Conveyor_Motor_01", "Conveyor_Motor_02", "Conveyor_Motor_03"])
        self.chart_subsystem.setFixedWidth(200)
        self.chart_subsystem.currentTextChanged.connect(self._on_subsystem_changed)
        header.addWidget(QLabel("Subsystem:"))
        header.addWidget(self.chart_subsystem)
        
        # Time range
        self.time_range = QComboBox()
        self.time_range.addItems(["Last 5 min", "Last 15 min", "Last hour", "All"])
        self.time_range.setCurrentIndex(1)
        self.time_range.currentTextChanged.connect(self._on_time_range_changed)
        header.addWidget(QLabel("Range:"))
        header.addWidget(self.time_range)
        
        header.addStretch()
        layout.addLayout(header)
        
        # Charts area
        self.charts_container = QWidget()
        charts_layout = QGridLayout(self.charts_container)
        # Zero margin, because this layout is nested inside a container that is
        # already padded by the tab layout above. Qt's 9px default here was a
        # second inset nobody asked for: it put the chart panels' outer border
        # 9px right of this tab's own title text and 9px right of the gutter
        # every other tab uses, while the 4px between the panels stayed 4.
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(GAP)
        layout.addWidget(self.charts_container, 1)
        
        # Create five chart widgets. There is no colour argument any more: every
        # curve colour comes from series_defs / SERIES in refresh_charts(), so
        # the Material hexes this used to carry were never rendered.
        self.risk_chart = self._create_chart("Risk Score", "Risk Score")
        self.current_chart = self._create_chart("Motor Current", "Current (A)")
        self.speed_chart = self._create_chart("Motor Speed", "Speed (RPM)")
        self.temp_chart = self._create_chart("Temperature", "Temp (°C)")
        self.box_chart = self._create_chart("Box Rate", "Boxes/min")
        
        # Ordered handle on the frames. The named attributes above stay the
        # access path the dashboard uses; this list is what lets a verification
        # run (or a future exporter) walk every panel without string lookups.
        self.frames = [
            self.risk_chart, self.current_chart, self.speed_chart,
            self.temp_chart, self.box_chart,
        ]
        for i, chart in enumerate(self.frames):
            row, col = divmod(i, 3)
            charts_layout.addWidget(chart, row, col)
        # Equal stretch on every column and row. Without it the grid sized each
        # panel to its own sizeHint and left the remainder to the last one, so
        # the three columns came out 521 / 522 / 521 - a 1px step in the borders
        # that runs straight down the middle of the tab.
        for col in range(3):
            charts_layout.setColumnStretch(col, 1)
        for row in range(2):
            charts_layout.setRowStretch(row, 1)
        
        # Chart visual-refresh cadence (ms). This is the repaint, NOT the sampling:
        # the dashboard appends one point per conveyor every 5 s (its subsystem
        # tick) and hands the accumulated history over, and this timer is what
        # decides how often those points are actually redrawn. The two are
        # deliberately far apart - a repaint per sample would redraw five plots
        # three times per trace step at 5 s cadence - and the interval is read
        # from config so one token (SG_CHART_REFRESH_MS) tunes the whole app.
        self.chart_refresh_interval_ms = app_config.timeouts.get_chart_refresh_interval()
        self.chart_refresh_timer = QTimer()
        self.chart_refresh_timer.timeout.connect(self.refresh_charts)
        self.chart_refresh_timer.start(self.chart_refresh_interval_ms)
    
    def _create_chart(self, title: str, y_label: str):
        """Create a pyqtgraph plot widget"""
        frame = QFrame()
        # Shape.Box only. Asking for Qt's raised bevel as well painted the native
        # 3D frame *under* the stylesheet border, so every chart panel showed a
        # doubled edge.
        frame.setFrameShape(QFrame.Shape.Box)
        frame.setStyleSheet(
            "QFrame {"
            f" background-color: {BG_PANEL};"
            f" border: {BORDER_W}px solid {BORDER};"
            "}"
            "QFrame:hover {"
            f" border: {BORDER_W}px solid {BORDER_HI};"
            "}"
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        layout.setSpacing(GAP)

        # Title
        title_lbl = QLabel(title)
        # Caption treatment kept, but the face is pinned to the UI font instead
        # of inheriting whatever the plot's monospace ticks want, and the
        # padding is zeroed so five captions do not cost a millimetre of
        # chart height each.
        title_lbl.setStyleSheet(
            f"font-family: '{FONT_UI}'; font-size: {LABEL_PT}px; font-weight: 700;"
            f" letter-spacing: 1px; color: {TEXT_DIM}; background: transparent; padding: 0;"
        )
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Plot widget. Every axis, grid and tick decision is delegated to the
        # shared style_plot() so this file cannot drift from the other tabs:
        # it also supplies the monospace 8pt tick fonts that stop axis digits
        # jittering as values change width. style_plot is not given the caption
        # text: pyqtgraph's in-plot title is roomy and would eat chart height
        # that the dense header strip above already spends well.
        plot = pg.PlotWidget()
        style_plot(
            plot,
            y_label=y_label,
            x_label="Sample",
            mouse_x=True,
            mouse_y=False,
        )

        # The legend has to exist before the first plot() call: PlotItem.addItem
        # only registers a curve when self.legend is already set, so adding it
        # later (as this file used to, after refresh_charts had already run)
        # produced a legend with no entries at all. addLegend returns the
        # existing legend instead of raising, so there is nothing to catch.
        plot.addLegend(
            offset=(-10, 12),
            pen=pg.mkPen(BORDER_HI, width=1),
            brush=pg.mkBrush(BG_INSET),
            labelTextColor=TEXT_DIM,
            labelTextSize="8pt",
        )

        # Curves are created on demand by _update_chart, because "All" plots one
        # curve per subsystem rather than a single flattened trace.
        layout.addWidget(title_lbl)
        layout.addWidget(plot)

        frame.setLayout(layout)

        # Store references. Only plot and curves are live: curve/data_x/data_y/
        # color were written once here and never read anywhere in the app.
        frame.plot = plot
        frame.curves = {}
        
        return frame
    
    def _on_subsystem_changed(self, subsystem: str):
        self.current_subsystem = subsystem
        self.refresh_charts()
    
    def _on_time_range_changed(self, range_text: str):
        self.refresh_charts()

    def refresh_charts(self):
        """
        Redraw every chart from the dashboard's shared history.

        "All" plots one curve per subsystem. Flattening every subsystem into a
        single trace interleaved running and idle motors, which produced a
        528 -> 0 sawtooth that looked like a sensor fault.
        """
        subsystem = self.chart_subsystem.currentText()

        if subsystem == "All":
            groups = {
                name: list(entries)
                for name, entries in self.command_history.items()
                if entries
            }
        else:
            groups = {subsystem: list(self.command_history.get(subsystem, []))}

        if not groups:
            return

        # Filter by time range
        range_text = self.time_range.currentText()
        if "5 min" in range_text:
            window = 300
        elif "15 min" in range_text:
            window = 900
        elif "1 hour" in range_text:
            window = 3600
        else:
            window = None

        now = time.time()
        # Single-subsystem mode: colour means CHANNEL identity, so temperature
        # takes ROSE (the flat series token) rather than a state colour. It is a
        # subsystem reading a motor's temperature here, not a channel that has
        # tripped, and the 80 °C envelope that makes temperature alarming belongs
        # to the evidence tab, which owns it. In "All" mode the eight SERIES
        # colours are assigned by subsystem, so temperature-as-a-subsystem must
        # not inherit a state colour there either.
        series_defs = (
            ("risk_chart", "risk_score", ACCENT),
            ("current_chart", "motor_current_amps", WARN),
            ("speed_chart", "motor_speed_rpm", OK),
            ("temp_chart", "temperature_c", ROSE),
            ("box_chart", "box_rate_per_min", VIOLET),
        )

        for frame_name, key, base_color in series_defs:
            frame = getattr(self, frame_name)
            per_series = []
            for index, (name, entries) in enumerate(sorted(groups.items())):
                if window is not None:
                    entries = [e for e in entries if e.get("timestamp", 0) >= now - window]
                if not entries:
                    continue
                entries.sort(key=lambda x: x.get("timestamp", 0))
                color = base_color if subsystem != "All" else SERIES[index % len(SERIES)]
                per_series.append((name, list(range(len(entries))), self._series(entries, key), color))
            if per_series:
                self._update_chart(frame, per_series)

    def _series(self, records: List[Dict], key: str) -> List[float]:
        """
        Extract one plotted series, carrying the last known value forward.

        Live telemetry samples carry ``risk_score: None`` because risk is only
        produced by command assessment. A plain ``dict.get(key, 0)`` would plot
        a misleading zero spike for every sample, because the key is present
        but empty.
        """
        values: List[float] = []
        last = 0.0
        for record in records:
            value = record.get(key)
            if value is None:
                values.append(last)
                continue
            last = float(value)
            values.append(last)
        return values

    def closeEvent(self, event):
        """Stop the refresh timer so no callback fires during teardown."""
        self.chart_refresh_timer.stop()
        super().closeEvent(event)

    def _update_chart(self, chart_frame, per_series):
        """
        Update a chart with one or more named series.

        ``per_series`` is a list of ``(name, x_values, y_values, color)``. Curves
        are created on demand and reused, and extras are hidden rather than
        destroyed so the plot does not churn items on every refresh.
        """
        plot = chart_frame.plot
        curves = getattr(chart_frame, "curves", None)
        if curves is None:
            curves = {}
            chart_frame.curves = curves

        wanted = {name for name, _, _, _ in per_series}
        for name, curve in list(curves.items()):
            if name not in wanted:
                curve.clear()
                curve.setVisible(False)
        if not per_series:
            plot.enableAutoRange('xy', True)
            return

        y_min = y_max = None
        for name, x_vals, y_vals, color in per_series:
            x_list = list(x_vals)
            y_list = list(y_vals)
            curve = curves.get(name)
            if curve is None:
                # stepMode="right" draws a right-angle staircase between
                # discrete samples. Without it pyqtgraph joins points with
                # diagonals, which invents intermediate values the machine
                # never reported - the single most misleading thing a trend
                # chart can do. connect="finite" keeps gaps as gaps instead of
                # interpolating across them.
                curve = plot.plot(
                    pen=trace_pen(color),
                    name=name,
                    stepMode="right",
                    connect="finite",
                    antialias=False,
                )
                curves[name] = curve
                # Clickable points would let a stray click clear a live trace.
                curve.setCurveClickable(False)
                # Both of these are render-path dependent rather than static
                # settings, so they are pinned explicitly: neither
                # downsampling nor clip-to-view may be allowed to minify
                # discrete telemetry samples into a smoothed line if a future
                # pyqtgraph default changes.
                curve.setDownsampling(1, False, "peak")
                curve.setClipToView(False)
            else:
                curve.setPen(trace_pen(color))
            # Restated on every update so the step / finite-connect contract is
            # enforced at the draw call, not only where the curve was built.
            curve.setData(
                x_list,
                y_list,
                stepMode="right",
                connect="finite",
                antialias=False,
            )
            curve.setVisible(True)
            if y_list:
                lo, hi = min(y_list), max(y_list)
                y_min = lo if y_min is None else min(y_min, lo)
                y_max = hi if y_max is None else max(y_max, hi)

        span = max(len(x) for _, x, _, _ in per_series)
        plot.enableAutoRange('xy', False)
        plot.setXRange(max(0, span - VISIBLE_SAMPLE_WINDOW), span)
        if y_min is not None:
            if y_min == y_max:
                y_min -= 1.0
                y_max += 1.0
            plot.setYRange(y_min * 0.92, y_max * 1.08)

        # No legend bookkeeping here: _create_chart attaches the legend before
        # any curve exists, so PlotItem.addItem registers each named trace as it
        # is plotted. Calling addLegend after the fact registered nothing.


# Quick test for the charts tab
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    from industrial_theme import apply_theme, apply_plot_theme
    
    # Same bootstrap as dashboard_qt: without it this window picks up default
    # Windows chrome and the charts render against the wrong background.
    app = QApplication(sys.argv)
    apply_theme(app)
    apply_plot_theme(pg)
    chart_tab = ChartsTab()
    chart_tab.show()
    sys.exit(app.exec())