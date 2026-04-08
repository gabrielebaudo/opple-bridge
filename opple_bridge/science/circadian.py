"""Circadian metrics: EML (Equivalent Melanopic Lux).

Uses linear channel coefficients from the Opple Light Master firmware,
as documented in the open-light-master project.
"""
from __future__ import annotations


# EML coefficients for three CCT/mode regimes
# Channels: V1(450), B1(500), G1(550), Y1(570), O1(600), R1(650)
_EML_COEFF_LOW_INCANDESCENT = [-11.1321, 10.088, 10.5399, -4.9714, -4.2457, 1.3921]
_EML_COEFF_LOW_GENERAL = [0.1157, 0.543, 0.1886, 0.02516, -0.0825, -0.007316]
_EML_COEFF_HIGH = [-0.005224, 0.3113, 0.3649, 0.3632, -0.4313, 0.05123]


def compute_eml(channels: list[float], cct: float,
                is_incandescent: bool = False) -> float:
    """Compute Equivalent Melanopic Lux from 6 sensor channels.

    Args:
        channels: 6 raw sensor values at [450, 500, 550, 570, 600, 650] nm.
        cct: Correlated Color Temperature in Kelvin.
        is_incandescent: Whether the light source is incandescent.

    Returns:
        EML value (clamped to >= 0).
    """
    if len(channels) < 6:
        return 0.0

    if cct < 4000:
        if cct < 3000 and is_incandescent:
            coeffs = _EML_COEFF_LOW_INCANDESCENT
        else:
            coeffs = _EML_COEFF_LOW_GENERAL
    else:
        coeffs = _EML_COEFF_HIGH

    eml = sum(c * ch for c, ch in zip(coeffs, channels))
    return max(0.0, eml)
