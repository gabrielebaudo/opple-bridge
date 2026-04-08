"""Tristimulus matrix conversion for Opple Light Master.

Converts raw sensor data to CIE XYZ tristimulus values.

G3 (Light Master III): 6 channels → 3×7 matrix with light-type classification
  Three matrices for different source types: mono, incandescent, general.

G4 (Light Master IV): 9 channels → 3×8 matrix (first 8 channels)
  Single matrix for all source types (polynomial model handles nonlinearity).
  From decompiled OPPLE app v3.15.0 (LightmasterⅣCoeff_20231115).

The Y component of the output equals illuminance (lux) directly.
"""
from __future__ import annotations

# ============================================================
# G3 matrices: 3×6 (V, B, G, Y, O, R)
# From open-light-master lib/ble/lm3.ts
# (The reference implementation uses a 3×7 matrix with a temperature column,
#  but every coefficient in that column is zero — the device's temperature
#  byte never actually contributes to XYZ — so we drop it.)
# ============================================================

MATRIX_MONO = (
    (0.06023, 0.00106, 0.02108, 0.03673, 0.1683, 0.02001),
    (0.00652, 0.04478, 0.16998, -0.03268, 0.07425, 0.00739),
    (0.33092, 0.12936, -0.15809, 0.19889, -0.0156, 0.00296),
)

MATRIX_INCANDESCENT = (
    (-0.43786, 0.53102, -0.1453, 0.2316, 0.36758, -0.09047),
    (-0.23226, 0.69225, -0.39786, 0.22539, 0.47947, -0.17614),
    (-0.11002, 1.21259, -0.56003, 0.14487, 0.35074, -0.30248),
)

MATRIX_GENERAL = (
    (-0.05825, -0.0896, 0.25859, 0.19518, 0.10893, 0.06724),
    (-0.19865, 0.01337, 0.40651, 0.29702, -0.06287, 0.03282),
    (0.58258, 0.11548, 0.21823, -0.00136, -0.10732, -0.00915),
)

# Map mode name → matrix (G3 only)
_MATRICES = {
    "mono": MATRIX_MONO,
    "incandescent": MATRIX_INCANDESCENT,
    "general": MATRIX_GENERAL,
}

# ============================================================
# G4 matrix: 3×8 (8 spectral channels, no temperature column)
# From decompiled OPPLE app: LightmasterⅣCoeff_20231115
# ============================================================

MATRIX_G4 = (
    (-0.873112331303128, 0.805269469275936, -0.14141487926448,
     0.0341236934045446, 0.290053924131123, 0.681542877395036,
     0.237949611300369, -0.0216220125618065),
    (-0.892318403241807, 0.283584501574269, -0.142426509016336,
     0.670437256572805, 0.619588489202499, 0.436347226426992,
     0.0482937353635748, -0.00263886395266582),
    (-1.60374782255152, 3.11179541056893, 0.945597350971534,
     -0.0788297890447575, 0.103830669638194, -0.0824849988110418,
     -0.0071035486372898, -0.0659551443269493),
)


def detect_light_mode(channels: list[float]) -> str:
    """Detect light source type from calibrated G3 channel values.

    Args:
        channels: 6 calibrated sensor values [V, B, G, Y, O, R]

    Returns:
        "mono", "incandescent", or "general"
    """
    if len(channels) < 6:
        return "general"

    total = sum(channels[:6])
    if total <= 0:
        return "general"

    brightest = max(channels[:6])

    # Monochromatic: single channel dominates (≥45% of total)
    if brightest >= 0.45 * total:
        return "mono"

    # Incandescent: specific O/R and R/Y ratios
    o_ch = channels[4]  # Orange (600nm)
    r_ch = channels[5]  # Red (650nm)
    y_ch = channels[3]  # Yellow (570nm)

    if r_ch > 0 and y_ch > 0:
        or_ratio = o_ch / r_ch
        ry_ratio = (r_ch - y_ch) / y_ch if y_ch > 0 else 999
        if 0.5 <= or_ratio <= 0.55 and 0.0 <= ry_ratio <= 0.05:
            return "incandescent"

    return "general"


def channels_to_xyz(channels: list[float]) -> tuple[float, float, float]:
    """Convert 6-channel G3 sensor data to CIE XYZ using tristimulus matrices.

    Args:
        channels: 6 calibrated sensor values [V, B, G, Y, O, R]

    Returns:
        (X, Y, Z) where Y equals illuminance in lux
    """
    mode = detect_light_mode(channels)
    matrix = _MATRICES[mode]

    vec = channels[:6]
    x = sum(m * v for m, v in zip(matrix[0], vec))
    y = sum(m * v for m, v in zip(matrix[1], vec))
    z = sum(m * v for m, v in zip(matrix[2], vec))

    return max(0.0, x), max(0.0, y), max(0.0, z)


def channels_to_xyz_g4(channels: list[float]) -> tuple[float, float, float]:
    """Convert 9-channel G4 sensor data to CIE XYZ using M_1 matrix.

    Uses the first 8 of 9 channels (9th is clear/reference, not used for XYZ).
    No light-type classification needed — single matrix handles all sources.

    Args:
        channels: 9 calibrated sensor values from G4

    Returns:
        (X, Y, Z) where Y equals illuminance in lux
    """
    vec = channels[:8]

    x = sum(m * v for m, v in zip(MATRIX_G4[0], vec))
    y = sum(m * v for m, v in zip(MATRIX_G4[1], vec))
    z = sum(m * v for m, v in zip(MATRIX_G4[2], vec))

    return max(0.0, x), max(0.0, y), max(0.0, z)
