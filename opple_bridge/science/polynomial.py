"""G4 Polynomial prediction model for CRI, EML, and CS.

Extracted from decompiled OPPLE app v3.15.0 (LightmasterⅣCoeff_20231115).
Uses degree-3 polynomial regression on 8 transformed sensor channels.

Pipeline:
    calibrated_channels[:8]
    → L2 normalize
    → Coeff matrix transform (8×8)
    → L2 normalize again
    → min-max scale (ledScaler / emlScaler / abScaler)
    → polynomial features (165 terms, degree ≤ 3)
    → dot product with learned coefficients + bias
    → CRI R1-R14, Ra, EML, CS(a,b)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

# ============================================================
# Load coefficient data from JSON
# ============================================================

_DATA_PATH = Path(__file__).parent / "g4_poly_data.json"

with open(_DATA_PATH) as _f:
    _COEF_DATA = json.load(_f)

# Coefficient arrays for R1-R14, Ra, EML, a, b
# Each entry: {"coefficients": [None, c1, c2, ...c164], "bias": float}
_R_COEF_KEYS = [f"LAS_R{i}_COEF" for i in range(1, 15)]
_RA_KEY = "LAS_Ra_COEF"
_EML_KEY = "LAS_EML_COEF"
_A_KEY = "LAS_A_COEF"
_B_KEY = "LAS_B_COEF"

# ============================================================
# Coeff transform matrix (8×8) — LightmasterⅣCoeff_20231115
# Transforms L2-normalized channels into regression input space
# ============================================================

COEFF_MATRIX = (
    (-0.158469, 0.20916, 0.112595, -0.330816, -0.108551, 0.156185, -0.031859, 0.301539),
    (-1.419388, 1.96641, -0.37666, -0.063028, 0.217644, 0.157068, -0.238497, 0.307221),
    (-1.144102, 1.352208, 0.414882, -0.239411, 0.052844, 0.412882, -0.596718, 0.684658),
    (-0.225311, 0.175267, -0.304776, 0.874862, 0.0965, 0.106016, -0.168342, 0.396309),
    (0.254739, -0.063965, 0.223948, -0.295055, 0.721228, -0.009727, 0.196025, 0.190601),
    (0.136996, 0.654563, 0.171631, -0.856572, -0.895806, 1.215222, 0.257699, 0.303073),
    (-0.208297, 1.65795, 0.693002, -2.181311, -2.197116, 1.38897, 1.202967, 0.4825),
    (0.038598, 0.814068, 0.59312, -1.397442, -1.28491, 0.886942, 0.06491, 0.989551),
)

# ============================================================
# Scalers: min-max normalization arrays (8 values each)
# ============================================================

LED_SCALER_MIN = (0.05181869, 0.01784572, 0.04740712, 0.04553685, 0.25051674, 0.28267713, 0.17828663, 0.03560036)
LED_SCALER_MAX = (0.32746889, 0.73256163, 0.59506801, 0.65308541, 0.72466856, 0.65386043, 0.87034288, 0.54106279)

AB_SCALER_MIN = (0.08172532, 0.10375636, 0.07822125, 0.15535571, 0.26380078, 0.29673346, 0.26490609, 0.03563745)
AB_SCALER_MAX = (0.12244247, 0.51499119, 0.33630407, 0.40782491, 0.5581059, 0.58960656, 0.68683068, 0.56185695)

EML_SCALER_MIN = (0.08177328, 0.10373766, 0.07822311, 0.15534812, 0.26378332, 0.2967478, 0.29495997, 0.036428)
EML_SCALER_MAX = (0.12246987, 0.46526904, 0.31737552, 0.40371817, 0.5580768, 0.58961628, 0.68682864, 0.56187936)

# ============================================================
# POWERS: 165 exponent vectors for polynomial feature generation
# Each entry is a tuple of 8 exponents (degree ≤ 3)
# ============================================================

POWERS = (
    (0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 1), (0, 0, 0, 0, 0, 0, 1, 0), (0, 0, 0, 0, 0, 1, 0, 0), (0, 0, 0, 0, 1, 0, 0, 0),
    (0, 0, 0, 1, 0, 0, 0, 0), (0, 0, 1, 0, 0, 0, 0, 0), (0, 1, 0, 0, 0, 0, 0, 0), (1, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 2),
    (0, 0, 0, 0, 0, 0, 1, 1), (0, 0, 0, 0, 0, 0, 2, 0), (0, 0, 0, 0, 0, 1, 0, 1), (0, 0, 0, 0, 0, 1, 1, 0), (0, 0, 0, 0, 0, 2, 0, 0),
    (0, 0, 0, 0, 1, 0, 0, 1), (0, 0, 0, 0, 1, 0, 1, 0), (0, 0, 0, 0, 1, 1, 0, 0), (0, 0, 0, 0, 2, 0, 0, 0), (0, 0, 0, 1, 0, 0, 0, 1),
    (0, 0, 0, 1, 0, 0, 1, 0), (0, 0, 0, 1, 0, 1, 0, 0), (0, 0, 0, 1, 1, 0, 0, 0), (0, 0, 0, 2, 0, 0, 0, 0), (0, 0, 1, 0, 0, 0, 0, 1),
    (0, 0, 1, 0, 0, 0, 1, 0), (0, 0, 1, 0, 0, 1, 0, 0), (0, 0, 1, 0, 1, 0, 0, 0), (0, 0, 1, 1, 0, 0, 0, 0), (0, 0, 2, 0, 0, 0, 0, 0),
    (0, 1, 0, 0, 0, 0, 0, 1), (0, 1, 0, 0, 0, 0, 1, 0), (0, 1, 0, 0, 0, 1, 0, 0), (0, 1, 0, 0, 1, 0, 0, 0), (0, 1, 0, 1, 0, 0, 0, 0),
    (0, 1, 1, 0, 0, 0, 0, 0), (0, 2, 0, 0, 0, 0, 0, 0), (1, 0, 0, 0, 0, 0, 0, 1), (1, 0, 0, 0, 0, 0, 1, 0), (1, 0, 0, 0, 0, 1, 0, 0),
    (1, 0, 0, 0, 1, 0, 0, 0), (1, 0, 0, 1, 0, 0, 0, 0), (1, 0, 1, 0, 0, 0, 0, 0), (1, 1, 0, 0, 0, 0, 0, 0), (2, 0, 0, 0, 0, 0, 0, 0),
    (0, 0, 0, 0, 0, 0, 0, 3), (0, 0, 0, 0, 0, 0, 1, 2), (0, 0, 0, 0, 0, 0, 2, 1), (0, 0, 0, 0, 0, 0, 3, 0), (0, 0, 0, 0, 0, 1, 0, 2),
    (0, 0, 0, 0, 0, 1, 1, 1), (0, 0, 0, 0, 0, 1, 2, 0), (0, 0, 0, 0, 0, 2, 0, 1), (0, 0, 0, 0, 0, 2, 1, 0), (0, 0, 0, 0, 0, 3, 0, 0),
    (0, 0, 0, 0, 1, 0, 0, 2), (0, 0, 0, 0, 1, 0, 1, 1), (0, 0, 0, 0, 1, 0, 2, 0), (0, 0, 0, 0, 1, 1, 0, 1), (0, 0, 0, 0, 1, 1, 1, 0),
    (0, 0, 0, 0, 1, 2, 0, 0), (0, 0, 0, 0, 2, 0, 0, 1), (0, 0, 0, 0, 2, 0, 1, 0), (0, 0, 0, 0, 2, 1, 0, 0), (0, 0, 0, 0, 3, 0, 0, 0),
    (0, 0, 0, 1, 0, 0, 0, 2), (0, 0, 0, 1, 0, 0, 1, 1), (0, 0, 0, 1, 0, 0, 2, 0), (0, 0, 0, 1, 0, 1, 0, 1), (0, 0, 0, 1, 0, 1, 1, 0),
    (0, 0, 0, 1, 0, 2, 0, 0), (0, 0, 0, 1, 1, 0, 0, 1), (0, 0, 0, 1, 1, 0, 1, 0), (0, 0, 0, 1, 1, 1, 0, 0), (0, 0, 0, 1, 2, 0, 0, 0),
    (0, 0, 0, 2, 0, 0, 0, 1), (0, 0, 0, 2, 0, 0, 1, 0), (0, 0, 0, 2, 0, 1, 0, 0), (0, 0, 0, 2, 1, 0, 0, 0), (0, 0, 0, 3, 0, 0, 0, 0),
    (0, 0, 1, 0, 0, 0, 0, 2), (0, 0, 1, 0, 0, 0, 1, 1), (0, 0, 1, 0, 0, 0, 2, 0), (0, 0, 1, 0, 0, 1, 0, 1), (0, 0, 1, 0, 0, 1, 1, 0),
    (0, 0, 1, 0, 0, 2, 0, 0), (0, 0, 1, 0, 1, 0, 0, 1), (0, 0, 1, 0, 1, 0, 1, 0), (0, 0, 1, 0, 1, 1, 0, 0), (0, 0, 1, 0, 2, 0, 0, 0),
    (0, 0, 1, 1, 0, 0, 0, 1), (0, 0, 1, 1, 0, 0, 1, 0), (0, 0, 1, 1, 0, 1, 0, 0), (0, 0, 1, 1, 1, 0, 0, 0), (0, 0, 1, 2, 0, 0, 0, 0),
    (0, 0, 2, 0, 0, 0, 0, 1), (0, 0, 2, 0, 0, 0, 1, 0), (0, 0, 2, 0, 0, 1, 0, 0), (0, 0, 2, 0, 1, 0, 0, 0), (0, 0, 2, 1, 0, 0, 0, 0),
    (0, 0, 3, 0, 0, 0, 0, 0), (0, 1, 0, 0, 0, 0, 0, 2), (0, 1, 0, 0, 0, 0, 1, 1), (0, 1, 0, 0, 0, 0, 2, 0), (0, 1, 0, 0, 0, 1, 0, 1),
    (0, 1, 0, 0, 0, 1, 1, 0), (0, 1, 0, 0, 0, 2, 0, 0), (0, 1, 0, 0, 1, 0, 0, 1), (0, 1, 0, 0, 1, 0, 1, 0), (0, 1, 0, 0, 1, 1, 0, 0),
    (0, 1, 0, 0, 2, 0, 0, 0), (0, 1, 0, 1, 0, 0, 0, 1), (0, 1, 0, 1, 0, 0, 1, 0), (0, 1, 0, 1, 0, 1, 0, 0), (0, 1, 0, 1, 1, 0, 0, 0),
    (0, 1, 0, 2, 0, 0, 0, 0), (0, 1, 1, 0, 0, 0, 0, 1), (0, 1, 1, 0, 0, 0, 1, 0), (0, 1, 1, 0, 0, 1, 0, 0), (0, 1, 1, 0, 1, 0, 0, 0),
    (0, 1, 1, 1, 0, 0, 0, 0), (0, 1, 2, 0, 0, 0, 0, 0), (0, 2, 0, 0, 0, 0, 0, 1), (0, 2, 0, 0, 0, 0, 1, 0), (0, 2, 0, 0, 0, 1, 0, 0),
    (0, 2, 0, 0, 1, 0, 0, 0), (0, 2, 0, 1, 0, 0, 0, 0), (0, 2, 1, 0, 0, 0, 0, 0), (0, 3, 0, 0, 0, 0, 0, 0), (1, 0, 0, 0, 0, 0, 0, 2),
    (1, 0, 0, 0, 0, 0, 1, 1), (1, 0, 0, 0, 0, 0, 2, 0), (1, 0, 0, 0, 0, 1, 0, 1), (1, 0, 0, 0, 0, 1, 1, 0), (1, 0, 0, 0, 0, 2, 0, 0),
    (1, 0, 0, 0, 1, 0, 0, 1), (1, 0, 0, 0, 1, 0, 1, 0), (1, 0, 0, 0, 1, 1, 0, 0), (1, 0, 0, 0, 2, 0, 0, 0), (1, 0, 0, 1, 0, 0, 0, 1),
    (1, 0, 0, 1, 0, 0, 1, 0), (1, 0, 0, 1, 0, 1, 0, 0), (1, 0, 0, 1, 1, 0, 0, 0), (1, 0, 0, 2, 0, 0, 0, 0), (1, 0, 1, 0, 0, 0, 0, 1),
    (1, 0, 1, 0, 0, 0, 1, 0), (1, 0, 1, 0, 0, 1, 0, 0), (1, 0, 1, 0, 1, 0, 0, 0), (1, 0, 1, 1, 0, 0, 0, 0), (1, 0, 2, 0, 0, 0, 0, 0),
    (1, 1, 0, 0, 0, 0, 0, 1), (1, 1, 0, 0, 0, 0, 1, 0), (1, 1, 0, 0, 0, 1, 0, 0), (1, 1, 0, 0, 1, 0, 0, 0), (1, 1, 0, 1, 0, 0, 0, 0),
    (1, 1, 1, 0, 0, 0, 0, 0), (1, 2, 0, 0, 0, 0, 0, 0), (2, 0, 0, 0, 0, 0, 0, 1), (2, 0, 0, 0, 0, 0, 1, 0), (2, 0, 0, 0, 0, 1, 0, 0),
    (2, 0, 0, 0, 1, 0, 0, 0), (2, 0, 0, 1, 0, 0, 0, 0), (2, 0, 1, 0, 0, 0, 0, 0), (2, 1, 0, 0, 0, 0, 0, 0), (3, 0, 0, 0, 0, 0, 0, 0),
)


# ============================================================
# Processing functions
# ============================================================

def _l2_normalize(vec: list[float]) -> list[float]:
    """Normalize vector to unit L2 norm (in-place semantics like JS)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def _min_max_scale(vec: list[float], minima: tuple, maxima: tuple) -> list[float]:
    """Min-max scale: (x - min) / (max - min) for each element."""
    return [
        (v - lo) / (hi - lo) if hi != lo else 0.0
        for v, lo, hi in zip(vec, minima, maxima)
    ]


def _coeff_transform(vec: list[float]) -> list[float]:
    """Apply 8×8 Coeff matrix transform: result[i] = dot(Coeff[i], vec)."""
    return [sum(c * v for c, v in zip(row, vec)) for row in COEFF_MATRIX]


def _polynomial_features(vec: list[float]) -> list[float]:
    """Generate 165 polynomial features from 8-element input."""
    features = []
    for powers in POWERS:
        val = 1.0
        for v, p in zip(vec, powers):
            if p != 0:
                val *= v ** p
        features.append(val)
    return features


def _dot_with_bias(features: list[float], coef_key: str) -> float:
    """Compute dot product of features with coefficient array + bias."""
    entry = _COEF_DATA[coef_key]
    coeffs = entry["coefficients"]
    bias = entry["bias"]
    result = bias
    for i in range(1, len(coeffs)):
        c = coeffs[i]
        if c is not None:
            result += c * features[i]
    return result


# ============================================================
# Public API
# ============================================================

def predict_g4(channels_8: list[float], cct: float = 0.0, lux: float = 0.0) -> dict | None:
    """Run the G4 polynomial model on 8 calibrated channels.

    Args:
        channels_8: First 8 calibrated sensor values (after k_sensor multiply).
        cct: Correlated Color Temperature (for EML fallback).
        lux: Illuminance in lux (for EML scaling).

    Returns:
        Dict with keys: ra, r_values (R1-R14), eml, a, b.
        Returns None if input is invalid (negative transformed values).
    """
    if len(channels_8) < 8:
        return None

    vec = list(channels_8[:8])

    # Step 1: L2 normalize input channels
    vec = _l2_normalize(vec)

    # Step 2: Coeff matrix transform (8→8)
    transformed = _coeff_transform(vec)

    # Step 3: Check all values > 0
    if any(v <= 0 for v in transformed):
        return None

    # Step 4: L2 normalize transformed values
    base = _l2_normalize(transformed)

    # Step 5a: CRI — ledScaler → polynomial features → dot product
    led_scaled = _min_max_scale(base, LED_SCALER_MIN, LED_SCALER_MAX)
    led_features = _polynomial_features(led_scaled)

    r_values = []
    for i in range(1, 15):
        ri = _dot_with_bias(led_features, f"LAS_R{i}_COEF")
        # CRI values capped at 100 (calculateRI in decompiled JS)
        r_values.append(min(ri, 100.0))

    ra = min(_dot_with_bias(led_features, _RA_KEY), 100.0)

    # Step 5b: EML ratio — polynomial model or CCT-based fallback
    eml_scaled = _min_max_scale(base, EML_SCALER_MIN, EML_SCALER_MAX)
    eml_features = _polynomial_features(eml_scaled)
    eml_poly = _dot_with_bias(eml_features, _EML_KEY)

    # App logic: if polynomial EML is in (0, 1), use it as ratio;
    # otherwise fall back to CCT-based formula
    if 0 < eml_poly < 1:
        eml_ratio = eml_poly
    else:
        eml_ratio = 0.00023846153846153847 * cct - 0.6438461538461538 + 0.45

    eml = max(0.0, eml_ratio * lux)

    # Step 5c: CS coefficients — abScaler → polynomial features → dot product
    ab_scaled = _min_max_scale(base, AB_SCALER_MIN, AB_SCALER_MAX)
    ab_features = _polynomial_features(ab_scaled)
    a = _dot_with_bias(ab_features, _A_KEY)
    b = _dot_with_bias(ab_features, _B_KEY)

    return {
        "ra": ra,
        "r_values": r_values,
        "eml": eml,
        "a": a,
        "b": b,
    }


def compute_cs(a: float, b: float, lux: float) -> float:
    """Compute Circadian Stimulus from polynomial model a,b and Lux.

    Formula from decompiled OPPLE app (GetExCttCIE → getCRIFromMeasureData).
    """
    lux_k = lux / 1000.0
    val = a * lux_k * lux_k + b * lux_k
    if val < 0:
        return 0.0
    return 0.7 - 0.7 / (1.0 + (val / 355.7) ** 1.1026)
