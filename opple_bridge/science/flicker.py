"""Flicker analysis: modulation depth, flicker index, and FFT.

Replicates the algorithm of the OPPLE app's `dealFreqMeasureData`
(opple-js-decompiled.js:2497900-2498130). The raw 12-bit waveform from
the G4 carries a per-`data_type` ADC baseline that must be removed
before any analysis, otherwise the smallest samples sit on the baseline
instead of zero (modulation depth blows up to ~56% vs the app's ~1%) and
the FFT spends most of its energy in bin 0 — leaking into bin 1 and
making `dominant_frequency` pick bin 1 as a spurious peak (we observed
39 Hz vs the app's 28 kHz).

Pipeline (every helper that touches the waveform must run step 1 first):
1. AC-couple: subtract a `data_type`-specific DC offset and clip negatives.
2. Modulation depth: TIME-DOMAIN sort → (avg_largest_30 - avg_smallest_30)
   / (avg_largest_30 + avg_smallest_30) * 100. The OPPLE app uses the same
   sort-based metric on the post-AC-coupling samples, NOT on FFT bins.
3. Flicker index: `sum(max(0, s - mean)) / sum(s)` on the AC-coupled wave.
4. FFT: bare DFT on the AC-coupled wave (no window — the OPPLE app's JS
   path also applies no window; an earlier version of this module used
   Hann, which leaked DC into bin 1 and is the bug above).
"""
from __future__ import annotations

import math


# DC offsets per data_type, transcribed from opple-js-decompiled.js:2497963-2497972.
# data_type 2/3/other share the same baseline; only 0 and 1 have their own.
_DC_OFFSETS = {0: 29.7412109375, 1: 15.8720703125}
_DC_OFFSET_DEFAULT = 13.8447265625


def _ac_couple(waveform: list[float], data_type: int) -> list[float]:
    """Subtract the data_type-specific ADC baseline and clip negatives to 0.

    Mirrors the half-wave rectification step at js:2497989-2497998.
    """
    dc = _DC_OFFSETS.get(data_type, _DC_OFFSET_DEFAULT)
    return [s - dc if s > dc else 0.0 for s in waveform]


def modulation_depth(waveform: list[float], data_type: int) -> float:
    """Compute percent modulation depth in the time domain.

    AC-couples the waveform (subtract data_type DC offset, clip negatives),
    sorts the samples, then computes
        (avg_largest_30 - avg_smallest_30) / (avg_largest_30 + avg_smallest_30) * 100
    matching opple-js-decompiled.js:2498042-2498072 exactly.

    The 30-sample averaging makes the metric robust against single-sample
    spikes; the AC-coupling step is what brings the smallest samples down
    to zero for a fully-modulated signal.

    Returns value in percent (0-99.5).
    """
    if len(waveform) < 60:
        return 0.0

    processed = _ac_couple(waveform, data_type)
    if max(processed) <= 0.0:
        return 0.0

    sorted_samples = sorted(processed)
    count = min(30, len(sorted_samples))
    smallest_avg = sum(sorted_samples[:count]) / count
    largest_avg = sum(sorted_samples[-count:]) / count

    denom = largest_avg + smallest_avg
    if denom <= 0.0:
        return 0.0

    md = (largest_avg - smallest_avg) / denom * 100.0
    return min(99.5, max(0.0, md))


def flicker_index(waveform: list[float], data_type: int) -> float:
    """Compute flicker index in the time domain, OPPLE-app style.

    Uses Rea's definition on the AC-coupled waveform:
        FI = sum(max(0, s - mean)) / sum(s)
    This mirrors the reduce loop at opple-js-decompiled.js:2498091-2498116.

    Returns value 0 to 1.
    """
    if len(waveform) < 8:
        return 0.0

    processed = _ac_couple(waveform, data_type)
    total = sum(processed)
    if total <= 0.0:
        return 0.0

    avg = total / len(processed)
    above = sum(s - avg for s in processed if s > avg)
    return above / total


def fft(waveform: list[float], data_type: int) -> tuple[list[float], list[float]]:
    """Compute FFT magnitudes of the AC-coupled waveform.

    AC-couples the input via ``_ac_couple`` (subtract the data_type DC
    offset, half-wave rectify) before computing a bare DFT — matching the
    OPPLE app's JS pipeline exactly. No window is applied: windowing the
    raw, DC-laden 12-bit waveform was the bug that leaked DC into bin 1
    and made ``dominant_frequency`` always return ~39 Hz on period 25.

    Args:
        waveform: Raw time-domain samples (the 12-bit ADC counts the device
            delivers — *not* already AC-coupled).
        data_type: Device-reported flicker range (selects DC offset).

    Returns:
        (frequency_bins, magnitudes). Frequencies are in *bin indices*
        (0..N/2-1); the caller scales by ``sample_rate / N`` to get Hz.
        Bin 0 (DC) is included so the dashboard can render it; downstream
        peak detection in ``dominant_frequency`` skips it explicitly.
    """
    n = len(waveform)
    if n == 0:
        return [], []

    processed = _ac_couple(waveform, data_type)

    half = n // 2
    magnitudes = []
    for k in range(half):
        re = 0.0
        im = 0.0
        for t in range(n):
            angle = -2.0 * math.pi * k * t / n
            re += processed[t] * math.cos(angle)
            im += processed[t] * math.sin(angle)
        mag = math.sqrt(re * re + im * im) / n
        magnitudes.append(mag)

    freq_bins = list(range(half))
    return freq_bins, magnitudes


def dominant_frequency(magnitudes: list[float], sample_rate: float, n_samples: int) -> float:
    """Find the dominant frequency from FFT magnitudes.

    Args:
        magnitudes: FFT magnitude array (N/2 values).
        sample_rate: Sample rate in Hz.
        n_samples: Total number of samples.

    Returns:
        Dominant frequency in Hz (excluding DC bin 0).
    """
    if len(magnitudes) < 2:
        return 0.0

    # Skip DC (bin 0), find peak
    peak_bin = 1
    peak_val = magnitudes[1]
    for i in range(2, len(magnitudes)):
        if magnitudes[i] > peak_val:
            peak_val = magnitudes[i]
            peak_bin = i

    return peak_bin * sample_rate / n_samples
