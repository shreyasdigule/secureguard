"""
dashboard_sync.py — Signal bridge between SecureGuardPipeline and Dashboard Qt widgets.

Provides Qt signals for:
- Pipeline command results → dashboard updates
- Subsystem state changes → tile updates
- Evidence log changes → evidence tab updates
- Telemetry streaming → stream/3D view updates
"""
import time
import atexit
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

from PySide6.QtCore import QObject, Signal, QTimer, Slot, QThread

from pipeline import SecureGuardPipeline, CommandResult
from keycloak_auth import AuthContext
from evidence_log import read_all_evidence, log_evidence, classify_decision
from hardware_telemetry import get_global_telemetry, TelemetryReading, SimulatedHardwareTelemetry

logger = logging.getLogger(__name__)


class PipelineWorker(QThread):
    """Background thread for executing pipeline commands without blocking UI."""
    
    command_completed = Signal(object)  # CommandResult
    command_failed = Signal(str)  # error message
    
    def __init__(self, pipeline: SecureGuardPipeline):
        super().__init__()
        self.pipeline = pipeline
        self._pending_command = None
        self._running = True
    
    def submit_command(self, subsystem_id: str, from_speed_rpm: float, to_speed_rpm: float,
                       cmd_type: str = "SET_SPEED", accel_rate: float = 100.0,
                       decel_rate: float = 150.0, torque_limit: float = 100.0,
                       direction: str = "FWD", ctrl_mode: str = "VELOCITY",
                       auth: AuthContext = None):
        """Queue a command for execution."""
        self._pending_command = {
            'subsystem_id': subsystem_id,
            'from_speed_rpm': from_speed_rpm,
            'to_speed_rpm': to_speed_rpm,
            'cmd_type': cmd_type,
            'accel_rate': accel_rate,
            'decel_rate': decel_rate,
            'torque_limit': torque_limit,
            'direction': direction,
            'ctrl_mode': ctrl_mode,
            'auth': auth,
        }
    
    def run(self):
        """Process commands from queue."""
        while self._running:
            if self._pending_command:
                cmd = self._pending_command
                self._pending_command = None
                try:
                    result = self.pipeline.process_command(
                        subsystem_id=cmd['subsystem_id'],
                        from_speed_rpm=cmd['from_speed_rpm'],
                        to_speed_rpm=cmd['to_speed_rpm'],
                        cmd_type=cmd['cmd_type'],
                        accel_rate=cmd['accel_rate'],
                        decel_rate=cmd['decel_rate'],
                        torque_limit=cmd['torque_limit'],
                        direction=cmd['direction'],
                        ctrl_mode=cmd['ctrl_mode'],
                        auth=cmd['auth'],
                    )
                    self.command_completed.emit(result)
                except Exception as e:
                    self.command_failed.emit(str(e))
            else:
                self.msleep(50)  # Poll interval
    
    def stop(self, timeout_ms: int = 5000) -> bool:
        """
        Signal the worker to exit and wait, but never block indefinitely.

        The worker polls every ``50ms``, so it normally returns immediately. A
        bounded wait matters because pipeline processing is allowed to run for
        several minutes under the generous timeout budget, and a plain
        ``wait()`` would freeze the UI for that whole period.
        """
        self._running = False
        if self.isRunning():
            if not self.wait(timeout_ms):
                logger.warning(
                    "PipelineWorker did not stop within %dms; leaving thread "
                    "alive to avoid a QThread-destroyed-while-running abort.",
                    timeout_ms,
                )
                return False
        return True


class DashboardPipelineSync(QObject):
    """
    Central synchronization hub connecting SecureGuardPipeline to Dashboard widgets.
    
    Signals emitted:
        subsystem_updated(str, dict) - subsystem_id, state_data
        command_executed(CommandResult) - pipeline command result
        evidence_added(dict) - new evidence record
        telemetry_update(dict) - live telemetry data
        subsystem_state_changed(str, str) - subsystem_id, new_state
        error_occurred(str) - error message
    """
    
    # Core signals
    subsystem_updated = Signal(str, dict)  # subsystem_id, state_data
    command_executed = Signal(object)  # CommandResult
    evidence_added = Signal(dict)  # evidence record
    telemetry_update = Signal(dict)  # telemetry data
    subsystem_state_changed = Signal(str, str)  # subsystem_id, new_state
    error_occurred = Signal(str)  # error message
    auth_changed = Signal(object)  # AuthContext or None
    
    def __init__(self, pipeline: SecureGuardPipeline = None):
        super().__init__()
        self.pipeline = pipeline or SecureGuardPipeline()
        self._auth: Optional[AuthContext] = None
        self._subsystem_tiles: Dict[str, 'SubsystemTile'] = {}
        self._command_history: List[Dict] = []
        self._max_history = 200
        
        # Worker thread for async command execution
        self._worker = PipelineWorker(self.pipeline)
        self._worker.command_completed.connect(self._on_command_completed)
        self._worker.command_failed.connect(self._on_command_failed)
        self._worker.start()
        
        # Telemetry streaming
        self._telemetry = get_global_telemetry()
        self._stream_timer = QTimer()
        self._stream_timer.timeout.connect(self._poll_telemetry)
        self._stream_active = False
        self._stream_subsystem = "conv_1"
        
        # Evidence log polling
        self._evidence_timer = QTimer()
        self._evidence_timer.timeout.connect(self._poll_evidence)
        self._last_evidence_count = 0
        
        # Subsystem state polling
        self._state_timer = QTimer()
        self._state_timer.timeout.connect(self._poll_subsystem_states)
        self._state_timer.start(5000)  # Poll every 5 seconds
        
        # Initial state load
        self._poll_subsystem_states()
    
    # -------------------------------------------------------------------------
    # Auth management
    # -------------------------------------------------------------------------
    def set_auth(self, auth: Optional[AuthContext]):
        """Set current authentication context."""
        self._auth = auth
        self.auth_changed.emit(auth)
    
    def get_auth(self) -> Optional[AuthContext]:
        return self._auth
    
    # -------------------------------------------------------------------------
    # Command execution
    # -------------------------------------------------------------------------
    def execute_command(self, subsystem_id: str, from_speed_rpm: float, to_speed_rpm: float,
                        cmd_type: str = "SET_SPEED", accel_rate: float = 100.0,
                        decel_rate: float = 150.0, torque_limit: float = 100.0,
                        direction: str = "FWD", ctrl_mode: str = "VELOCITY"):
        """Submit a command to the pipeline worker thread."""
        if not self._auth:
            self.error_occurred.emit("No authentication context - please log in first")
            return
        
        # CommandResult carries no subsystem_id or target speed, so the context
        # has to be retained here; otherwise every evidence record written by
        # this bridge says subsystem="unknown" / "SET_SPEED = unknown RPM".
        self._command_context = {
            "subsystem": subsystem_id,
            "to_speed_rpm": to_speed_rpm,
            "cmd_type": cmd_type,
        }

        self._worker.submit_command(
            subsystem_id=subsystem_id,
            from_speed_rpm=from_speed_rpm,
            to_speed_rpm=to_speed_rpm,
            cmd_type=cmd_type,
            accel_rate=accel_rate,
            decel_rate=decel_rate,
            torque_limit=torque_limit,
            direction=direction,
            ctrl_mode=ctrl_mode,
            auth=self._auth,
        )
    
    @Slot(object)
    def _on_command_completed(self, result: CommandResult):
        """Handle completed pipeline command."""
        # Store in command history
        context = getattr(self, "_command_context", None) or {}
        subsystem_id = context.get("subsystem", "unknown")
        to_speed_rpm = context.get("to_speed_rpm")
        cmd_type = context.get("cmd_type", "SET_SPEED")

        record = {
            'timestamp': time.time(),
            'subsystem_id': subsystem_id,
            'accepted': result.accepted,
            'reason': result.reason,
            'risk_score': result.risk.overall_risk_score if result.risk else 0,
            'risk_level': result.risk.overall_risk_level if result.risk else 'UNKNOWN',
            'new_state': result.new_state.value if result.new_state else 'UNKNOWN',
            'predicted': asdict(result.predicted) if result.predicted else None,
            'observed': asdict(result.observed) if result.observed else None,
        }
        self._command_history.append(record)
        if len(self._command_history) > self._max_history:
            self._command_history = self._command_history[-self._max_history:]
        
        # Emit signals for UI updates
        self.command_executed.emit(result)
        
        # Update charts with new data
        if result.risk:
            self._update_charts_from_result(result, subsystem_id)

        # Every processed command is recorded, accepted or not: a refusal is a
        # governance event, not a no-op.
        self._log_command_evidence(result, subsystem_id, to_speed_rpm, cmd_type)
        
        # Refresh subsystem states
        self._poll_subsystem_states()
    
    @Slot(str)
    def _on_command_failed(self, error: str):
        self.error_occurred.emit(f"Command execution failed: {error}")
    
    def _log_command_evidence(self, result: CommandResult, subsystem_id: str,
                               to_speed_rpm, cmd_type: str = "SET_SPEED"):
        """Append this command to the tamper-evident ledger.

        Subsystem and target speed come from the submission, not from
        ``result``: ``CommandResult`` has no such attributes, so reading them off
        it silently produced "unknown" for every field. ``final_decision`` uses
        the shared classifier so this bridge and the console cannot disagree
        about whether a refusal was a safety or an authorization event.
        """
        try:
            target = "unknown" if to_speed_rpm is None else f"{float(to_speed_rpm):.0f} RPM"
            log_evidence(
                subsystem=subsystem_id,
                command=f"{cmd_type} = {target}",
                previous_state=result.previous_state.value if result.previous_state else "UNKNOWN",
                predicted_trajectory=asdict(result.predicted) if result.predicted else {},
                observed_trajectory=asdict(result.observed) if result.observed else {},
                residual=0.0,  # Would need calculation
                risk_score=result.risk.overall_risk_score if result.risk else None,
                risk_level=result.risk.overall_risk_level if result.risk else None,
                new_state=result.new_state.value if result.new_state else "UNKNOWN",
                authorization_path=result.reason,
                xai_explanation=result.explanation or "",
                user=self._auth.username if self._auth else "unknown",
                roles=sorted(self._auth.roles) if self._auth else [],
                mfa_verified=self._auth.mfa_verified if self._auth else False,
                supervisor_approved=self._auth.supervisor_approved if self._auth else False,
                final_decision=classify_decision(result),
                rejection_reason="" if result.accepted else str(result.reason or ""),
            )
        except Exception as e:
            self.error_occurred.emit(f"Failed to log evidence: {e}")

    def _update_charts_from_result(self, result: CommandResult, subsystem_id: str):
        """Update chart data from command result."""
        if not result.risk or not result.predicted or not result.observed:
            return

        data_point = {
            'timestamp': time.time(),
            'subsystem': subsystem_id,
            'risk_score': result.risk.overall_risk_score,
            'motor_current_amps': result.observed.motor_current_amps,
            'motor_speed_rpm': result.observed.motor_speed_rpm,
            'temperature_c': result.observed.temperature_c,
            'box_rate_per_min': result.observed.box_rate_per_min,
        }
        # ChartsTab will poll this via get_chart_data()
    
    # -------------------------------------------------------------------------
    # Telemetry streaming
    # -------------------------------------------------------------------------
    def start_telemetry_stream(self, subsystem_id: str = "conv_1"):
        """Start live telemetry polling."""
        self._stream_subsystem = subsystem_id
        self._stream_active = True
        self._stream_timer.start(1000)  # 1 Hz
    
    def stop_telemetry_stream(self):
        """Stop live telemetry polling."""
        self._stream_active = False
        self._stream_timer.stop()
    
    @Slot()
    def _poll_telemetry(self):
        """Poll telemetry and emit update."""
        if not self._stream_active:
            return
        try:
            reading: TelemetryReading = self._telemetry.read_telemetry(self._stream_subsystem)
            data = {
                'timestamp': reading.timestamp,
                'subsystem_id': self._stream_subsystem,
                'motor_speed_rpm': reading.trajectory.motor_speed_rpm,
                'motor_current_amps': reading.trajectory.motor_current_amps,
                'temperature_c': reading.trajectory.temperature_c,
                'box_rate_per_min': reading.trajectory.box_rate_per_min,
                'conveyor_state': reading.trajectory.conveyor_state,
                'source': reading.source,
                'quality': reading.quality,
                'sequence_id': reading.sequence_id,
            }
            self.telemetry_update.emit(data)
        except Exception as e:
            self.error_occurred.emit(f"Telemetry poll error: {e}")
    
    # -------------------------------------------------------------------------
    # Evidence log polling
    # -------------------------------------------------------------------------
    def start_evidence_poll(self):
        """Start polling evidence log for new records."""
        self._last_evidence_count = len(read_all_evidence())
        self._evidence_timer.start(3000)  # Poll every 3 seconds
    
    def stop_evidence_poll(self):
        self._evidence_timer.stop()
    
    @Slot()
    def _poll_evidence(self):
        """Poll evidence log for new records."""
        try:
            records = read_all_evidence()
            if len(records) > self._last_evidence_count:
                # New records added (records are newest-first)
                new_records = records[:len(records) - self._last_evidence_count]
                for record in new_records:
                    self.evidence_added.emit(record)
                self._last_evidence_count = len(records)
        except Exception as e:
            self.error_occurred.emit(f"Evidence poll error: {e}")
    
    # -------------------------------------------------------------------------
    # Subsystem state polling
    # -------------------------------------------------------------------------
    @Slot()
    def _poll_subsystem_states(self):
        """Poll subsystem states and emit updates."""
        try:
            subsystems = self.pipeline.state_store.get_all()
            for subsystem_id, subsystem in subsystems.items():
                state_data = {
                    'subsystem_id': subsystem_id,
                    'state': subsystem.state.value if hasattr(subsystem.state, 'value') else str(subsystem.state),
                    'risk_score': 0,  # Would need to compute from last command
                    'last_update': time.time(),
                }
                self.subsystem_updated.emit(subsystem_id, state_data)
                
                # Track state changes
                if subsystem_id in self._subsystem_tiles:
                    old_state = self._subsystem_tiles[subsystem_id].get('state')
                    new_state = state_data['state']
                    if old_state and old_state != new_state:
                        self.subsystem_state_changed.emit(subsystem_id, new_state)
                
                # Store for change detection
                self._subsystem_tiles[subsystem_id] = state_data
        except Exception as e:
            self.error_occurred.emit(f"State poll error: {e}")
    
    # -------------------------------------------------------------------------
    # Public API for dashboard widgets
    # -------------------------------------------------------------------------
    def get_command_history(self) -> List[Dict]:
        """Get command history for charts."""
        return self._command_history.copy()
    
    def get_subsystem_states(self) -> Dict[str, Dict]:
        """Get current subsystem states."""
        return self._subsystem_tiles.copy()
    
    def register_subsystem_tile(self, subsystem_id: str, tile_widget):
        """Register a tile widget for direct updates."""
        self._subsystem_tiles[subsystem_id] = {'widget': tile_widget, 'state': 'UNKNOWN'}
    
    def cleanup(self):
        """
        Stop timers and the worker thread.

        Must run before the interpreter finalises Qt: a still-running QThread is
        destroyed with the process and aborts it (0xC0000409). Idempotent, so it
        is safe to call from both ``closeEvent`` and the ``atexit`` hook.
        """
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True

        self._state_timer.stop()
        self._evidence_timer.stop()
        self._stream_timer.stop()
        self._stream_active = False
        self._worker.stop()


# Global sync instance (singleton pattern)
_sync_instance: Optional[DashboardPipelineSync] = None


def get_dashboard_sync(pipeline: SecureGuardPipeline = None) -> DashboardPipelineSync:
    """Get or create the global dashboard sync instance."""
    global _sync_instance
    if _sync_instance is None:
        _sync_instance = DashboardPipelineSync(pipeline)
    return _sync_instance


def set_dashboard_sync(sync: DashboardPipelineSync):
    """Set a custom sync instance (for testing)."""
    global _sync_instance
    _sync_instance = sync


def shutdown_dashboard_sync() -> None:
    """
    Stop the global sync instance's timers and worker thread.

    Registered with ``atexit`` so the QThread is always retired before Python
    finalises the Qt object tree. Without this the interpreter exit aborts with
    STATUS_STACK_BUFFER_OVERRUN as soon as any widget has created the singleton.
    """
    global _sync_instance
    sync = _sync_instance
    _sync_instance = None
    if sync is None:
        return
    try:
        sync.cleanup()
    except Exception:  # pragma: no cover - best effort during shutdown
        logger.exception("Dashboard sync shutdown failed")


atexit.register(shutdown_dashboard_sync)