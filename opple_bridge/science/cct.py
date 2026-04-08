"""Correlated Color Temperature calculation."""
from __future__ import annotations


def cct_from_xy(x: float, y: float) -> float:
    """Compute CCT from CIE 1931 xy using McCamy's approximation.

    Valid for approximately 2000K - 12500K.

    Reference: McCamy, C.S., "Correlated color temperature as an explicit
    function of chromaticity coordinates", Color Research & Application, 1992.
    """
    if y == 0:
        return 0.0

    n = (x - 0.3320) / (0.1858 - y)
    cct = 449.0 * n**3 + 3525.0 * n**2 + 6823.3 * n + 5520.33
    return max(0.0, cct)
