"""
config.py â€” Central configuration for SecureGuard placeholders
DEVELOPMENT PLACEHOLDERS ONLY. To be replaced with real specs from Person 1.
"""
from dataclasses import dataclass, field
from typing import Dict
import os


def _env_float(name: str, default: float) -> float:
    """Read a float override, falling back to ``default`` on bad input.

    These are dataclass field defaults, evaluated at import time, and this
    module is imported by nearly every other one. A bare ``float()`` call meant
    a single typo such as ``SG_PIPELINE_TIMEOUT=900s`` aborted startup with a
    ValueError instead of falling back to a working configuration.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    """Integer counterpart of :func:`_env_float`."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


@dataclass
class TimeoutConfig:
    """Dynamic timeout configuration for slow computations and long-running tasks."""
    # Pipeline command processing timeout (seconds)
    # Generous by default: physics twin + risk + XAI can be slow on loaded hosts,
    # and an idle upstream connection is worse than a slow response.
    pipeline_command_timeout: float = _env_float("SG_PIPELINE_TIMEOUT", 900.0)

    # Telemetry streaming timeout (seconds)
    telemetry_stream_timeout: float = _env_float("SG_TELEMETRY_TIMEOUT", 300.0)

    # 3D animation frame rate (fps). 30 fps is a 33 ms frame budget. This is the
    # single source of truth for the animation cadence; the frame interval is
    # derived from it rather than typed in twice. It is deliberately the ONLY 3D
    # timing knob: the belt's travel rate is calibrated in qt_view3d against a
    # fixed historical 33 ms point, so changing the FPS changes how smoothly the
    # belt is drawn and nothing about how fast it appears to move.
    view3d_fps: float = _env_float("SG_VIEW3D_FPS", 30.0)

    # Chart refresh interval (ms) - the visual repaint of the trend plots.
    # History is appended on the much faster subsystem tick; this is only how
    # often the accumulated history is redrawn.
    chart_refresh_interval_ms: int = _env_int("SG_CHART_REFRESH_MS", 30000)

    # Live stream refresh interval (ms)
    stream_refresh_interval_ms: int = _env_int("SG_STREAM_REFRESH_MS", 2000)

    # Heartbeat interval (ms)
    heartbeat_interval_ms: int = _env_int("SG_HEARTBEAT_MS", 1000)

    # Clock update interval (ms)
    clock_interval_ms: int = _env_int("SG_CLOCK_MS", 1000)

    # Telemetry sample period in seconds (drives TelemetryStreamer cadence)
    telemetry_sample_period_s: float = _env_float("SG_TELEMETRY_PERIOD_S", 5.0)

    # Subsystem telemetry poll / overview UI update (ms). This is the dashboard's
    # 5 s tick: it acquires a sample per conveyor, updates the tiles, the risk
    # gauge and the command form, and appends one point per conveyor to the trend
    # history. It does NOT repaint the charts (see chart_refresh_interval_ms).
    subsystem_refresh_interval_ms: int = _env_int("SG_SUBSYSTEM_REFRESH_MS", 5000)
    
    # PyInstaller build timeout (seconds)
    build_timeout: float = _env_float("SG_BUILD_TIMEOUT", 300.0)
    
    # API request timeout (seconds)
    api_request_timeout: float = _env_float("SG_API_TIMEOUT", 30.0)
    
    # Database operation timeout (seconds)
    db_operation_timeout: float = _env_float("SG_DB_TIMEOUT", 10.0)
    
    # Evidence log write timeout (seconds)
    evidence_write_timeout: float = _env_float("SG_EVIDENCE_WRITE_TIMEOUT", 5.0)
    
    # Hardware telemetry health check timeout (seconds)
    hardware_health_check_timeout: float = _env_float("SG_HARDWARE_HEALTH_TIMEOUT", 5.0)
    
    # Dynamic scaling factor for slow environments (1.0 = normal, 2.0 = 2x slower)
    slow_environment_factor: float = _env_float("SG_SLOW_FACTOR", 1.0)
    
    def scaled(self, base_timeout: float) -> float:
        """Apply slow environment scaling factor to a timeout."""
        return base_timeout * self.slow_environment_factor
    
    def get_pipeline_timeout(self) -> float:
        return self.scaled(self.pipeline_command_timeout)
    
    def get_telemetry_timeout(self) -> float:
        return self.scaled(self.telemetry_stream_timeout)
    
    def get_subsystem_refresh_interval(self) -> int:
        """Telemetry sample + overview UI update cadence, in milliseconds."""
        return int(self.scaled(self.subsystem_refresh_interval_ms))

    def get_view3d_fps(self) -> float:
        """Configured 3D animation frame rate. Clamped so the interval stays sane."""
        return max(1.0, float(self.view3d_fps))

    def get_view3d_frame_interval_ms(self) -> int:
        """
        Frame budget for the 3D animation loop: ``1000 / fps``.

        Stretched by ``slow_environment_factor`` because this one IS a cadence:
        on a host declared twice as slow the animation is allowed to run at half
        the rate rather than dropping frames behind the UI thread. Motion
        compensation for the new interval lives in the view, not here - see
        qt_view3d.BELT_CALIBRATION_FRAME_MS.
        """
        return max(1, int(round(self.scaled(1000.0 / self.get_view3d_fps()))))
    
    def get_chart_refresh_interval(self) -> int:
        return int(self.scaled(self.chart_refresh_interval_ms))
    
    def get_stream_refresh_interval(self) -> int:
        return int(self.scaled(self.stream_refresh_interval_ms))
    
    def get_heartbeat_interval(self) -> int:
        return int(self.scaled(self.heartbeat_interval_ms))
    
    def get_clock_interval(self) -> int:
        return int(self.scaled(self.clock_interval_ms))


@dataclass
class ConveyorConfig:
    # Safety Limits
    max_safe_rpm: float = 1000.0
    max_safe_temperature_c: float = 80.0
    max_safe_current_amps: float = 15.0
    max_safe_box_rate_per_min: float = 60.0
    
    # Development Defaults / Expected Baseline
    normal_temperature_c: float = 35.0
    normal_box_rate_per_min: float = 20.0
    
    # Residual Weights (Must sum to 1.0)
    weight_speed: float = 0.25
    weight_current: float = 0.30
    weight_temperature: float = 0.25
    weight_box_rate: float = 0.20
    
    # State Machine Risk Thresholds (0-100)
    risk_threshold_degraded: float = 25.0
    risk_threshold_restricted: float = 50.0
    risk_threshold_quarantined: float = 75.0


@dataclass
class AppConfig:
    """Main application configuration aggregator."""
    conveyor: ConveyorConfig = field(default_factory=ConveyorConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)


config = ConveyorConfig()
app_config = AppConfig()
