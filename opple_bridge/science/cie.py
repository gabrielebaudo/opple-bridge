"""CIE color space conversions."""
from __future__ import annotations

from opple_bridge.science.data import CMF_X, CMF_Y, CMF_Z, N_WAVELENGTHS


def spd_to_xyz(spd: list[float]) -> tuple[float, float, float]:
    """Convert an SPD (81 values, 380-780nm at 5nm) to CIE XYZ tristimulus values.

    Normalizes so that Y = 100 for a perfect reflector.
    """
    if len(spd) != N_WAVELENGTHS:
        raise ValueError(f"Expected {N_WAVELENGTHS} SPD values, got {len(spd)}")

    sum_y = sum(s * cy for s, cy in zip(spd, CMF_Y))
    if sum_y == 0:
        return 0.0, 0.0, 0.0

    x = 100.0 * sum(s * cx for s, cx in zip(spd, CMF_X)) / sum_y
    y = 100.0
    z = 100.0 * sum(s * cz for s, cz in zip(spd, CMF_Z)) / sum_y
    return x, y, z


def xyz_to_xy(x: float, y: float, z: float) -> tuple[float, float]:
    """Convert CIE XYZ to CIE 1931 xy chromaticity coordinates."""
    total = x + y + z
    if total == 0:
        return 0.0, 0.0
    return x / total, y / total


def xy_to_uv(x: float, y: float) -> tuple[float, float]:
    """Convert CIE 1931 xy to CIE 1960 UCS (u, v).

    Note: These are CIE 1960 u,v — NOT CIE 1976 u',v'.
    The relationship is: u' = u, v' = (3/2)*v.
    """
    denom = -2.0 * x + 12.0 * y + 3.0
    if denom == 0:
        return 0.0, 0.0
    u = 4.0 * x / denom
    v = 6.0 * y / denom
    return u, v


def xy_to_uv_prime(x: float, y: float) -> tuple[float, float]:
    """Convert CIE 1931 xy to CIE 1976 u'v' coordinates."""
    u, v = xy_to_uv(x, y)
    return u, v * 1.5


def uv_to_xy(u: float, v: float) -> tuple[float, float]:
    """Convert CIE 1960 UCS (u, v) to CIE 1931 xy."""
    d = 2.0 * u - 8.0 * v + 4.0
    if d == 0:
        return 0.0, 0.0
    return 3.0 * u / d, 2.0 * v / d


def uv2cd(u: float, v: float) -> tuple[float, float]:
    """Compute c, d coefficients for Von Kries chromatic adaptation (CIE 13.3)."""
    c = (4.0 - u - 10.0 * v) / v if v != 0 else 0.0
    d = (1.708 * v + 0.404 - 1.481 * u) / v if v != 0 else 0.0
    return c, d


def xyz_to_uvw(x: float, y: float, z: float,
               u0: float, v0: float) -> tuple[float, float, float]:
    """Convert CIE XYZ to CIE 1964 U*V*W* (for CRI calculation).

    Args:
        x, y, z: Tristimulus values.
        u0, v0: Reference white chromaticity in CIE 1960 UCS.
    """
    cx, cy = xyz_to_xy(x, y, z)
    u, v = xy_to_uv(cx, cy)
    y_val = y  # The Y tristimulus value directly

    w = 25.0 * (y_val ** (1.0 / 3.0)) - 17.0
    uu = 13.0 * w * (u - u0)
    vv = 13.0 * w * (v - v0)
    return uu, vv, w


def spd_xyz_for_tcs(spd: list[float], tcs: list[float]) -> tuple[float, float, float]:
    """Compute XYZ of a test color sample under a given illuminant SPD.

    Args:
        spd: Illuminant SPD (81 values).
        tcs: TCS reflectance (81 values).
    """
    sum_y = sum(s * cy for s, cy in zip(spd, CMF_Y))
    if sum_y == 0:
        return 0.0, 0.0, 0.0

    x = 100.0 * sum(s * r * cx for s, r, cx in zip(spd, tcs, CMF_X)) / sum_y
    y = 100.0 * sum(s * r * cy for s, r, cy in zip(spd, tcs, CMF_Y)) / sum_y
    z = 100.0 * sum(s * r * cz for s, r, cz in zip(spd, tcs, CMF_Z)) / sum_y
    return x, y, z
