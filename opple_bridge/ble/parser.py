"""Byte-level parser for Opple Light Master measurement responses.

Extracts raw sensor channels and metadata from NUS response payloads.
Supports both G3 (6 channels) and G4 (9 channels) formats.

G3 payload layout (after 11-byte inner header):
  Measurement (0x0A01):
    [0]    = 0x00 (skip)
    [1:13] = 6x uint16 big-endian channels (V,B,G,Y,O,R)
    [13:15]= uint16 big-endian power (battery mV)
    [15]   = uint8 ambient temperature (ignored — not displayed by the bridge)
  Calibration (0x0A05):
    [1:29] = 7x float32 little-endian kSensor coefficients

G4 payload layout (after 11-byte inner header), reverse-engineered from
Hermes-decompiled `dealNormalMeasureData` (line 2497691):
  Measurement (0x0A01) — 23-byte payload:
    [0]    = 0x00 (skip)
    [1:19] = 9x uint16 big-endian channels (8 spectral + 1 clear "fc")
    [19:21]= 2 reserved/padding bytes (always observed as 0x00 0x00)
    [21:23]= uint16 big-endian power (battery raw, lookup-table mapped)
    No temperature byte in this packet.
  Calibration (0x0A05):
    [1:37] = 9x float32 little-endian kSensor coefficients
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from typing import Optional

from opple_bridge.ble.protocol import RES_MEAS, RES_FREQ, RES_CALIB

logger = logging.getLogger(__name__)

# G3: 6 channels, G4: 9 channels
G3_NUM_CHANNELS = 6
G4_NUM_CHANNELS = 9

# G4 power offset in stripped payload: 1 (skip) + 18 (channels) + 2 (padding) = 21
G4_POWER_OFFSET = 21


@dataclass
class RawMeasurement:
    """Raw sensor data from the Opple (G3: 6 channels, G4: 9 channels)."""
    raw_channels: list[float]
    battery_voltage: float

    @property
    def channels(self) -> list[float]:
        return self.raw_channels

    @property
    def is_g4(self) -> bool:
        return len(self.raw_channels) > G3_NUM_CHANNELS


@dataclass
class CalibrationData:
    """Sensor calibration coefficients (G3: 7 floats, G4: 9 floats)."""
    k_sensor: list[float]


# G4 flicker chunking constants — see opple-js-decompiled.js dealReadFreq (~2497162).
# Each BLE response carries one chunk of the 1024-sample waveform.
# Pages 0..2 hold 65 sample-groups (260 samples each); page 3 holds 61 groups (244).
# 3 * 260 + 244 = 1024.
G4_FLICKER_TOTAL_SAMPLES = 1024
G4_FLICKER_FULL_GROUPS = 65
G4_FLICKER_LAST_GROUPS = 61
G4_FLICKER_LAST_PAGE = 3
G4_FLICKER_WAVE_OFFSET = 25  # Bytes 0..24 are chunk header (page at [1], data_type at [2]).

# Per-period time factors used by the device's frequency formula.
# Source: opple-js-decompiled.js:2488288-2488304 (`readFrequenceWithParam`).
# The OPPLE app issues REQ_FREQ with a `period` byte (25, 146, or 11) that
# selects the device's flicker sampling mode, then converts the FFT peak bin
# to Hz with `freq = peakBin * 1024 / time_factor`. We re-cast that as an
# effective sample rate `fs = N² / time_factor` so the standard formula
# `bin * fs / N` produces the same result.
G4_FLICKER_PERIOD_25 = 25     # ~25us mode, broad scan (covers ~50 Hz – 20 kHz)
G4_FLICKER_PERIOD_146 = 146   # ~195us mode, fine resolution at low frequencies
G4_FLICKER_PERIOD_11 = 11     # ~11us mode, high-frequency capture (>15 kHz)
G4_FLICKER_TIME_FACTORS: dict[int, float] = {
    G4_FLICKER_PERIOD_25: 26.0,
    G4_FLICKER_PERIOD_146: 150.0,
    G4_FLICKER_PERIOD_11: 12.285,
}
G4_FLICKER_DEFAULT_PERIOD = G4_FLICKER_PERIOD_25


def period_to_sample_rate(period: int) -> float:
    """Effective FFT sample rate for a given device flicker period.

    Re-casts the JS formula `freq = peakBin * 1024 / time_factor` so the
    standard `bin * fs / N` works without changes. See `G4_FLICKER_TIME_FACTORS`.
    """
    factor = G4_FLICKER_TIME_FACTORS.get(
        period, G4_FLICKER_TIME_FACTORS[G4_FLICKER_DEFAULT_PERIOD]
    )
    return (G4_FLICKER_TOTAL_SAMPLES * G4_FLICKER_TOTAL_SAMPLES) / factor


@dataclass
class RawFlickerChunk:
    """One chunk of the chunked G4 flicker response.

    The G4 splits a 1024-sample waveform across 4 BLE messages. The manager
    accumulates these into a `RawFlicker` before running the analysis.
    """
    page: int            # 0..3 (3 = last, smaller chunk)
    data_type: int       # device flicker range (0..2) — selects DC offset
    samples: list[float]


@dataclass
class RawFlicker:
    """Fully reassembled flicker waveform (1024 samples)."""
    waveform: list[float]
    sample_rate: float
    data_type: int


def parse_opcode(data: bytes) -> int:
    """Extract the opcode from a reassembled inner message."""
    if len(data) < 11:
        return 0
    return (data[9] << 8) | data[10]


def parse_measurement(data: bytes) -> Optional[RawMeasurement]:
    """Parse a measurement response (opcode 0x0A01).

    Auto-detects G3 (6 channels) vs G4 (9 channels) based on payload length.
    G4 sends 9×uint16 channels (18 bytes) vs G3's 6×uint16 (12 bytes).

    Layout differences:
      G3: skip + 6ch + power(u16 BE) + temp(u8) = 16 bytes payload
      G4: skip + 9ch + 2 padding + power(u16 BE) = 23 bytes payload, no temp
    """
    min_g3 = 11 + 1 + 12 + 2 + 1  # 27 bytes total

    if len(data) < min_g3:
        logger.warning("Measurement response too short: %d bytes", len(data))
        return None

    payload = data[11:]

    try:
        is_g4 = len(payload) >= (1 + 18 + 2 + 2)
        num_channels = G4_NUM_CHANNELS if is_g4 else G3_NUM_CHANNELS

        channels = []
        for i in range(num_channels):
            offset = 1 + 2 * i
            ch = (payload[offset] << 8) | payload[offset + 1]
            channels.append(float(ch))

        if is_g4:
            # G4 power: u16 BE at stripped offset 21 (after 9ch + 2-byte padding).
            power = (payload[G4_POWER_OFFSET] << 8) | payload[G4_POWER_OFFSET + 1]
        else:
            # G3 power: u16 BE right after the 6 channels.
            # (G3 also carries an ambient-temperature byte right after, but we
            #  don't expose it — see module docstring.)
            power_offset = 1 + 2 * num_channels  # = 13
            power = (payload[power_offset] << 8) | payload[power_offset + 1]

        return RawMeasurement(
            raw_channels=channels,
            battery_voltage=float(power),
        )
    except (struct.error, IndexError) as e:
        logger.error("Failed to parse measurement: %s", e)
        logger.debug("Raw data: %s", data.hex())
        return None


def parse_calibration(data: bytes) -> Optional[CalibrationData]:
    """Parse a calibration response (opcode 0x0A05).

    Auto-detects G3 (7 factors) vs G4 (9 factors) based on payload length.
    Each factor is float32 little-endian starting at payload[1].
    """
    payload = data[11:]
    min_g3 = 1 + 7 * 4  # 29 bytes
    min_g4 = 1 + 9 * 4  # 37 bytes

    if len(payload) < min_g3:
        logger.warning("Calibration response too short: %d bytes payload", len(payload))
        return None

    try:
        num_factors = 9 if len(payload) >= min_g4 else 7
        k_sensor = []
        for i in range(num_factors):
            offset = 1 + 4 * i
            val = struct.unpack_from('<f', payload, offset)[0]
            k_sensor.append(val)

        return CalibrationData(k_sensor=k_sensor)
    except struct.error as e:
        logger.error("Failed to parse calibration: %s", e)
        return None


def parse_flicker_chunk(data: bytes) -> Optional[RawFlickerChunk]:
    """Parse one G4 flicker chunk (opcode 0x0A0B).

    The G4 firmware delivers the 1024-sample flicker waveform in 4 chunks
    (pages 0..3). Layout per chunk, after the 11-byte NUS inner header
    (mirrors `dealReadFreq` in opple-js-decompiled.js around line 2497162):

      [0]    = ?
      [1]    = page index (0..3, page 3 = last)
      [2]    = data_type (device flicker range; selects DC offset)
      [3:25] = chunk metadata (unused here)
      [25:]  = packed 12-bit samples — groups of 6 bytes → 4 samples each

    Pages 0..2 carry 65 groups (260 samples). Page 3 carries 61 groups
    (244 samples). 3*260 + 244 = 1024.
    """
    payload = data[11:]

    if len(payload) < G4_FLICKER_WAVE_OFFSET:
        logger.warning("Flicker chunk too short: %d bytes payload", len(payload))
        return None

    try:
        page = payload[1]
        data_type = payload[2]

        if page > G4_FLICKER_LAST_PAGE:
            logger.warning("Invalid flicker page index: %d", page)
            return None

        n_groups = G4_FLICKER_LAST_GROUPS if page == G4_FLICKER_LAST_PAGE else G4_FLICKER_FULL_GROUPS
        wave_data = payload[G4_FLICKER_WAVE_OFFSET:]

        if len(wave_data) < n_groups * 6:
            logger.warning(
                "Flicker chunk wave data too short for page %d: %d < %d",
                page, len(wave_data), n_groups * 6,
            )
            return None

        samples: list[float] = []
        for i in range(n_groups):
            offset = 6 * i
            a = (wave_data[offset] << 8) | wave_data[offset + 1]
            b = (wave_data[offset + 2] << 8) | wave_data[offset + 3]
            c = (wave_data[offset + 4] << 8) | wave_data[offset + 5]

            xn0 = a >> 4
            xn1 = ((0x0F & a) << 8) | (b >> 8)
            xn2 = ((0xFF & b) << 4) | (c >> 12)
            xn3 = 0xFFF & c

            samples.extend([float(xn0), float(xn1), float(xn2), float(xn3)])

        return RawFlickerChunk(page=page, data_type=data_type, samples=samples)
    except (struct.error, IndexError) as e:
        logger.error("Failed to parse flicker chunk: %s", e)
        return None
