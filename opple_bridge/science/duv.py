"""Delta uv (Duv) calculation — distance from the Planckian locus.

Uses the Ohno (2014) polynomial method based on ANSI C78.377-2011.
Input is CIE 1960 UCS (u, v), NOT CIE 1976 (u', v').
"""
from __future__ import annotations

import math


def duv_from_uv(u: float, v: float) -> float:
    """Compute Duv from CIE 1960 (u, v) coordinates.

    Positive Duv = above the Planckian locus (greenish tint).
    Negative Duv = below the Planckian locus (pinkish tint).

    Reference: Ohno, Y. (2014), "Practical Use and Calculation of CCT and Duv",
    LEUKOS, 10:1, 47-55.
    """
    k = [
        -0.471106, 1.925865, -2.4243787,
        1.5317403, -0.5179722, 0.0893944,
        -0.00616793,
    ]

    # Distance from approximate center of Planckian locus
    du = u - 0.292
    dv = v - 0.24
    lfp = math.sqrt(du * du + dv * dv)

    if lfp == 0:
        return 0.0

    a = math.acos(du / lfp)

    # Polynomial fit of Planckian locus distance at angle a
    lbb = (k[6] * a**6 + k[5] * a**5 + k[4] * a**4 +
           k[3] * a**3 + k[2] * a**2 + k[1] * a + k[0])

    return lfp - lbb
