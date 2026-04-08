"""Tests for BLEManager helpers that don't need a live BLE stack."""
import asyncio
import math

import pytest

from opple_bridge.ble.manager import BLEManager, _battery_raw_to_pct
from opple_bridge.ble.parser import (
    G4_FLICKER_FULL_GROUPS,
    G4_FLICKER_LAST_GROUPS,
    G4_FLICKER_LAST_PAGE,
    G4_FLICKER_PERIOD_11,
    G4_FLICKER_PERIOD_146,
    G4_FLICKER_PERIOD_25,
    G4_FLICKER_TOTAL_SAMPLES,
    CalibrationData,
    RawFlickerChunk,
    RawMeasurement,
)
from opple_bridge.ble.protocol import REQ_FREQ
from opple_bridge.models import FlickerData, FlickerRiskLevel


class TestBatteryRawToPct:
    """Verify the lookup-table battery formula matches the OPPLE app behaviour.

    The reference tables come from the Hermes-decompiled `battery()` function
    in the OPPLE Android app (opple-js-decompiled.js line 2496934).
    """

    # Old-firmware (< 107) branch: raw is a direct ADC reading.
    @pytest.mark.parametrize("raw,expected", [
        (3344.0, 100),    # observed real-device value when fully charged
        (3297.0, 100),    # exact top of OLD table
        (3027.0, 1),      # exact bottom of OLD table
        (3000.0, 1),      # below min → clamp to 1
        (5000.0, 100),    # above max → clamp to 100
    ])
    def test_old_branch_endpoints(self, raw, expected):
        assert _battery_raw_to_pct(raw) == expected

    def test_old_branch_interpolates_midpoint(self):
        # Halfway between 3162 (50%) and 3135 (40%) → ~45%
        assert 44 <= _battery_raw_to_pct(3148.5) <= 46

    # New-firmware (>= 107) branch: raw is in quarter-mV units (raw * 4 → mV).
    @pytest.mark.parametrize("raw,expected", [
        (1020.0, 100),    # 4080 mV → top of NEW table
        (864.0, 1),       # 3456 mV → just above bottom of NEW table
        (1100.0, 100),    # above max → clamp to 100
        (800.0, 1),       # below min → clamp to 1
    ])
    def test_new_branch_endpoints(self, raw, expected):
        assert _battery_raw_to_pct(raw) == expected

    def test_new_branch_interpolates_midpoint(self):
        # Halfway between 3725 mV (50%) and 3710 mV (40%) → ~45%; raw = 3717.5/4
        assert 44 <= _battery_raw_to_pct(929.375) <= 46

    @pytest.mark.parametrize("raw", [0, -1, None])
    def test_invalid_returns_none(self, raw):
        assert _battery_raw_to_pct(raw) is None


class TestCalibrateAndSmooth:
    def test_without_calibration_is_identity(self):
        mgr = BLEManager()
        out = mgr._calibrate_and_smooth([100.0, 200.0, 300.0])
        assert out == [100.0, 200.0, 300.0]

    def test_applies_k_sensor(self):
        mgr = BLEManager()
        mgr._calibration = CalibrationData(k_sensor=[2.0, 0.5, 1.0])
        out = mgr._calibrate_and_smooth([100.0, 200.0, 300.0])
        assert out == [200.0, 100.0, 300.0]

    def test_low_pass_filter_blends_with_previous(self):
        mgr = BLEManager()
        mgr._prev_channels = [0.0, 0.0]
        out = mgr._calibrate_and_smooth([100.0, 200.0])
        # LPF_ALPHA=0.3 → 0.3*prev + 0.7*cur = 70, 140
        assert out == [70.0, 140.0]

    def test_smoothing_skipped_on_length_change(self):
        mgr = BLEManager()
        mgr._prev_channels = [1.0, 2.0, 3.0]
        out = mgr._calibrate_and_smooth([10.0, 20.0])
        assert out == [10.0, 20.0]


class TestComputeMetrics:
    def test_g4_branch_returns_all_keys(self):
        channels = [100.0] * 9
        metrics = BLEManager._compute_metrics(channels, is_g4=True)
        for key in ("lux", "cct", "duv", "cie_x", "cie_y", "u_prime", "v_prime",
                    "ra", "r_values", "eml", "cs", "light_mode"):
            assert key in metrics

    def test_g3_branch_returns_all_keys(self):
        channels = [200.0, 400.0, 500.0, 450.0, 380.0, 300.0]
        metrics = BLEManager._compute_metrics(channels, is_g4=False)
        assert metrics["cs"] is None
        assert metrics["light_mode"] in ("mono", "incandescent", "general")
        assert len(metrics["r_values"]) == 14


def _make_chunks(waveform: list[float], data_type: int) -> list[RawFlickerChunk]:
    """Slice a 1024-sample waveform into the 4 page chunks the G4 produces."""
    assert len(waveform) == G4_FLICKER_TOTAL_SAMPLES
    stride = G4_FLICKER_FULL_GROUPS * 4
    return [
        RawFlickerChunk(
            page=page,
            data_type=data_type,
            samples=waveform[
                page * stride : page * stride
                + (G4_FLICKER_LAST_GROUPS * 4 if page == G4_FLICKER_LAST_PAGE else stride)
            ],
        )
        for page in range(G4_FLICKER_LAST_PAGE + 1)
    ]


class TestFlickerChunkAssembly:
    def test_resolves_future_only_after_all_4_pages(self):
        mgr = BLEManager()
        loop = asyncio.new_event_loop()
        try:
            mgr._flicker_future = loop.create_future()
            wave = [100.0] * G4_FLICKER_TOTAL_SAMPLES
            chunks = _make_chunks(wave, data_type=2)

            for chunk in chunks[:3]:
                mgr._handle_flicker_chunk(chunk)
                assert not mgr._flicker_future.done()

            mgr._handle_flicker_chunk(chunks[3])
            assert mgr._flicker_future.done()
            raw = mgr._flicker_future.result()
            assert len(raw.waveform) == G4_FLICKER_TOTAL_SAMPLES
            assert raw.data_type == 2
        finally:
            loop.close()

    def test_assembled_waveform_preserves_per_page_samples(self):
        mgr = BLEManager()
        loop = asyncio.new_event_loop()
        try:
            mgr._flicker_future = loop.create_future()
            # Distinct ramp per page so we can spot-check ordering.
            wave = [float(i) for i in range(G4_FLICKER_TOTAL_SAMPLES)]
            for chunk in _make_chunks(wave, data_type=0):
                mgr._handle_flicker_chunk(chunk)
            raw = mgr._flicker_future.result()
            assert raw.waveform == wave
        finally:
            loop.close()

    def test_low_modulation_signal_round_trip(self):
        """A 1% sine on a high baseline must read as ~1% mod after assembly."""
        mgr = BLEManager()
        loop = asyncio.new_event_loop()
        try:
            mgr._flicker_future = loop.create_future()
            wave = [
                100.0 + 1.0 * math.sin(2 * math.pi * i / 256)
                for i in range(G4_FLICKER_TOTAL_SAMPLES)
            ]
            for chunk in _make_chunks(wave, data_type=2):
                mgr._handle_flicker_chunk(chunk)

            flicker = mgr._process_flicker(mgr._flicker_future.result())
            assert flicker.modulation_pct < 3.0, flicker.modulation_pct
            assert flicker.flicker_index < 0.05
        finally:
            loop.close()


class _FakeConnection:
    """Minimal stand-in for BLEConnection that records every write."""

    def __init__(self):
        self.writes: list[tuple[str, bytes]] = []
        self.is_connected = True

    async def write(self, uuid: str, data: bytes) -> None:
        self.writes.append((uuid, bytes(data)))


def _fake_flicker(freq_hz: float) -> FlickerData:
    """Build a FlickerData with just the field the cascade looks at."""
    return FlickerData(
        frequency_hz=freq_hz,
        modulation_pct=0.0,
        flicker_index=0.0,
        risk_level=FlickerRiskLevel.NO_RISK,
        waveform=[],
        fft_freq=[],
        fft_mag=[],
    )


class TestRequestFlickerPayload:
    """The REQ_FREQ body must encode the period byte the device expects."""

    def _last_inner_payload(self, conn: _FakeConnection) -> bytes:
        """Strip BLE fragmentation + 11-byte NUS header from the captured frame."""
        # Single-fragment SINGLE frame: [0x00, len_hi, len_lo, ...inner...]
        frame = conn.writes[-1][1]
        inner = frame[3:]
        return inner[11:]

    @pytest.mark.parametrize("period", [
        G4_FLICKER_PERIOD_25,
        G4_FLICKER_PERIOD_146,
        G4_FLICKER_PERIOD_11,
    ])
    def test_payload_encodes_period_as_uint16_be(self, period):
        loop = asyncio.new_event_loop()
        try:
            mgr = BLEManager()
            mgr._connection = _FakeConnection()
            # Resolve immediately so the request doesn't hang on the future.
            future = loop.create_future()
            future.set_result(None)  # _process_flicker tolerates None? No — short-circuit instead.

            async def fake_send(opcode, payload=b""):
                # Capture by going through the real path so encoding is exercised.
                from opple_bridge.ble.protocol import build_command, encapsulate
                inner = build_command(opcode, payload, seq_no=0)
                for frame in encapsulate(inner):
                    await mgr._connection.write("uuid", frame)

            mgr._send_command = fake_send  # type: ignore[method-assign]

            async def runner():
                # Drive _request_flicker_once just up to the send; cancel the wait.
                task = loop.create_task(mgr._request_flicker_once(period))
                await asyncio.sleep(0)  # let it start
                # The future is awaiting; cancel cleanly.
                if mgr._flicker_future and not mgr._flicker_future.done():
                    mgr._flicker_future.set_exception(asyncio.CancelledError())
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            loop.run_until_complete(runner())

            payload = self._last_inner_payload(mgr._connection)
            assert payload == bytes([0x00, (period >> 8) & 0xFF, period & 0xFF])
        finally:
            loop.close()


class TestFlickerCascade:
    """Verify the 25 → 146 → 11 escalation logic from the OPPLE app."""

    def _run(self, mgr: BLEManager):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(mgr.request_flicker())
        finally:
            loop.close()

    def _stub_cascade(self, mgr: BLEManager, freqs: dict[int, float]):
        """Make _request_flicker_once return canned FlickerData per period."""
        calls: list[int] = []

        async def fake_once(period):
            calls.append(period)
            return _fake_flicker(freqs[period])

        mgr._connection = _FakeConnection()
        mgr._request_flicker_once = fake_once  # type: ignore[method-assign]
        return calls

    def test_low_frequency_returns_period_25_only(self):
        mgr = BLEManager()
        calls = self._stub_cascade(mgr, {G4_FLICKER_PERIOD_25: 100.0})
        result = self._run(mgr)
        assert result is not None
        assert result.frequency_hz == 100.0
        assert calls == [G4_FLICKER_PERIOD_25]

    def test_mid_frequency_escalates_to_146_then_11_and_keeps_146(self):
        mgr = BLEManager()
        calls = self._stub_cascade(mgr, {
            G4_FLICKER_PERIOD_25: 5000.0,
            G4_FLICKER_PERIOD_146: 4500.0,
            G4_FLICKER_PERIOD_11: 4500.0,  # below 15 kHz → fall back
        })
        result = self._run(mgr)
        assert result is not None
        assert result.frequency_hz == 4500.0
        assert calls == [
            G4_FLICKER_PERIOD_25,
            G4_FLICKER_PERIOD_146,
            G4_FLICKER_PERIOD_11,
        ]

    def test_high_frequency_uses_period_11(self):
        """Switching-PSU case: app reads 28 kHz, must come from period-11 mode."""
        mgr = BLEManager()
        calls = self._stub_cascade(mgr, {
            G4_FLICKER_PERIOD_25: 5000.0,
            G4_FLICKER_PERIOD_146: 5000.0,  # alias / wrong band
            G4_FLICKER_PERIOD_11: 28174.0,  # the real frequency
        })
        result = self._run(mgr)
        assert result is not None
        assert result.frequency_hz == 28174.0
        assert calls == [
            G4_FLICKER_PERIOD_25,
            G4_FLICKER_PERIOD_146,
            G4_FLICKER_PERIOD_11,
        ]

    def test_period_25_failure_returns_none(self):
        mgr = BLEManager()

        async def fake_once(period):
            return None

        mgr._connection = _FakeConnection()
        mgr._request_flicker_once = fake_once  # type: ignore[method-assign]
        assert self._run(mgr) is None


class TestProcessMeasurementAssembly:
    def test_latest_is_populated(self):
        mgr = BLEManager()
        raw = RawMeasurement(
            raw_channels=[200.0, 400.0, 500.0, 450.0, 380.0, 300.0],
            battery_voltage=4000.0,
        )
        mgr._process_measurement(raw)
        assert mgr._latest is not None
        assert mgr._latest.lux >= 0
        assert len(mgr._latest.spectrum) == 6
