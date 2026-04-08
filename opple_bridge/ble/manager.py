"""BLE Manager — orchestrates scanning, connection, and measurement."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from opple_bridge.ble.connection import BLEConnection
from opple_bridge.ble.parser import (
    CalibrationData,
    G4_FLICKER_DEFAULT_PERIOD,
    G4_FLICKER_FULL_GROUPS,
    G4_FLICKER_LAST_PAGE,
    G4_FLICKER_PERIOD_11,
    G4_FLICKER_PERIOD_146,
    G4_FLICKER_PERIOD_25,
    G4_FLICKER_TOTAL_SAMPLES,
    RawFlicker,
    RawFlickerChunk,
    RawMeasurement,
    parse_calibration,
    parse_flicker_chunk,
    parse_measurement,
    parse_opcode,
    period_to_sample_rate,
)
from opple_bridge.ble.protocol import (
    NUS_NOTIFY_UUID,
    NUS_WRITE_UUID,
    REQ_CALIB,
    REQ_FREQ,
    REQ_MEAS,
    RES_CALIB,
    RES_FREQ,
    RES_MEAS,
    MessageAssembler,
    build_command,
    encapsulate,
)
from bleak import BleakScanner

from opple_bridge.ble.scanner import find_opple, scan_opple_devices
from opple_bridge.config import settings
from opple_bridge.models import (
    ConnectionState,
    ConnectionStatus,
    FlickerData,
    FlickerRiskLevel,
    MeasurementData,
)
from opple_bridge.science.cct import cct_from_xy
from opple_bridge.science.cie import (
    xy_to_uv,
    xy_to_uv_prime,
    xyz_to_xy,
)
from opple_bridge.science.circadian import compute_eml
from opple_bridge.science.cri import compute_cri
from opple_bridge.science.duv import duv_from_uv
from opple_bridge.science.polynomial import predict_g4, compute_cs
from opple_bridge.science.flicker import (
    dominant_frequency,
    fft,
    flicker_index,
    modulation_depth,
)
from opple_bridge.science.ieee1789 import assess_risk
from opple_bridge.science.spd import interpolate_spd
from opple_bridge.science.tristimulus import channels_to_xyz, channels_to_xyz_g4, detect_light_mode

logger = logging.getLogger(__name__)

LPF_ALPHA = 0.3

# Per-page sample stride in the assembled flicker buffer (see parser docstring).
# Pages 0..2 each contribute 65 groups × 4 samples = 260 samples; page 3 fills
# the remaining 244 slots. Stride is page * 260 regardless of chunk length.
_FLICKER_PAGE_STRIDE = G4_FLICKER_FULL_GROUPS * 4
_FLICKER_PAGES_REQUIRED = frozenset(range(G4_FLICKER_LAST_PAGE + 1))

# Cascade thresholds — replicates the OPPLE app's `readFrequence` escalation
# logic at opple-js-decompiled.js:2487794 / :2487898. We start with the
# broad-scan period 25, escalate to the fine-resolution period 146 if the
# detected frequency exceeds 2 kHz, then to the high-frequency period 11 if
# it exceeds 15 kHz. Below threshold, the previous round's result is kept.
_FLICKER_ESCALATE_TO_146_HZ = 2000.0
_FLICKER_ESCALATE_TO_11_HZ = 15000.0
_FLICKER_REQUEST_TIMEOUT_S = 10.0

# Battery lookup tables — ported verbatim from the OPPLE app's `battery()` function
# (Hermes-decompiled JS, line 2496934). The device firmware picks one of two tables
# based on its internal `firmwareVersion` field; we auto-detect by raw value range.
#
# Firmware < 107: raw is a direct ADC reading. Table values 3027..3297.
# Firmware >= 107: raw is in quarter-mV units (lookup = raw * 4). Table values 3455..4080 mV.
_G4_BATT_PCT = [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 1]
_G4_BATT_OLD_TABLE = [3297, 3270, 3243, 3216, 3189, 3162, 3135, 3108, 3081, 3054, 3027]
_G4_BATT_NEW_TABLE = [4080, 3985, 3894, 3838, 3773, 3725, 3710, 3688, 3656, 3594, 3455]


def _battery_raw_to_pct(raw: float | None) -> int | None:
    """Map the Opple G4 raw power reading to a 0-100% level.

    Replicates the official app's piecewise-linear lookup with the two tables
    used by the firmware. Above the table maximum → 100%; below the minimum → 1%.
    """
    if raw is None or raw <= 0:
        return None

    # Auto-detect firmware-version branch by which range the raw value lies in.
    # OLD raw values cluster around 3000-3300; NEW raw values around 860-1020.
    if raw >= 2000:
        table = _G4_BATT_OLD_TABLE
        lookup = float(raw)
    else:
        table = _G4_BATT_NEW_TABLE
        lookup = float(raw) * 4.0

    if lookup > table[0]:
        return 100
    if lookup <= table[-1]:
        return 1
    for i in range(len(table) - 1):
        hi, lo = table[i], table[i + 1]
        if hi >= lookup > lo:
            frac = (lookup - lo) / (hi - lo)
            pct = _G4_BATT_PCT[i + 1] + frac * (_G4_BATT_PCT[i] - _G4_BATT_PCT[i + 1])
            return int(round(pct))
    return None


class BLEManager:
    """High-level BLE orchestrator for the Opple Light Master.

    Handles: scan → connect → calibrate → measure loop → emit data.
    """

    def __init__(self):
        self._connection: Optional[BLEConnection] = None
        self._assembler = MessageAssembler(self._on_complete_message)
        self._calibration: Optional[CalibrationData] = None
        self._latest: Optional[MeasurementData] = None
        self._flicker_future: Optional[asyncio.Future] = None
        self._callbacks: list[Callable] = []
        self._state_callbacks: list[Callable] = []
        self._seq_no = 0
        self._running = False
        self._user_disconnected = False
        self._target_address: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._state = ConnectionState.DISCONNECTED
        self._device_name: Optional[str] = None
        self._device_address: Optional[str] = None
        self._battery_pct: Optional[int] = None
        self._last_raw_power: Optional[float] = None

        # Smoothing state
        self._prev_channels: Optional[list[float]] = None

        # Flicker chunk reassembly state — see _handle_flicker_chunk.
        self._flicker_buffer: list[float] = [0.0] * G4_FLICKER_TOTAL_SAMPLES
        self._flicker_pages_received: set[int] = set()
        self._flicker_data_type: int = 2
        # Period last sent in REQ_FREQ — needed when chunks come back so we
        # know which time-base to use for the FFT frequency formula.
        self._flicker_period: int = G4_FLICKER_DEFAULT_PERIOD

    @property
    def connection_status(self) -> ConnectionStatus:
        return ConnectionStatus(
            status=self._state,
            device_name=self._device_name,
            device_address=self._device_address,
            battery_pct=self._battery_pct,
            mock_mode=False,
        )

    @property
    def latest_measurement(self) -> Optional[MeasurementData]:
        return self._latest

    @property
    def last_raw_power(self) -> Optional[float]:
        return self._last_raw_power

    def on_measurement(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def on_state_change(self, callback: Callable) -> None:
        """Register a callback for connection state changes."""
        self._state_callbacks.append(callback)

    def _set_state(self, state: ConnectionState) -> None:
        if self._state != state:
            self._state = state
            self._notify_state_change()

    def _notify_state_change(self) -> None:
        status = self.connection_status
        for cb in self._state_callbacks:
            cb(status)

    def _notify_measurement(self) -> None:
        if self._latest is None:
            return
        for cb in self._callbacks:
            cb(self._latest)

    async def start(self) -> None:
        """Start the BLE manager: scan, connect, and begin measurement loop."""
        self._running = True
        self._user_disconnected = False
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the BLE manager and disconnect."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._connection:
            await self._connection.disconnect()
        self._set_state(ConnectionState.DISCONNECTED)

    async def connect_to(self, address: Optional[str] = None) -> None:
        """User-initiated connect: scan and connect to device."""
        self._user_disconnected = False
        self._target_address = address
        if self._running:
            await self.stop()
        await self.start()

    async def user_disconnect(self) -> None:
        """User-initiated disconnect: stop and don't auto-reconnect."""
        self._user_disconnected = True
        self._latest = None
        await self.stop()

    async def scan(self) -> list[dict]:
        """Scan for available Opple devices."""
        return await scan_opple_devices()

    async def request_flicker(self) -> Optional[FlickerData]:
        """Run the OPPLE app's 3-stage flicker measurement cascade.

        The G4 firmware exposes 3 distinct sampling modes (period 25/146/11),
        each with its own frequency-conversion factor and bin spacing. A single
        period cannot cover both LED PWM at ~100 Hz AND switching-PSU flicker
        at ~30 kHz with usable resolution, so the OPPLE Android app cycles
        through them. Logic transcribed from
        opple-js-decompiled.js:2487700-2487917 (`readFrequence`):

            1. Try period 25 (broad scan). If freq <= 2 kHz, this is the answer.
            2. Try period 146 (fine resolution). Always escalate further.
            3. Try period 11 (high-frequency). If freq > 15 kHz, use it,
               otherwise fall back to the period-146 result.
        """
        if not self._connection or not self._connection.is_connected:
            return None

        result_25 = await self._request_flicker_once(G4_FLICKER_PERIOD_25)
        if result_25 is None:
            return None
        if result_25.frequency_hz <= _FLICKER_ESCALATE_TO_146_HZ:
            return result_25

        result_146 = await self._request_flicker_once(G4_FLICKER_PERIOD_146)
        if result_146 is None:
            return result_25

        result_11 = await self._request_flicker_once(G4_FLICKER_PERIOD_11)
        if result_11 is not None and result_11.frequency_hz > _FLICKER_ESCALATE_TO_11_HZ:
            return result_11
        return result_146

    async def _request_flicker_once(self, period: int) -> Optional[FlickerData]:
        """Send one REQ_FREQ at the given period and return the analyzed result.

        REQ_FREQ payload layout (3 bytes), per `readFrequenceWithParam`
        (opple-js-decompiled.js:2488210-2488228):
            [0] = first param (always 0 in the OPPLE app)
            [1] = (period >> 8) & 0xFF  (high byte)
            [2] =  period       & 0xFF  (low byte)
        """
        if not self._connection or not self._connection.is_connected:
            return None

        self._reset_flicker_buffer()
        self._flicker_period = period
        self._flicker_future = asyncio.get_event_loop().create_future()

        payload = bytes([0x00, (period >> 8) & 0xFF, period & 0xFF])
        await self._send_command(REQ_FREQ, payload)

        try:
            raw_flicker = await asyncio.wait_for(
                self._flicker_future, timeout=_FLICKER_REQUEST_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            logger.warning("Flicker measurement at period=%d timed out", period)
            return None
        finally:
            self._flicker_future = None

        return self._process_flicker(raw_flicker)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                if self._user_disconnected:
                    break

                device = await self._discover_device()
                if device is None:
                    await asyncio.sleep(settings.ble_reconnect_delay)
                    continue

                if not await self._open_session(device):
                    await asyncio.sleep(settings.ble_reconnect_delay)
                    continue

                await self._measure_forever()

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in BLE run loop")
                if self._user_disconnected:
                    break
                self._set_state(ConnectionState.RECONNECTING)
                await asyncio.sleep(settings.ble_reconnect_delay)

    async def _discover_device(self):
        self._set_state(ConnectionState.SCANNING)
        if self._target_address:
            return await BleakScanner.find_device_by_address(
                self._target_address, timeout=settings.ble_scan_timeout
            )
        return await find_opple()

    async def _open_session(self, device) -> bool:
        self._device_name = device.name
        self._device_address = device.address

        self._set_state(ConnectionState.CONNECTING)
        self._connection = BLEConnection(device.address, on_disconnect=self._on_disconnect)
        if not await self._connection.connect():
            return False

        await self._connection.start_notify(NUS_NOTIFY_UUID, self._on_notification)
        await asyncio.sleep(0.3)
        await self._send_command(REQ_CALIB)
        await asyncio.sleep(1.0)
        self._set_state(ConnectionState.CONNECTED)
        return True

    async def _measure_forever(self) -> None:
        while self._running and self._connection and self._connection.is_connected:
            await self._send_command(REQ_MEAS)
            await asyncio.sleep(settings.measurement_interval)

    def _on_disconnect(self):
        """Handle unexpected BLE disconnection."""
        if not self._user_disconnected:
            self._set_state(ConnectionState.RECONNECTING)
        self._assembler.reset()
        self._prev_channels = None
        self._reset_flicker_buffer()

    def _on_notification(self, sender, data: bytearray):
        """Handle raw BLE notification (may be a fragment)."""
        self._assembler.feed(bytes(data))

    def _on_complete_message(self, data: bytes):
        """Process a fully reassembled NUS message."""
        opcode = parse_opcode(data)

        if opcode == RES_MEAS:
            raw = parse_measurement(data)
            if raw:
                self._process_measurement(raw)

        elif opcode == RES_CALIB:
            calib = parse_calibration(data)
            if calib:
                self._calibration = calib
                logger.info("Calibration loaded: kSensor=%s", calib.k_sensor)

        elif opcode == RES_FREQ:
            chunk = parse_flicker_chunk(data)
            if chunk:
                self._handle_flicker_chunk(chunk)

        else:
            logger.debug("Unknown opcode: 0x%04X", opcode)

    def _reset_flicker_buffer(self) -> None:
        """Drop any partial chunks so the next REQ_FREQ starts clean."""
        self._flicker_buffer = [0.0] * G4_FLICKER_TOTAL_SAMPLES
        self._flicker_pages_received = set()

    def _handle_flicker_chunk(self, chunk: RawFlickerChunk) -> None:
        """Write a chunk into the assembly buffer; resolve when all 4 arrive.

        Mirrors `dealReadFreq` (opple-js-decompiled.js:2497162) which writes
        each page at offset `page * 260` into a shared 1024-sample buffer and
        only invokes the analysis function on page 3.
        """
        offset = chunk.page * _FLICKER_PAGE_STRIDE
        for i, sample in enumerate(chunk.samples):
            idx = offset + i
            if idx < G4_FLICKER_TOTAL_SAMPLES:
                self._flicker_buffer[idx] = sample
        self._flicker_pages_received.add(chunk.page)
        self._flicker_data_type = chunk.data_type

        if not _FLICKER_PAGES_REQUIRED.issubset(self._flicker_pages_received):
            return

        raw = RawFlicker(
            waveform=list(self._flicker_buffer),
            sample_rate=period_to_sample_rate(self._flicker_period),
            data_type=self._flicker_data_type,
        )
        self._reset_flicker_buffer()

        if self._flicker_future and not self._flicker_future.done():
            self._flicker_future.set_result(raw)

    def _process_measurement(self, raw: RawMeasurement) -> None:
        self._update_battery(raw.battery_voltage)
        channels = self._calibrate_and_smooth(raw.channels)
        metrics = self._compute_metrics(channels, raw.is_g4)
        self._latest = self._build_measurement(channels, metrics)
        self._notify_measurement()

    def _update_battery(self, raw: float) -> None:
        self._last_raw_power = raw
        new_pct = _battery_raw_to_pct(raw)
        if new_pct != self._battery_pct:
            self._battery_pct = new_pct
            self._notify_state_change()

    def _calibrate_and_smooth(self, channels: list[float]) -> list[float]:
        if self._calibration:
            k = self._calibration.k_sensor[:len(channels)]
            channels = [ch * ki for ch, ki in zip(channels, k)]

        if self._prev_channels and len(self._prev_channels) == len(channels):
            channels = [
                LPF_ALPHA * prev + (1 - LPF_ALPHA) * cur
                for prev, cur in zip(self._prev_channels, channels)
            ]
        self._prev_channels = channels
        return channels

    @staticmethod
    def _compute_metrics(channels: list[float], is_g4: bool) -> dict:
        if is_g4:
            x_tri, y_tri, z_tri = channels_to_xyz_g4(channels)
        else:
            x_tri, y_tri, z_tri = channels_to_xyz(channels)

        lux = y_tri
        cie_x, cie_y = xyz_to_xy(x_tri, y_tri, z_tri)
        u_1960, v_1960 = xy_to_uv(cie_x, cie_y)
        u_prime, v_prime = xy_to_uv_prime(cie_x, cie_y)
        cct = cct_from_xy(cie_x, cie_y)
        duv = duv_from_uv(u_1960, v_1960)

        # G4 polynomial model can return None for spectra outside its training
        # domain (negative coefficient transform). In that case fall back to the
        # SPD-based CIE 13.3 path so the manager keeps producing measurements.
        result = predict_g4(channels[:8], cct=cct, lux=lux) if is_g4 else None
        if result is not None:
            ra = result["ra"]
            r_values = result["r_values"]
            eml = result["eml"]
            cs = compute_cs(result["a"], result["b"], lux)
            light_mode = "general"
        else:
            channels_6 = channels[:6]
            spd = interpolate_spd(channels_6)
            ra, r_values = compute_cri(spd, cct)
            light_mode = detect_light_mode(channels_6)
            eml = compute_eml(channels_6, cct, is_incandescent=(light_mode == "incandescent"))
            cs = None

        return {
            "lux": lux, "cct": cct, "duv": duv,
            "cie_x": cie_x, "cie_y": cie_y,
            "u_prime": u_prime, "v_prime": v_prime,
            "ra": ra, "r_values": r_values,
            "eml": eml, "cs": cs, "light_mode": light_mode,
        }

    def _build_measurement(
        self, channels: list[float], metrics: dict
    ) -> MeasurementData:
        r_values = metrics["r_values"]
        cs = metrics["cs"]
        return MeasurementData(
            connection=self.connection_status,
            lux=round(metrics["lux"], 1),
            cct_k=int(round(metrics["cct"])),
            duv=round(metrics["duv"], 4),
            cie_x=round(metrics["cie_x"], 4),
            cie_y=round(metrics["cie_y"], 4),
            cie_u=round(metrics["u_prime"], 4),
            cie_v=round(metrics["v_prime"], 4),
            cri_ra=round(metrics["ra"], 1),
            r9=round(r_values[8], 1) if len(r_values) > 8 else None,
            r_values=[round(r, 1) for r in r_values],
            cs=round(cs, 3) if cs is not None else None,
            eml=round(metrics["eml"], 0),
            light_mode=metrics["light_mode"],
            spectrum=[round(c, 1) for c in channels[:6]],
        )

    def _process_flicker(self, raw: RawFlicker) -> FlickerData:
        """Convert raw flicker data to FlickerData model.

        Runs the FFT on the full 1024-sample waveform — matching the JS path
        which feeds the entire buffer into its FFT. Truncating to 256 samples
        (as the previous version did) collapsed the bin spacing by 4× and
        produced ghost peaks at the wrong frequencies.
        """
        wave = raw.waveform
        if not wave:
            return FlickerData()

        md = modulation_depth(wave, raw.data_type)
        fi = flicker_index(wave, raw.data_type)

        n = len(wave)
        freq_bins, magnitudes = fft(wave, raw.data_type)
        freq_hz = dominant_frequency(magnitudes, raw.sample_rate, n)

        risk = assess_risk(freq_hz, md)

        # Dashboard only renders the first slice of the spectrum; keep the
        # 64-bin slice but scale by the *true* sample rate / N.
        fft_freqs = [b * raw.sample_rate / n for b in freq_bins[:64]]
        fft_mags = magnitudes[:64]

        return FlickerData(
            frequency_hz=round(freq_hz, 1),
            modulation_pct=round(md, 2),
            flicker_index=round(fi, 4),
            risk_level=risk,
            waveform=wave[:256],
            fft_freq=[round(f, 1) for f in fft_freqs],
            fft_mag=[round(m, 4) for m in fft_mags],
        )

    async def _send_command(self, opcode: int, payload: bytes = b"") -> None:
        """Build, encapsulate, and send a command to the device."""
        inner = build_command(opcode, payload, seq_no=self._next_seq())
        frames = encapsulate(inner)
        for frame in frames:
            await self._connection.write(NUS_WRITE_UUID, frame)

    def _next_seq(self) -> int:
        seq = self._seq_no
        self._seq_no = (self._seq_no + 1) & 0xFF
        return seq
