"""Tests for color science calculations using known reference values."""
import math

from opple_bridge.science.cie import (
    spd_to_xyz, xyz_to_xy, xy_to_uv, xy_to_uv_prime, uv_to_xy,
)
from opple_bridge.science.cct import cct_from_xy
from opple_bridge.science.duv import duv_from_uv
from opple_bridge.science.cri import compute_cri, _spd_planck, _spd_d_illuminant
from opple_bridge.science.spd import interpolate_spd
from opple_bridge.science.flicker import modulation_depth, flicker_index
from opple_bridge.science.ieee1789 import assess_risk
from opple_bridge.science.tristimulus import (
    channels_to_xyz, detect_light_mode,
    MATRIX_MONO, MATRIX_INCANDESCENT, MATRIX_GENERAL,
)
from opple_bridge.models import FlickerRiskLevel


def _approx(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


class TestCIEConversions:
    def test_xy_to_uv_roundtrip(self):
        """xy -> uv -> xy should round-trip."""
        x, y = 0.3127, 0.3290
        u, v = xy_to_uv(x, y)
        x2, y2 = uv_to_xy(u, v)
        assert _approx(x, x2, 0.0001)
        assert _approx(y, y2, 0.0001)

    def test_d65_chromaticity(self):
        """D65 illuminant should have xy close to (0.3127, 0.3290)."""
        from opple_bridge.science.cri import _spd_d_illuminant
        spd = _spd_d_illuminant(6504)
        X, Y, Z = spd_to_xyz(spd)
        x, y = xyz_to_xy(X, Y, Z)
        assert _approx(x, 0.3127, 0.005)
        assert _approx(y, 0.3290, 0.005)

    def test_uv_prime_relation(self):
        """u' = u, v' = 1.5*v."""
        x, y = 0.4, 0.35
        u, v = xy_to_uv(x, y)
        up, vp = xy_to_uv_prime(x, y)
        assert _approx(up, u, 0.0001)
        assert _approx(vp, 1.5 * v, 0.0001)


class TestCCT:
    def test_d65_cct(self):
        """D65 (0.3127, 0.3290) should yield ~6504K."""
        cct = cct_from_xy(0.3127, 0.3290)
        assert _approx(cct, 6504, 200)  # McCamy's has some error at high CCT

    def test_tungsten_cct(self):
        """Tungsten-like (0.4476, 0.4075) should yield ~2856K (Illuminant A)."""
        cct = cct_from_xy(0.4476, 0.4075)
        assert _approx(cct, 2856, 100)

    def test_zero_y(self):
        """y=0 should return 0 (edge case)."""
        assert cct_from_xy(0.3, 0.0) == 0.0


class TestDuv:
    def test_planckian_duv_near_zero(self):
        """A point on the Planckian locus should have Duv close to 0."""
        # 3000K Planckian: x≈0.4369, y≈0.4041
        x, y = 0.4369, 0.4041
        u, v = xy_to_uv(x, y)
        duv = duv_from_uv(u, v)
        assert abs(duv) < 0.01

    def test_sign_convention(self):
        """Above locus = positive Duv, below = negative."""
        # Point clearly above the locus (green tint)
        x_above, y_above = 0.35, 0.40
        u_a, v_a = xy_to_uv(x_above, y_above)
        duv_above = duv_from_uv(u_a, v_a)
        assert duv_above > 0

        # Point clearly below (pink tint)
        x_below, y_below = 0.35, 0.28
        u_b, v_b = xy_to_uv(x_below, y_below)
        duv_below = duv_from_uv(u_b, v_b)
        assert duv_below < 0


class TestCRI:
    def test_blackbody_perfect_cri(self):
        """A Planckian radiator should get CRI Ra = 100."""
        spd = _spd_planck(3000)
        ra, r_values = compute_cri(spd, 3000)
        assert _approx(ra, 100, 1.0)
        for r in r_values:
            assert _approx(r, 100, 2.0)

    def test_d_illuminant_high_cri(self):
        """D65 illuminant should get CRI Ra close to 100."""
        spd = _spd_d_illuminant(6504)
        ra, r_values = compute_cri(spd, 6504)
        assert _approx(ra, 100, 2.0)

    def test_cri_returns_14_values(self):
        """CRI should return Ra + 14 R-values."""
        spd = _spd_planck(4000)
        ra, r_values = compute_cri(spd, 4000)
        assert len(r_values) == 14


class TestSPD:
    def test_interpolation_length(self):
        """Interpolated SPD should have 81 values."""
        channels = [100, 200, 300, 250, 200, 150]
        spd = interpolate_spd(channels)
        assert len(spd) == 81

    def test_non_negative(self):
        """All SPD values should be non-negative."""
        channels = [50, 100, 200, 180, 120, 80]
        spd = interpolate_spd(channels)
        assert all(v >= 0 for v in spd)

    def test_wrong_channel_count(self):
        """Should raise ValueError for wrong number of channels."""
        try:
            interpolate_spd([1, 2, 3])
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestFlicker:
    # Using data_type=3 throughout: DC offset 13.8447265625 (the default branch).

    def test_dc_below_baseline_no_modulation(self):
        """A constant signal below the ADC baseline should have 0% modulation."""
        wave = [1.0] * 1000
        assert modulation_depth(wave, data_type=3) == 0.0
        assert flicker_index(wave, data_type=3) == 0.0

    def test_constant_above_baseline_no_modulation(self):
        """A constant signal above baseline still has 0% modulation."""
        wave = [200.0] * 1000
        assert modulation_depth(wave, data_type=3) == 0.0
        assert flicker_index(wave, data_type=3) == 0.0

    def test_full_modulation_pulsed(self):
        """A pulsed signal that swings from 0 to peak should give ~100% mod."""
        # Half-rectified sine: range [0, 100], emulates a square-wave-driven LED.
        wave = [max(0.0, 100.0 * math.sin(2 * math.pi * i / 100)) for i in range(1000)]
        md = modulation_depth(wave, data_type=3)
        assert md > 90.0, f"expected ~100% modulation, got {md}"

    def test_low_modulation_matches_app(self):
        """A 1% sine around a high baseline should give ~1% modulation."""
        # Sine swinging ±1 around 100 → max=101, min=99, mod ≈ 2/200 = 1%.
        wave = [100.0 + 1.0 * math.sin(2 * math.pi * i / 256) for i in range(1024)]
        md = modulation_depth(wave, data_type=3)
        assert 0.5 < md < 2.0, f"expected ~1% modulation, got {md}"

    def test_flicker_index_range(self):
        """Flicker index should always be in [0, 1]."""
        wave = [100.0 + 50.0 * math.sin(2 * math.pi * i / 50) for i in range(200)]
        fi = flicker_index(wave, data_type=3)
        assert 0 <= fi <= 1

    def test_data_type_zero_uses_high_offset(self):
        """data_type=0 must use the larger DC offset (29.74)."""
        # All samples below the data_type=0 baseline → fully clipped.
        wave = [25.0] * 500  # 25 < 29.74
        assert modulation_depth(wave, data_type=0) == 0.0
        assert flicker_index(wave, data_type=0) == 0.0


class TestIEEE1789:
    def test_no_risk_at_zero(self):
        """Zero frequency/modulation = no risk."""
        assert assess_risk(0, 0) == FlickerRiskLevel.NO_RISK

    def test_low_flicker_no_risk(self):
        """Very low modulation at high frequency = no risk."""
        assert assess_risk(1000, 0.1) == FlickerRiskLevel.NO_RISK

    def test_high_risk(self):
        """High modulation at low frequency = high risk."""
        assert assess_risk(50, 80) == FlickerRiskLevel.HIGH_RISK

    def test_low_risk_band(self):
        """Modulation between no-risk and low-risk thresholds = low risk."""
        # At 100 Hz: no_risk=3.3%, low_risk=8.0%; 5% sits in the band.
        assert assess_risk(100, 5.0) == FlickerRiskLevel.LOW_RISK

    def test_horizontal_floor_below_10hz(self):
        """Below 10 Hz the threshold is clamped to its value at 10 Hz."""
        # At 5 Hz the no-risk limit is 0.033 * 10 = 0.33%, not 0.033 * 5.
        assert assess_risk(5, 0.3) == FlickerRiskLevel.NO_RISK
        assert assess_risk(5, 0.5) == FlickerRiskLevel.LOW_RISK
        assert assess_risk(5, 1.0) == FlickerRiskLevel.HIGH_RISK


class TestTristimulus:
    def test_matrix_dimensions(self):
        """All G3 matrices should be 3×6 (V, B, G, Y, O, R)."""
        for matrix in (MATRIX_MONO, MATRIX_INCANDESCENT, MATRIX_GENERAL):
            assert len(matrix) == 3
            for row in matrix:
                assert len(row) == 6

    def test_zero_channels(self):
        """All-zero channels should produce (0, 0, 0)."""
        x, y, z = channels_to_xyz([0, 0, 0, 0, 0, 0])
        assert x == 0.0
        assert y == 0.0
        assert z == 0.0

    def test_general_mode_default(self):
        """Mixed channels should detect as general mode."""
        channels = [200, 300, 400, 350, 280, 200]
        mode = detect_light_mode(channels)
        assert mode == "general"

    def test_mono_detection(self):
        """A single dominant channel should detect as monochromatic."""
        # Green channel dominates (>45% of total)
        channels = [10, 20, 900, 30, 20, 10]
        mode = detect_light_mode(channels)
        assert mode == "mono"

    def test_general_xyz_positive(self):
        """Typical channels should produce non-negative XYZ."""
        channels = [200, 400, 500, 450, 380, 300]
        x, y, z = channels_to_xyz(channels)
        assert x >= 0
        assert y >= 0
        assert z >= 0

    def test_lux_equals_y(self):
        """Y from channels_to_xyz is the lux value directly."""
        channels = [200, 400, 500, 450, 380, 300]
        _, y, _ = channels_to_xyz(channels)
        # Y should be a positive lux-like value, not normalized to 100
        assert y > 0

    def test_empty_channels(self):
        """Short channel list should default to general mode."""
        mode = detect_light_mode([100, 200])
        assert mode == "general"
