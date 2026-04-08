"""IEEE PAR1789-2015 flicker risk assessment.

Classifies light flicker risk from frequency and modulation depth using the
two recommended-practice thresholds:

    no-risk threshold  : Mod% = 0.033 * max(10, f)
    low-risk threshold : Mod% = 0.080 * max(10, f)

The ``max(10, f)`` clamp produces a horizontal floor below 10 Hz and a
straight diagonal above, matching the IEEE 1789-2015 chart and the OPPLE
companion app. Modulation at or below the no-risk line is classified as
NO_RISK; between the two lines is LOW_RISK; above the low-risk line is
HIGH_RISK.
"""
from __future__ import annotations

from opple_bridge.models import FlickerRiskLevel

_NO_RISK_SLOPE = 0.033
_LOW_RISK_SLOPE = 0.080
_FLOOR_HZ = 10.0


def _no_risk_limit(frequency_hz: float) -> float:
    """Modulation % at or below which flicker has no observable effect."""
    return _NO_RISK_SLOPE * max(_FLOOR_HZ, frequency_hz)


def _low_risk_limit(frequency_hz: float) -> float:
    """Modulation % at or below which flicker is considered low risk."""
    return _LOW_RISK_SLOPE * max(_FLOOR_HZ, frequency_hz)


def assess_risk(frequency_hz: float, modulation_pct: float) -> FlickerRiskLevel:
    """Assess flicker risk per IEEE PAR1789-2015.

    Args:
        frequency_hz: Fundamental flicker frequency.
        modulation_pct: Modulation depth as a percentage (0-100).
    """
    if frequency_hz <= 0 or modulation_pct <= 0:
        return FlickerRiskLevel.NO_RISK

    if modulation_pct <= _no_risk_limit(frequency_hz):
        return FlickerRiskLevel.NO_RISK
    if modulation_pct <= _low_risk_limit(frequency_hz):
        return FlickerRiskLevel.LOW_RISK
    return FlickerRiskLevel.HIGH_RISK
