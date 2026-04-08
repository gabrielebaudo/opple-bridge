from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    SCANNING = "scanning"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class ConnectionStatus(BaseModel):
    status: ConnectionState = ConnectionState.DISCONNECTED
    device_name: Optional[str] = None
    device_address: Optional[str] = None
    mock_mode: bool = False
    battery_pct: Optional[int] = None
    message: Optional[str] = None


class MeasurementData(BaseModel):
    type: str = "measurement"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    connection: ConnectionStatus = Field(default_factory=ConnectionStatus)

    # Illuminance
    lux: float = 0.0

    # Color temperature
    cct_k: int = 0
    duv: float = 0.0

    # Chromaticity
    cie_x: float = 0.0
    cie_y: float = 0.0
    cie_u: float = 0.0
    cie_v: float = 0.0

    # Color rendering
    cri_ra: Optional[float] = None
    r9: Optional[float] = None
    r_values: Optional[list[float]] = None

    # Circadian
    cs: Optional[float] = None
    eml: Optional[float] = None

    # Light source type detected by tristimulus mode detection
    light_mode: Optional[str] = None  # "mono", "incandescent", "general"

    # Spectrum (6 channels: 450, 500, 550, 570, 600, 650 nm)
    spectrum: list[float] = Field(default_factory=lambda: [0.0] * 6)


class FlickerRiskLevel(str, Enum):
    NO_RISK = "no_risk"
    LOW_RISK = "low_risk"
    HIGH_RISK = "high_risk"


class FlickerData(BaseModel):
    type: str = "flicker"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    frequency_hz: float = 0.0
    modulation_pct: float = 0.0
    flicker_index: float = 0.0
    risk_level: FlickerRiskLevel = FlickerRiskLevel.NO_RISK
    waveform: list[float] = Field(default_factory=list)
    fft_freq: list[float] = Field(default_factory=list)
    fft_mag: list[float] = Field(default_factory=list)
