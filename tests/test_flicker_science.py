"""Regression tests for the flicker FFT path.

These tests pin a real-device bug observed against the OPPLE app: ``fft()``
used to apply a Hann window directly to the raw 12-bit ADC waveform without
first removing the per-data_type DC baseline, which leaked the DC pedestal
into bin 1 and made ``dominant_frequency`` return the bin-1 frequency
(~39 Hz on period 25) for any low-modulation signal — including the 28 kHz
switching-PSU LED that prompted this fix.

Each synthetic test below was hand-checked against the OPPLE app's reference
pipeline (opple-js-decompiled.js:2497888-2498164): AC-couple → FFT (no window)
→ skip DC → peak bin → ``freq = peak_bin * fs / N``.
"""
from __future__ import annotations

import math

from opple_bridge.ble.parser import (
    G4_FLICKER_PERIOD_11,
    G4_FLICKER_PERIOD_25,
    G4_FLICKER_TOTAL_SAMPLES,
    period_to_sample_rate,
)
from opple_bridge.science.flicker import dominant_frequency, fft

N = G4_FLICKER_TOTAL_SAMPLES  # 1024
FS_25 = period_to_sample_rate(G4_FLICKER_PERIOD_25)  # 40329.85 Hz
FS_11 = period_to_sample_rate(G4_FLICKER_PERIOD_11)  # 85354.17 Hz

# data_type 2 → DC offset 13.8447265625 (see flicker._DC_OFFSETS).
DC_TYPE_2 = 13.8447265625


def _synth_sine(dc: float, amplitude: float, freq_hz: float, fs: float, n: int) -> list[float]:
    """Build a constant + sine waveform sampled at fs (n samples)."""
    return [dc + amplitude * math.sin(2.0 * math.pi * freq_hz * i / fs) for i in range(n)]


def _bin_width(fs: float) -> float:
    return fs / N


class TestFftDominantFrequency:
    """``fft`` + ``dominant_frequency`` must recover the input frequency.

    Pre-fix all four of these tests fail because Hann-windowed DC dumps energy
    into bin 1 and ``dominant_frequency`` always returns ~39.4 Hz (period 25)
    or ~83.4 Hz (period 11).
    """

    def test_5khz_sine_on_period_25(self):
        # 5000 Hz, well inside period-25 Nyquist (20 165 Hz). Easy case.
        wave = _synth_sine(dc=80.0, amplitude=20.0, freq_hz=5000.0, fs=FS_25, n=N)
        _, mags = fft(wave, data_type=2)
        freq = dominant_frequency(mags, FS_25, N)
        assert abs(freq - 5000.0) < _bin_width(FS_25), (
            f"expected ~5000 Hz, got {freq:.1f} Hz "
            f"(bin width {_bin_width(FS_25):.2f} Hz)"
        )

    def test_28174hz_sine_on_period_11(self):
        # The user's actual case: 28 174 Hz LED switching PSU. Period 11 has
        # Nyquist 42 677 Hz so this signal is observable directly.
        wave = _synth_sine(dc=80.0, amplitude=20.0, freq_hz=28174.0, fs=FS_11, n=N)
        _, mags = fft(wave, data_type=2)
        freq = dominant_frequency(mags, FS_11, N)
        assert abs(freq - 28174.0) < _bin_width(FS_11), (
            f"expected ~28174 Hz, got {freq:.1f} Hz "
            f"(bin width {_bin_width(FS_11):.2f} Hz)"
        )

    def test_low_modulation_100hz_on_period_25(self):
        # 4 % modulation (amplitude 1.0 on DC 25.0 → ~4 % MD after AC-coupling).
        # Pre-fix: bin 1 leakage wins → returns ~39 Hz.
        # Post-fix: real peak at bin 3 (~118 Hz) wins.
        wave = _synth_sine(dc=25.0, amplitude=1.0, freq_hz=100.0, fs=FS_25, n=N)
        _, mags = fft(wave, data_type=2)
        freq = dominant_frequency(mags, FS_25, N)
        # Allow ±2 bins of tolerance because 100 Hz lands between bins 2 and 3.
        assert abs(freq - 100.0) < 2 * _bin_width(FS_25), (
            f"expected ~100 Hz, got {freq:.1f} Hz "
            f"(bin width {_bin_width(FS_25):.2f} Hz)"
        )

    def test_dc_only_waveform_has_no_spectral_energy(self):
        # A constant waveform at the data_type=2 baseline AC-couples to all
        # zeros. With no window, every FFT bin should be ~0 — the smoking gun
        # that bin 1 was a Hann-window leakage artefact, not a real peak.
        wave = [DC_TYPE_2] * N
        _, mags = fft(wave, data_type=2)
        peak = max(mags)
        assert peak < 1e-9, (
            f"DC-only AC-coupled waveform should have no spectral energy, "
            f"max bin magnitude was {peak:.6e}"
        )
