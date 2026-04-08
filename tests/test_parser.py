"""Tests for the NUS byte-level parser (G3 vs G4 auto-detection)."""
import struct

from opple_bridge.ble.parser import (
    G4_FLICKER_FULL_GROUPS,
    G4_FLICKER_LAST_GROUPS,
    G4_FLICKER_LAST_PAGE,
    G4_FLICKER_PERIOD_11,
    G4_FLICKER_PERIOD_25,
    G4_FLICKER_PERIOD_146,
    G4_FLICKER_TOTAL_SAMPLES,
    G4_FLICKER_WAVE_OFFSET,
    parse_calibration,
    parse_flicker_chunk,
    parse_measurement,
    parse_opcode,
    period_to_sample_rate,
)


def _header(opcode: int, payload_len: int) -> bytes:
    return bytes([
        0x00, 0x13, 0x00, 0x00,
        0x01,
        0x00,
        payload_len & 0xFF,
        0x00, 0x00,
        (opcode >> 8) & 0xFF, opcode & 0xFF,
    ])


def _g3_measurement_payload() -> bytes:
    skip = bytes([0x00])
    channels = b"".join(ch.to_bytes(2, "big") for ch in [100, 200, 300, 400, 500, 600])
    power = (3900).to_bytes(2, "big")
    temp = bytes([23])  # ambient-temperature byte: still in the wire format, ignored by the parser
    return skip + channels + power + temp


def _g4_measurement_payload() -> bytes:
    skip = bytes([0x00])
    channels = b"".join(ch.to_bytes(2, "big") for ch in [100, 200, 300, 400, 500, 600, 700, 800, 900])
    padding = bytes([0x00, 0x00])
    power = (3344).to_bytes(2, "big")  # observed real-device value, fully charged
    return skip + channels + padding + power


class TestParseOpcode:
    def test_extracts_big_endian_opcode(self):
        data = _header(0x0A01, 0) + b""
        assert parse_opcode(data) == 0x0A01

    def test_returns_zero_for_short_data(self):
        assert parse_opcode(b"\x00\x01") == 0


class TestParseMeasurement:
    def test_g3_payload(self):
        data = _header(0x0A01, 16) + _g3_measurement_payload()
        result = parse_measurement(data)
        assert result is not None
        assert not result.is_g4
        assert result.raw_channels == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]
        assert result.battery_voltage == 3900.0

    def test_g4_payload_detected_by_length(self):
        data = _header(0x0A01, 23) + _g4_measurement_payload()
        result = parse_measurement(data)
        assert result is not None
        assert result.is_g4
        assert len(result.raw_channels) == 9
        assert result.raw_channels[0] == 100.0
        assert result.raw_channels[8] == 900.0
        assert result.battery_voltage == 3344.0

    def test_truncated_returns_none(self):
        assert parse_measurement(b"\x00" * 10) is None


def _pack_4_samples_to_6_bytes(s: list[int]) -> bytes:
    """Inverse of the parser's 12-bit unpack: 4 sample × 12 bits → 6 bytes.

    Mirrors the layout used by `dealReadFreq` in the JS firmware so the
    parser can be exercised end-to-end with synthetic chunks.
    """
    s0, s1, s2, s3 = (v & 0xFFF for v in s)
    a = (s0 << 4) | (s1 >> 8)
    b = ((s1 & 0xFF) << 8) | (s2 >> 4)
    c = ((s2 & 0x0F) << 12) | s3
    return bytes([
        (a >> 8) & 0xFF, a & 0xFF,
        (b >> 8) & 0xFF, b & 0xFF,
        (c >> 8) & 0xFF, c & 0xFF,
    ])


def _flicker_chunk_payload(page: int, data_type: int, samples: list[int]) -> bytes:
    """Build the bytes that follow the 11-byte NUS header for one flicker chunk."""
    header = bytearray(G4_FLICKER_WAVE_OFFSET)
    header[1] = page
    header[2] = data_type
    groups = G4_FLICKER_LAST_GROUPS if page == G4_FLICKER_LAST_PAGE else G4_FLICKER_FULL_GROUPS
    assert len(samples) == groups * 4
    wave = b"".join(
        _pack_4_samples_to_6_bytes(samples[i * 4 : i * 4 + 4]) for i in range(groups)
    )
    return bytes(header) + wave


class TestParseFlickerChunk:
    def test_full_chunk_round_trip(self):
        """Page 0 chunk: 65 groups × 4 samples = 260 samples, exact round-trip."""
        samples = [(i * 13 + 7) & 0xFFF for i in range(G4_FLICKER_FULL_GROUPS * 4)]
        payload = _flicker_chunk_payload(page=0, data_type=2, samples=samples)
        data = _header(0x0A0B, len(payload)) + payload
        chunk = parse_flicker_chunk(data)
        assert chunk is not None
        assert chunk.page == 0
        assert chunk.data_type == 2
        assert len(chunk.samples) == G4_FLICKER_FULL_GROUPS * 4
        assert [int(s) for s in chunk.samples] == samples

    def test_last_chunk_has_244_samples(self):
        """Page 3 chunk: 61 groups × 4 = 244 samples."""
        samples = [(i * 5 + 1) & 0xFFF for i in range(G4_FLICKER_LAST_GROUPS * 4)]
        payload = _flicker_chunk_payload(page=3, data_type=0, samples=samples)
        data = _header(0x0A0B, len(payload)) + payload
        chunk = parse_flicker_chunk(data)
        assert chunk is not None
        assert chunk.page == 3
        assert chunk.data_type == 0
        assert len(chunk.samples) == G4_FLICKER_LAST_GROUPS * 4

    def test_data_type_extracted_from_byte_2(self):
        """The flicker range (selects DC offset) sits at payload[2], not [1]."""
        samples = [0] * (G4_FLICKER_FULL_GROUPS * 4)
        payload = _flicker_chunk_payload(page=1, data_type=1, samples=samples)
        chunk = parse_flicker_chunk(_header(0x0A0B, len(payload)) + payload)
        assert chunk is not None
        assert chunk.page == 1
        assert chunk.data_type == 1

    def test_invalid_page_returns_none(self):
        payload = bytearray(G4_FLICKER_WAVE_OFFSET + 6 * G4_FLICKER_FULL_GROUPS)
        payload[1] = 7
        chunk = parse_flicker_chunk(_header(0x0A0B, len(payload)) + bytes(payload))
        assert chunk is None

    def test_truncated_returns_none(self):
        assert parse_flicker_chunk(b"\x00" * 12) is None


class TestPeriodToSampleRate:
    """Verify the FFT sample rate matches the JS frequency formula.

    The OPPLE app computes flicker frequency as `peakBin * 1024 / time_factor`
    where time_factor is 26/150/12.285 for periods 25/146/11. We re-cast as
    `fs = N² / time_factor` so the standard `bin * fs / N` formula gives the
    same answer (see opple-js-decompiled.js:2498152-2498158).
    """

    def test_period_25_matches_broad_scan(self):
        # 1024² / 26 ≈ 40330 Hz; covers up to ~20 kHz Nyquist.
        assert abs(period_to_sample_rate(G4_FLICKER_PERIOD_25) - 40329.85) < 0.1

    def test_period_146_matches_fine_resolution(self):
        # 1024² / 150 ≈ 6991 Hz; ~6.8 Hz bin spacing for low-frequency precision.
        assert abs(period_to_sample_rate(G4_FLICKER_PERIOD_146) - 6990.51) < 0.1

    def test_period_11_matches_high_frequency(self):
        # 1024² / 12.285 ≈ 85354 Hz; required to capture ~30 kHz switching PSUs.
        assert abs(period_to_sample_rate(G4_FLICKER_PERIOD_11) - 85354.23) < 0.1

    def test_unknown_period_falls_back_to_default(self):
        assert period_to_sample_rate(999) == period_to_sample_rate(G4_FLICKER_PERIOD_25)

    def test_freq_formula_round_trip(self):
        """`bin * fs / N` should reproduce the JS `bin * 1024 / time_factor`."""
        n = G4_FLICKER_TOTAL_SAMPLES
        for period, factor in ((25, 26.0), (146, 150.0), (11, 12.285)):
            fs = period_to_sample_rate(period)
            for peak_bin in (1, 50, 338, 500):
                ours = peak_bin * fs / n
                js = peak_bin * 1024 / factor
                assert abs(ours - js) < 1e-6, (period, peak_bin, ours, js)


class TestParseCalibration:
    def test_g3_seven_factors(self):
        k = [1.01, 1.02, 0.98, 1.03, 0.99, 1.04, 1.0]
        payload = bytes([0x00]) + b"".join(struct.pack("<f", v) for v in k)
        data = _header(0x0A05, len(payload)) + payload
        calib = parse_calibration(data)
        assert calib is not None
        assert len(calib.k_sensor) == 7
        for actual, expected in zip(calib.k_sensor, k):
            assert abs(actual - expected) < 1e-5

    def test_g4_nine_factors(self):
        k = [1.010141, 1.009422, 0.928753, 1.037585, 0.968898,
             1.181077, 0.961893, 1.059147, 1.0]
        payload = bytes([0x00]) + b"".join(struct.pack("<f", v) for v in k)
        data = _header(0x0A05, len(payload)) + payload
        calib = parse_calibration(data)
        assert calib is not None
        assert len(calib.k_sensor) == 9
        for actual, expected in zip(calib.k_sensor, k):
            assert abs(actual - expected) < 1e-5
