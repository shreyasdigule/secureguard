"""
hardware_telemetry.py — Hardware Telemetry Abstraction Layer
Provides a clean interface for pulling telemetry from the actual hardware layer.
In production, this would interface with PLCs, Modbus, OPC-UA, or sensor buses.
"""

import abc
import random
import time
from dataclasses import dataclass
from typing import Optional, Dict
from digital_twin import Trajectory
from config import app_config


@dataclass
class TelemetryReading:
    """Raw telemetry reading from hardware with metadata."""
    trajectory: Trajectory
    timestamp: float
    source: str  # e.g., "modbus", "opcua", "sensor_bus"
    quality: str  # "good", "uncertain", "bad"
    sequence_id: int


class HardwareTelemetryInterface(abc.ABC):
    """Abstract interface for hardware telemetry acquisition."""

    @abc.abstractmethod
    def read_telemetry(self, subsystem_id: str) -> TelemetryReading:
        """Read current telemetry from hardware for a subsystem."""
        pass

    @abc.abstractmethod
    def health_check(self, subsystem_id: str) -> bool:
        """Check if telemetry source is healthy."""
        pass

    @abc.abstractmethod
    def get_supported_subsystems(self) -> list[str]:
        """Return list of subsystem IDs this interface can read."""
        pass

    def set_commanded_state(self, subsystem_id: str, trajectory: Trajectory, cmd_type: str = "SET_SPEED", accel_rate: float = 100.0, decel_rate: float = 150.0, torque_limit: float = 100.0, direction: str = "FWD", ctrl_mode: str = "VELOCITY") -> None:
        """Optional: set the commanded state for simulation purposes."""
        pass


class SimulatedHardwareTelemetry(HardwareTelemetryInterface):
    """
    Simulated hardware telemetry for development/testing.
    In production, replace with Modbus/OPC-UA/Profinet driver.
    
    For testing with noise_factor=0, this returns the exact commanded state
    to simulate perfect hardware behavior.
    """
    
    def __init__(self, noise_factor: float = 0.02):
        self.noise_factor = noise_factor
        self._sequence_counters: dict[str, int] = {}
        self._last_reading: dict[str, Trajectory] = {}
        self._commanded_state: dict[str, Trajectory] = {}
        self._commanded_params: dict[str, dict] = {}
        
    def set_commanded_state(self, subsystem_id: str, trajectory: Trajectory, cmd_type: str = "SET_SPEED", accel_rate: float = 100.0, decel_rate: float = 150.0, torque_limit: float = 100.0, direction: str = "FWD", ctrl_mode: str = "VELOCITY") -> None:
        """Set the commanded state for this subsystem (used by pipeline)."""
        self._commanded_state[subsystem_id] = trajectory
        self._commanded_params[subsystem_id] = {
            "cmd_type": cmd_type,
            "accel_rate": accel_rate,
            "decel_rate": decel_rate,
            "torque_limit": torque_limit,
            "direction": direction,
            "ctrl_mode": ctrl_mode,
        }
        
    def get_commanded_params(self, subsystem_id: str) -> dict:
        """Get the commanded parameters for a subsystem."""
        return self._commanded_params.get(subsystem_id, {})
        
    def read_telemetry(self, subsystem_id: str) -> TelemetryReading:
        """Generate simulated telemetry with realistic noise."""
        # Increment sequence counter
        self._sequence_counters[subsystem_id] = self._sequence_counters.get(subsystem_id, 0) + 1
        
        # Check if there's an injected anomaly for this subsystem
        if hasattr(self, '_anomalies') and subsystem_id in self._anomalies:
            # Return the injected anomaly trajectory directly
            anomaly = self._anomalies[subsystem_id]
            return TelemetryReading(
                trajectory=anomaly,
                timestamp=time.time(),
                source="simulated",
                quality="good",
                sequence_id=self._sequence_counters[subsystem_id],
            )
        
        # Use commanded state if available, otherwise fall back to last reading or baseline
        if subsystem_id in self._commanded_state:
            base = self._commanded_state[subsystem_id]
        elif subsystem_id in self._last_reading:
            base = self._last_reading[subsystem_id]
        else:
            # Baseline reading
            base = Trajectory(
                conveyor_state="STOPPED",
                motor_speed_rpm=0.0,
                motor_current_amps=0.0,
                temperature_c=25.0,
                box_rate_per_min=0.0,
            )
        
        # Apply noise factor if configured
        if self.noise_factor > 0:
            trajectory = Trajectory(
                conveyor_state=base.conveyor_state,
                motor_speed_rpm=max(0, base.motor_speed_rpm * (1 + random.uniform(-self.noise_factor, self.noise_factor))),
                motor_current_amps=max(0, base.motor_current_amps * (1 + random.uniform(-self.noise_factor, self.noise_factor))),
                temperature_c=base.temperature_c * (1 + random.uniform(-self.noise_factor, self.noise_factor)),
                box_rate_per_min=max(0, base.box_rate_per_min * (1 + random.uniform(-self.noise_factor, self.noise_factor))),
            )
        else:
            # No noise - return exact commanded state
            trajectory = Trajectory(
                conveyor_state=base.conveyor_state,
                motor_speed_rpm=base.motor_speed_rpm,
                motor_current_amps=base.motor_current_amps,
                temperature_c=base.temperature_c,
                box_rate_per_min=base.box_rate_per_min,
            )
        
        # Store for next reading
        self._last_reading[subsystem_id] = trajectory
        
        return TelemetryReading(
            trajectory=trajectory,
            timestamp=time.time(),
            source="simulated",
            quality="good",
            sequence_id=self._sequence_counters.get(subsystem_id, 0),
        )
    
    def inject_anomaly(self, subsystem_id: str, trajectory: Trajectory):
        """Inject an anomalous trajectory for testing risk detection."""
        if not hasattr(self, '_anomalies'):
            self._anomalies = {}
        self._anomalies[subsystem_id] = trajectory
    
    def clear_anomaly(self, subsystem_id: str):
        """Clear injected anomaly."""
        if hasattr(self, '_anomalies') and subsystem_id in self._anomalies:
            del self._anomalies[subsystem_id]
    
    def health_check(self, subsystem_id: str) -> bool:
        # Simulate a health check with configurable timeout
        timeout = app_config.timeouts.get_telemetry_timeout()
        # In simulation, just check state - in production this would ping hardware
        return subsystem_id in self._commanded_state or subsystem_id in self._last_reading
    
    def get_supported_subsystems(self) -> list[str]:
        return list(self._commanded_state.keys()) or list(self._last_reading.keys()) or ["conv_1"]
    
    def reset_subsystem(self, subsystem_id: str) -> None:
        """Reset the simulated state for a subsystem."""
        self._last_reading.pop(subsystem_id, None)
        self._commanded_state.pop(subsystem_id, None)
        self._sequence_counters.pop(subsystem_id, None)
        if hasattr(self, '_anomalies'):
            self._anomalies.pop(subsystem_id, None)


class ModbusTelemetry(HardwareTelemetryInterface):
    """
    Production Modbus TCP telemetry driver.
    Requires pymodbus: pip install pymodbus
    """
    def __init__(self, host: str, port: int = 502, unit_id: int = 1):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self._client = None
        self._register_map = {
            "motor_speed_rpm": 100,
            "motor_current_amps": 102,
            "temperature_c": 104,
            "box_rate_per_min": 106,
            "conveyor_state": 108,
        }
    
    def connect(self):
        """Establish Modbus connection."""
        try:
            from pymodbus.client import ModbusTcpClient
            self._client = ModbusTcpClient(self.host, port=self.port)
            self._client.connect()
        except ImportError:
            raise RuntimeError("pymodbus not installed. Run: pip install pymodbus")
    
    def read_telemetry(self, subsystem_id: str) -> TelemetryReading:
        if not self._client or not self._client.connected:
            self.connect()
        
        # Read holding registers
        result = self._client.read_holding_registers(
            address=100, count=10, slave=self.unit_id
        )
        
        if result.isError():
            raise RuntimeError(f"Modbus read error: {result}")
        
        registers = result.registers
        
        trajectory = Trajectory(
            conveyor_state="RUNNING" if registers[self._register_map["conveyor_state"]] == 1 else "STOPPED",
            motor_speed_rpm=float(registers[self._register_map["motor_speed_rpm"]]),
            motor_current_amps=float(registers[self._register_map["motor_current_amps"]]) / 10.0,
            temperature_c=float(registers[self._register_map["temperature_c"]]) / 10.0,
            box_rate_per_min=float(registers[self._register_map["box_rate_per_min"]]),
        )
        
        return TelemetryReading(
            trajectory=trajectory,
            timestamp=time.time(),
            source="modbus_tcp",
            quality="good",
            sequence_id=0,
        )
    
    def health_check(self, subsystem_id: str) -> bool:
        try:
            if not self._client or not self._client.connected:
                self.connect()
            result = self._client.read_holding_registers(address=100, count=1, slave=self.unit_id)
            return not result.isError()
        except Exception:
            return False
    
    def get_supported_subsystems(self) -> list[str]:
        return ["conveyor_motor_01"]


class OpcUaTelemetry(HardwareTelemetryInterface):
    """
    Production OPC-UA telemetry driver.
    Requires opcua-asyncio: pip install opcua-asyncio
    """
    def __init__(self, endpoint_url: str, node_prefix: str = "ns=2;s=Conveyor."):
        self.endpoint_url = endpoint_url
        self.node_prefix = node_prefix
        self._client = None
    
    async def connect(self):
        try:
            from asyncua import Client
            self._client = Client(self.endpoint_url)
            await self._client.connect()
        except ImportError:
            raise RuntimeError("opcua-asyncio not installed. Run: pip install opcua-asyncio")
    
    async def read_telemetry(self, subsystem_id: str) -> TelemetryReading:
        if not self._client:
            await self.connect()
        
        # Read nodes
        speed_node = self._client.get_node(f"{self.node_prefix}MotorSpeed")
        current_node = self._client.get_node(f"{self.node_prefix}MotorCurrent")
        temp_node = self._client.get_node(f"{self.node_prefix}Temperature")
        box_node = self._client.get_node(f"{self.node_prefix}BoxRate")
        state_node = self._client.get_node(f"{self.node_prefix}ConveyorState")
        
        speed = await speed_node.read_value()
        current = await current_node.read_value()
        temp = await temp_node.read_value()
        box_rate = await box_node.read_value()
        state = await state_node.read_value()
        
        trajectory = Trajectory(
            conveyor_state="RUNNING" if state else "STOPPED",
            motor_speed_rpm=float(speed),
            motor_current_amps=float(current),
            temperature_c=float(temp),
            box_rate_per_min=float(box_rate),
        )
        
        return TelemetryReading(
            trajectory=trajectory,
            timestamp=time.time(),
            source="opcua",
            quality="good",
            sequence_id=0,
        )
    
    async def health_check(self, subsystem_id: str) -> bool:
        try:
            if not self._client:
                await self.connect()
            # Try reading a simple node
            await self._client.get_node(f"{self.node_prefix}MotorSpeed").read_value()
            return True
        except Exception:
            return False
    
    def get_supported_subsystems(self) -> list[str]:
        return ["conveyor_motor_01"]


# Factory function for getting the right telemetry interface
def get_telemetry_interface() -> HardwareTelemetryInterface:
    """
    Factory to get the configured telemetry interface.
    In production, configure via environment variable.
    """
    import os
    
    telemetry_type = os.getenv("TELEMETRY_INTERFACE", "simulated").lower()
    
    if telemetry_type == "simulated":
        noise = float(os.getenv("TELEMETRY_NOISE", "0.02"))
        return SimulatedHardwareTelemetry(noise_factor=noise)
    
    elif telemetry_type == "modbus":
        host = os.getenv("MODBUS_HOST", "192.168.1.100")
        port = int(os.getenv("MODBUS_PORT", "502"))
        unit = int(os.getenv("MODBUS_UNIT_ID", "1"))
        telemetry = ModbusTelemetry(host, port, unit)
        telemetry.connect()
        return telemetry
    
    elif telemetry_type == "opcua":
        # OPC-UA requires async, wrap for sync usage
        raise NotImplementedError("OPC-UA requires async runtime. Use async pipeline.")
    
    else:
        raise ValueError(f"Unknown telemetry interface: {telemetry_type}")


# Global singleton instance
_telemetry_interface: Optional[HardwareTelemetryInterface] = None


def get_global_telemetry() -> HardwareTelemetryInterface:
    """Get or create the global telemetry interface singleton."""
    global _telemetry_interface
    if _telemetry_interface is None:
        _telemetry_interface = get_telemetry_interface()
    return _telemetry_interface


def set_telemetry_interface(interface: HardwareTelemetryInterface) -> None:
    """Set a custom telemetry interface (for testing)."""
    global _telemetry_interface
    _telemetry_interface = interface
