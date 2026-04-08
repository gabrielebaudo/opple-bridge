"""Mock data generator — produces realistic photometric measurements without hardware."""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from typing import Callable, Optional

from opple_bridge.models import (
    ConnectionState,
    ConnectionStatus,
    FlickerData,
    FlickerRiskLevel,
    MeasurementData,
)
from opple_bridge.science.cct import cct_from_xy
from opple_bridge.science.cie import xy_to_uv, xy_to_uv_prime, xyz_to_xy
from opple_bridge.science.circadian import compute_eml
from opple_bridge.science.cri import compute_cri
from opple_bridge.science.duv import duv_from_uv
from opple_bridge.science.spd import interpolate_spd
from opple_bridge.science.tristimulus import channels_to_xyz, detect_light_mode

logger = logging.getLogger(__name__)

# Preset lighting scenes — only channels needed, all metrics computed live
SCENES = [
    {"name": "Tungsten Wash 2800K", "channels": [80, 150, 350, 450, 520, 480]},
    {"name": "LED Wash Warm 3200K", "channels": [120, 200, 400, 420, 450, 380]},
    {"name": "LED Wash Cool 5600K", "channels": [320, 400, 450, 380, 300, 200]},
    {"name": "Fluorescent Work Light 4100K", "channels": [180, 280, 500, 420, 350, 250]},
]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class MockGenerator:
    """Simulates BLE data source with realistic photometric data."""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._latest: Optional[MeasurementData] = None
        self._callbacks: list[Callable] = []

        self._scene_idx = 0
        self._next_scene_idx = 1
        self._transition_start = 0.0
        self._transition_duration = 30.0  # seconds per scene
        self._time_in_scene = 0.0

    @property
    def connection_status(self) -> ConnectionStatus:
        return ConnectionStatus(
            status=ConnectionState.CONNECTED if self._running else ConnectionState.DISCONNECTED,
            device_name="Mock Light Master IV",
            device_address="MO:CK:00:00:00:01",
            mock_mode=True,
            battery_pct=85,
        )

    @property
    def latest_measurement(self) -> Optional[MeasurementData]:
        return self._latest

    def on_measurement(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        self._running = True
        self._transition_start = time.monotonic()
        self._task = asyncio.create_task(self._generate_loop())
        logger.info("Mock generator started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Mock generator stopped")

    async def request_flicker(self) -> FlickerData:
        """Generate mock flicker measurement on demand."""
        scene = SCENES[self._scene_idx]
        is_fluorescent = "Fluorescent" in scene["name"]

        freq = 100.0 if is_fluorescent else 0.0
        mod_pct = random.uniform(30, 50) if is_fluorescent else random.uniform(0.5, 3.0)
        fi = mod_pct / 1000.0

        n_samples = 256
        sample_rate = 10000.0
        waveform = []
        for i in range(n_samples):
            t = i / sample_rate
            if freq > 0:
                val = 1.0 + (mod_pct / 100.0) * math.sin(2.0 * math.pi * freq * t)
            else:
                val = 1.0 + random.gauss(0, 0.005)
            waveform.append(round(val, 4))

        n_fft = n_samples // 2
        fft_freq = [i * sample_rate / n_samples for i in range(n_fft)]
        fft_mag = [0.0] * n_fft
        fft_mag[0] = 1.0
        if freq > 0:
            peak_bin = int(freq * n_samples / sample_rate)
            if 0 < peak_bin < n_fft:
                fft_mag[peak_bin] = mod_pct / 100.0

        risk = FlickerRiskLevel.NO_RISK
        if freq > 0:
            if mod_pct > 30:
                risk = FlickerRiskLevel.HIGH_RISK
            elif mod_pct > 10:
                risk = FlickerRiskLevel.LOW_RISK

        return FlickerData(
            frequency_hz=round(freq + random.gauss(0, 0.5), 1),
            modulation_pct=round(mod_pct, 2),
            flicker_index=round(fi, 4),
            risk_level=risk,
            waveform=waveform,
            fft_freq=[round(f, 1) for f in fft_freq[:64]],
            fft_mag=[round(m, 4) for m in fft_mag[:64]],
        )

    async def _generate_loop(self):
        """Main generation loop — produces a new measurement at ~10Hz."""
        while self._running:
            try:
                self._latest = self._generate_measurement()
                for cb in self._callbacks:
                    cb(self._latest)
            except Exception:
                logger.exception("Error generating mock data")
            await asyncio.sleep(0.1)

    def _generate_measurement(self) -> MeasurementData:
        now = time.monotonic()
        elapsed = now - self._transition_start

        # Scene transition logic
        if elapsed > self._transition_duration:
            self._scene_idx = self._next_scene_idx
            self._next_scene_idx = (self._next_scene_idx + 1) % len(SCENES)
            self._transition_start = now
            elapsed = 0.0

        t = min(elapsed / self._transition_duration, 1.0)
        t = t * t * (3.0 - 2.0 * t)  # Smooth easing

        current = SCENES[self._scene_idx]
        target = SCENES[self._next_scene_idx]

        # Interpolate channels with noise
        channels = []
        for i in range(6):
            val = _lerp(current["channels"][i], target["channels"][i], t)
            val += random.gauss(0, val * 0.015)
            channels.append(max(0, val))

        # === Use real science pipeline ===
        x_tri, y_tri, z_tri = channels_to_xyz(channels)
        lux = y_tri

        cie_x, cie_y = xyz_to_xy(x_tri, y_tri, z_tri)
        u_1960, v_1960 = xy_to_uv(cie_x, cie_y)
        u_prime, v_prime = xy_to_uv_prime(cie_x, cie_y)
        cct = cct_from_xy(cie_x, cie_y)
        duv = duv_from_uv(u_1960, v_1960)

        # CRI from reconstructed SPD
        spd = interpolate_spd(channels)
        ra, r_values = compute_cri(spd, cct)

        # EML with correct light mode
        light_mode = detect_light_mode(channels)
        eml = compute_eml(channels, cct, is_incandescent=(light_mode == "incandescent"))

        return MeasurementData(
            connection=self.connection_status,
            lux=round(max(0, lux), 1),
            cct_k=max(1000, min(25000, int(round(cct)))),
            duv=round(duv, 4),
            cie_x=round(cie_x, 4),
            cie_y=round(cie_y, 4),
            cie_u=round(u_prime, 4),
            cie_v=round(v_prime, 4),
            cri_ra=round(max(0, min(100, ra)), 1),
            r9=round(r_values[8], 1) if len(r_values) > 8 else None,
            r_values=[round(r, 1) for r in r_values],
            cs=None,
            eml=round(max(0, eml), 0),
            light_mode=light_mode,
            spectrum=[round(c, 1) for c in channels[:6]],
        )
