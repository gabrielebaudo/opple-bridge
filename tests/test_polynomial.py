"""Tests for G4 polynomial prediction model using real probe data."""
import pytest

from opple_bridge.science.polynomial import predict_g4, compute_cs


# Real probe data from our-command.txt (measurement 2)
# Raw channels after k_sensor calibration
K_SENSOR = [1.010141, 1.009422, 0.928753, 1.037585, 0.968898, 1.181077, 0.961893, 1.059147, 1.0]
RAW_CHANNELS = [654, 819, 855, 1152, 1330, 1719, 2595, 3715, 14571]
CALIBRATED = [ch * k for ch, k in zip(RAW_CHANNELS, K_SENSOR)]

# Expected values from official Opple app screenshot
APP_CCT = 4236
APP_LUX = 2057
APP_RA = 96.5
APP_R9 = 52.2
APP_EML = 1680
APP_CS = 0.619


class TestPredictG4:
    """Validate polynomial model against official Opple app values."""

    def test_ra_matches_app(self):
        result = predict_g4(CALIBRATED[:8], cct=APP_CCT, lux=APP_LUX)
        assert abs(result["ra"] - APP_RA) < 1.0, f"Ra: {result['ra']} vs app {APP_RA}"

    def test_r9_matches_app(self):
        result = predict_g4(CALIBRATED[:8], cct=APP_CCT, lux=APP_LUX)
        r9 = result["r_values"][8]  # R9 is index 8 (0-based)
        assert abs(r9 - APP_R9) < 2.0, f"R9: {r9} vs app {APP_R9}"

    def test_eml_matches_app(self):
        result = predict_g4(CALIBRATED[:8], cct=APP_CCT, lux=APP_LUX)
        # EML difference is proportional to Lux difference (our probe reads slightly higher)
        assert abs(result["eml"] - APP_EML) < 150, f"EML: {result['eml']} vs app {APP_EML}"

    def test_cs_matches_app(self):
        result = predict_g4(CALIBRATED[:8], cct=APP_CCT, lux=APP_LUX)
        cs = compute_cs(result["a"], result["b"], APP_LUX)
        assert abs(cs - APP_CS) < 0.1, f"CS: {cs} vs app {APP_CS}"

    def test_r_values_all_present(self):
        result = predict_g4(CALIBRATED[:8], cct=APP_CCT, lux=APP_LUX)
        r_values = result["r_values"]
        assert len(r_values) == 14, f"Expected 14 R-values, got {len(r_values)}"
        for i, rv in enumerate(r_values, 1):
            assert 0 <= rv <= 100, f"R{i}={rv} out of range"

    def test_cri_values_clamped_at_100(self):
        result = predict_g4(CALIBRATED[:8], cct=APP_CCT, lux=APP_LUX)
        for i, rv in enumerate(result["r_values"], 1):
            assert rv <= 100.0, f"R{i}={rv} exceeds 100"


class TestComputeCS:
    """Test CS (Circadian Stimulus) calculation."""

    def test_cs_positive_for_warm_white(self):
        result = predict_g4(CALIBRATED[:8], cct=APP_CCT, lux=APP_LUX)
        cs = compute_cs(result["a"], result["b"], APP_LUX)
        assert cs > 0, f"CS should be positive: {cs}"

    def test_cs_in_valid_range(self):
        result = predict_g4(CALIBRATED[:8], cct=APP_CCT, lux=APP_LUX)
        cs = compute_cs(result["a"], result["b"], APP_LUX)
        assert 0 <= cs <= 0.7, f"CS out of range: {cs}"

    def test_cs_zero_lux(self):
        cs = compute_cs(1.0, 1.0, 0.0)
        assert cs == 0.0
