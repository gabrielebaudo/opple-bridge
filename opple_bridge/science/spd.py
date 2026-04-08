"""Spectral Power Distribution interpolation.

Interpolates 6-channel sensor data (450-650nm) to a full SPD (380-780nm at 5nm).
Uses natural cubic spline interpolation.
"""
from __future__ import annotations

from opple_bridge.science.data import N_WAVELENGTHS, SENSOR_WAVELENGTHS, WL_START, WL_STEP


def _natural_cubic_spline(xs: list[float], ys: list[float]) -> list[float]:
    """Compute natural cubic spline coefficients (second derivatives).

    Returns the 'ks' array (knot derivatives) for spline evaluation.
    """
    n = len(xs)
    # Build tridiagonal system for natural spline
    a = [0.0] * n
    b = [0.0] * n
    c = [0.0] * n
    d = [0.0] * n

    # Natural spline: second derivative = 0 at endpoints
    a[0] = 0.0
    b[0] = 2.0 / (xs[1] - xs[0])
    c[0] = 1.0 / (xs[1] - xs[0])
    d[0] = 3.0 * (ys[1] - ys[0]) / ((xs[1] - xs[0]) ** 2)

    for i in range(1, n - 1):
        h0 = xs[i] - xs[i - 1]
        h1 = xs[i + 1] - xs[i]
        a[i] = 1.0 / h0
        b[i] = 2.0 * (1.0 / h0 + 1.0 / h1)
        c[i] = 1.0 / h1
        d[i] = 3.0 * ((ys[i] - ys[i - 1]) / (h0 * h0) + (ys[i + 1] - ys[i]) / (h1 * h1))

    a[n - 1] = 1.0 / (xs[n - 1] - xs[n - 2])
    b[n - 1] = 2.0 / (xs[n - 1] - xs[n - 2])
    c[n - 1] = 0.0
    d[n - 1] = 3.0 * (ys[n - 1] - ys[n - 2]) / ((xs[n - 1] - xs[n - 2]) ** 2)

    # Forward sweep
    for i in range(1, n):
        m = a[i] / b[i - 1]
        b[i] -= m * c[i - 1]
        d[i] -= m * d[i - 1]

    # Back substitution
    ks = [0.0] * n
    ks[n - 1] = d[n - 1] / b[n - 1]
    for i in range(n - 2, -1, -1):
        ks[i] = (d[i] - c[i] * ks[i + 1]) / b[i]

    return ks


def _spline_eval(xs: list[float], ys: list[float], ks: list[float], x: float) -> float:
    """Evaluate the cubic spline at point x."""
    # Find the right interval
    i = len(xs) - 2
    for j in range(1, len(xs)):
        if x <= xs[j]:
            i = j - 1
            break

    h = xs[i + 1] - xs[i]
    t = (x - xs[i]) / h
    a = ks[i] * h - (ys[i + 1] - ys[i])
    b = -ks[i + 1] * h + (ys[i + 1] - ys[i])
    return (1 - t) * ys[i] + t * ys[i + 1] + t * (1 - t) * (a * (1 - t) + b * t)


def interpolate_spd(channels: list[float]) -> list[float]:
    """Interpolate 6 sensor channels to an 81-point SPD (380-780nm at 5nm).

    Args:
        channels: 6 values at [450, 500, 550, 570, 600, 650] nm.

    Returns:
        81 spectral values at 5nm intervals from 380 to 780nm.
    """
    if len(channels) != 6:
        raise ValueError(f"Expected 6 channels, got {len(channels)}")

    # Build control points with boundary extensions
    xs = [float(WL_START)] + [float(w) for w in SENSOR_WAVELENGTHS] + [780.0]
    ys = [0.0] + list(channels) + [channels[-1]]  # Zero at 380, extend last at 780

    ks = _natural_cubic_spline(xs, ys)

    spd = []
    for i in range(N_WAVELENGTHS):
        wl = WL_START + i * WL_STEP
        val = max(0.0, _spline_eval(xs, ys, ks, float(wl)))
        spd.append(val)

    return spd
