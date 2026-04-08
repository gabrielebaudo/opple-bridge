"""CRI (Color Rendering Index) calculation per CIE 13.3-1995.

Computes Ra (general CRI) and R1-R14 (special CRI values).
"""
from __future__ import annotations

import math

from opple_bridge.science.cie import (
    spd_to_xyz,
    spd_xyz_for_tcs,
    xy_to_uv,
    xyz_to_xy,
    uv2cd,
)
from opple_bridge.science.data import (
    CIE_S0, CIE_S1, CIE_S2,
    CMF_Y,
    N_WAVELENGTHS,
    TCS_DATA,
    WL_START, WL_STEP,
)


def _spd_planck(cct: float) -> list[float]:
    """Generate Planckian (blackbody) radiator SPD at given CCT.

    380-780nm at 5nm (81 values), normalized at 560nm.
    """
    spd = []
    c1 = 1.191027e-16  # 2*pi*h*c^2 (W*m^2)
    c2 = 0.0143876      # h*c/k (m*K)

    for i in range(N_WAVELENGTHS):
        wl_nm = WL_START + i * WL_STEP
        wl_m = wl_nm * 1e-9
        val = c1 / (wl_m**5 * (math.exp(c2 / (wl_m * cct)) - 1.0))
        spd.append(val)

    # Normalize at 560nm (index 36)
    norm = spd[36] if spd[36] != 0 else 1.0
    return [v / norm for v in spd]


def _spd_d_illuminant(cct: float) -> list[float]:
    """Generate CIE D-series illuminant SPD at given CCT.

    380-780nm at 5nm (81 values), normalized at 560nm.
    """
    # Compute daylight chromaticity
    if cct < 7000:
        xd = (-4.607e9 / cct**3 + 2.9678e6 / cct**2 +
              0.09911e3 / cct + 0.244063)
    else:
        xd = (-2.0064e9 / cct**3 + 1.9018e6 / cct**2 +
              0.24748e3 / cct + 0.23704)

    yd = -3.0 * xd**2 + 2.87 * xd - 0.275

    denom = 0.0241 + 0.2562 * xd - 0.7341 * yd
    m1 = (-1.3515 - 1.7703 * xd + 5.9114 * yd) / denom
    m2 = (0.03 - 31.4424 * xd + 30.0717 * yd) / denom

    spd = [CIE_S0[i] + m1 * CIE_S1[i] + m2 * CIE_S2[i] for i in range(N_WAVELENGTHS)]

    # Normalize at 560nm (index 36)
    norm = spd[36] if spd[36] != 0 else 1.0
    return [v / norm for v in spd]


def _reference_illuminant(cct: float) -> list[float]:
    """Select and generate the appropriate reference illuminant for CRI.

    Below 5000K: Planckian radiator.
    5000K and above: CIE D-series illuminant.
    """
    if cct < 5000:
        return _spd_planck(cct)
    return _spd_d_illuminant(cct)


def _adapted_uv(u_s: float, v_s: float,
                c_r: float, d_r: float,
                c_t: float, d_t: float) -> tuple[float, float]:
    """Von Kries chromatic adaptation of sample (u_s, v_s).

    Adapts from test illuminant to reference illuminant using
    the CIE 1964 method (CIE 13.3).
    """
    # Convert sample to c, d
    if v_s == 0:
        return 0.0, 0.0
    c_s = (4.0 - u_s - 10.0 * v_s) / v_s
    d_s = (1.708 * v_s + 0.404 - 1.481 * u_s) / v_s

    denom = 16.518 + 1.481 * (c_r / c_t) * c_s - (d_r / d_t) * d_s
    if denom == 0:
        return 0.0, 0.0

    u_a = (10.872 + 0.404 * (c_r / c_t) * c_s - 4.0 * (d_r / d_t) * d_s) / denom
    v_a = 5.52 / denom
    return u_a, v_a


def compute_cri(test_spd: list[float], cct: float) -> tuple[float, list[float]]:
    """Compute CRI Ra and R1-R14 for a test light source.

    Args:
        test_spd: Test illuminant SPD (81 values, 380-780nm at 5nm).
        cct: Correlated Color Temperature of the test source.

    Returns:
        Tuple of (Ra, [R1, R2, ..., R14]).
        Ra is the average of R1-R8.
    """
    if cct <= 0:
        return 0.0, [0.0] * 14

    # Step 1: Reference illuminant
    ref_spd = _reference_illuminant(cct)

    # Step 2: XYZ and chromaticity of test and reference
    x_t, y_t, z_t = spd_to_xyz(test_spd)
    x_r, y_r, z_r = spd_to_xyz(ref_spd)

    cx_t, cy_t = xyz_to_xy(x_t, y_t, z_t)
    cx_r, cy_r = xyz_to_xy(x_r, y_r, z_r)

    u_t, v_t = xy_to_uv(cx_t, cy_t)
    u_r, v_r = xy_to_uv(cx_r, cy_r)

    # Step 3: Von Kries adaptation coefficients
    c_r, d_r = uv2cd(u_r, v_r)
    c_t, d_t = uv2cd(u_t, v_t)

    if c_t == 0 or d_t == 0:
        return 0.0, [0.0] * 14

    # Adapted reference white for the test illuminant
    denom_at = 16.518 + 1.481 * (c_r / c_t) * c_t - (d_r / d_t) * d_t
    if denom_at == 0:
        return 0.0, [0.0] * 14
    u_at = (10.872 + 0.404 * (c_r / c_t) * c_t - 4.0 * (d_r / d_t) * d_t) / denom_at
    v_at = 5.52 / denom_at

    # Step 4: For each TCS, compute delta E in CIE 1964 UVW
    r_values = []

    for tcs_idx in range(14):
        tcs = TCS_DATA[tcs_idx]

        # XYZ of TCS under test illuminant
        x_ts, y_ts, z_ts = spd_xyz_for_tcs(test_spd, tcs)
        # XYZ of TCS under reference illuminant
        x_rs, y_rs, z_rs = spd_xyz_for_tcs(ref_spd, tcs)

        # Chromaticity of TCS under test
        cx_ts, cy_ts = xyz_to_xy(x_ts, y_ts, z_ts)
        u_ts, v_ts = xy_to_uv(cx_ts, cy_ts)

        # Chromaticity of TCS under reference
        cx_rs, cy_rs = xyz_to_xy(x_rs, y_rs, z_rs)
        u_rs, v_rs = xy_to_uv(cx_rs, cy_rs)

        # Adapt test TCS chromaticity to reference
        u_adapted, v_adapted = _adapted_uv(u_ts, v_ts, c_r, d_r, c_t, d_t)

        # UVW for adapted test sample
        w_test = 25.0 * (y_ts ** (1.0 / 3.0)) - 17.0
        uu_test = 13.0 * w_test * (u_adapted - u_at)
        vv_test = 13.0 * w_test * (v_adapted - v_at)

        # UVW for reference sample
        w_ref = 25.0 * (y_rs ** (1.0 / 3.0)) - 17.0
        uu_ref = 13.0 * w_ref * (u_rs - u_r)
        vv_ref = 13.0 * w_ref * (v_rs - v_r)

        # Delta E
        de = math.sqrt(
            (uu_ref - uu_test) ** 2 +
            (vv_ref - vv_test) ** 2 +
            (w_ref - w_test) ** 2
        )

        ri = 100.0 - 4.6 * de
        r_values.append(ri)

    # Ra = average of first 8 (R1-R8)
    ra = sum(r_values[:8]) / 8.0

    return ra, r_values
