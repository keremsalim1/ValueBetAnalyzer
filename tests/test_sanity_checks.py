"""
test_sanity_checks.py
─────────────────────
Kapsanan davranışlar:
  • xG > 3.5 → reject
  • Her iki xG de sıfıra yakın → reject
  • xG farkı aşırı → flag (reject değil)
  • edge > %40 → reject
  • edge > %20 → caution flag, reject yok
  • edge > %12 + confidence < 55 → reject
  • Olasılık-oran gap'i aşırı → reject
  • Olasılık-oran gap'i yüksek → caution flag
  • Normal durum → reject=False, flag yok
"""
import pytest
from sanity_checks import validate_prediction_context


# ── yardımcı ──────────────────────────────────────────────────────────────────
def v(hxg=1.5, axg=1.2, conf=70, edge=0.10, market="home", odds=2.0):
    return validate_prediction_context(hxg, axg, conf, edge, market, odds)


# ══════════════════════════════════════════════════════════════════════════════
# Normal (geçerli) durum
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalCase:

    def test_valid_input_not_rejected(self):
        result = v()
        assert result["reject"] is False

    def test_valid_input_no_flags(self):
        result = v()
        assert result["flags"] == []

    def test_returns_dict_with_required_keys(self):
        result = v()
        assert "reject" in result
        assert "flags"  in result


# ══════════════════════════════════════════════════════════════════════════════
# xG anomalileri
# ══════════════════════════════════════════════════════════════════════════════

class TestXgAnomalies:

    def test_high_home_xg_rejected(self):
        """hxg > 3.5 → reject"""
        result = v(hxg=4.0, axg=1.2)
        assert result["reject"] is True
        assert "anomaly_hxg_extreme" in result["flags"]

    def test_high_away_xg_rejected(self):
        """axg > 3.5 → reject"""
        result = v(hxg=1.5, axg=4.0)
        assert result["reject"] is True
        assert "anomaly_axg_extreme" in result["flags"]

    def test_both_xg_extreme_both_flags(self):
        """hxg ve axg ikisi de > 3.5 → iki flag"""
        result = v(hxg=4.0, axg=5.0)
        assert "anomaly_hxg_extreme" in result["flags"]
        assert "anomaly_axg_extreme" in result["flags"]

    def test_xg_near_zero_rejected(self):
        """hxg < 0.15 VE axg < 0.15 → reject"""
        result = v(hxg=0.05, axg=0.05)
        assert result["reject"] is True
        assert "anomaly_both_xg_near_zero" in result["flags"]

    def test_one_xg_near_zero_not_rejected(self):
        """Sadece biri küçük → reject yok (gap flag olabilir)"""
        result = v(hxg=0.05, axg=1.5)
        # anomaly_both_xg_near_zero olmadığı için tek başına reject etmemeli
        assert "anomaly_both_xg_near_zero" not in result["flags"]

    def test_xg_gap_extreme_flag(self):
        """hxg - axg > 2.5 → gap flag (reject değil)"""
        result = v(hxg=3.0, axg=0.3, edge=0.10)
        assert "anomaly_xg_gap_extreme" in result["flags"]

    def test_normal_xg_no_flag(self):
        """Normal xG farkı → flag yok"""
        result = v(hxg=1.8, axg=1.0)
        assert "anomaly_xg_gap_extreme" not in result["flags"]

    def test_boundary_xg_35_not_rejected(self):
        """hxg = 3.5 (tam) → reject yok (> 3.5 koşulu)"""
        result = v(hxg=3.5, axg=1.2)
        assert "anomaly_hxg_extreme" not in result["flags"]

    def test_boundary_xg_above_35_rejected(self):
        """hxg = 3.51 → reject"""
        result = v(hxg=3.51, axg=1.2)
        assert result["reject"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Edge anomalileri
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeAnomalies:

    def test_edge_above_40_rejected(self):
        """edge > 0.40 → reject + anomaly_edge_too_high"""
        result = v(edge=0.45)
        assert result["reject"] is True
        assert "anomaly_edge_too_high" in result["flags"]

    def test_edge_exactly_40_not_rejected(self):
        """edge = 0.40 (tam sınır) → reject yok"""
        result = v(edge=0.40)
        assert result["reject"] is False
        assert "anomaly_edge_too_high" not in result["flags"]

    def test_edge_above_20_caution(self):
        """edge > 0.20 → caution_high_edge flag, reject yok"""
        result = v(edge=0.25)
        assert "caution_high_edge" in result["flags"]
        assert result["reject"] is False

    def test_edge_exactly_20_no_caution(self):
        """edge = 0.20 (tam sınır) → caution yok"""
        result = v(edge=0.20)
        assert "caution_high_edge" not in result["flags"]

    def test_edge_above_12_low_conf_rejected(self):
        """edge > 0.12 VE confidence < 55 → reject"""
        result = v(edge=0.15, conf=50)
        assert result["reject"] is True
        assert "anomaly_high_edge_low_conf" in result["flags"]

    def test_edge_above_12_ok_conf_not_rejected(self):
        """edge > 0.12 VE confidence >= 55 → reject yok"""
        result = v(edge=0.15, conf=60)
        assert "anomaly_high_edge_low_conf" not in result["flags"]

    def test_edge_below_12_low_conf_ok(self):
        """edge ≤ 0.12 VE düşük confidence → bu kurala göre reject yok"""
        result = v(edge=0.10, conf=40)
        assert "anomaly_high_edge_low_conf" not in result["flags"]


# ══════════════════════════════════════════════════════════════════════════════
# Olasılık-oran gap kontrolü
# ══════════════════════════════════════════════════════════════════════════════

class TestProbGap:

    def test_extreme_gap_rejected(self):
        """
        gap = edge/odds (formülü basitleştirir).
        gap > 0.35 için: edge/odds > 0.35 → odds=1.05, edge=0.37 → 0.37/1.05=0.352 > 0.35
        """
        result = validate_prediction_context(
            hxg=1.5, axg=1.2, confidence=70,
            edge=0.37, market_key="home", odds=1.05
        )
        assert "anomaly_prob_gap_extreme" in result["flags"]
        assert result["reject"] is True

    def test_high_gap_caution(self):
        """gap > 0.20 ama ≤ 0.35 → caution_prob_gap_high"""
        # odds=2.0, edge=0.20 → implied=0.5, model_prob=(0.20+1)/2=0.60, gap=0.10 < 0.20
        # odds=1.6, edge=0.25 → implied=0.625, model_prob=(0.25+1)/1.6=0.78125, gap=0.156 < 0.20
        # odds=1.5, edge=0.30 → implied=0.667, model_prob=(0.30+1)/1.5=0.867, gap=0.20 (eşik)
        # odds=1.4, edge=0.25 → implied=0.714, model_prob=(0.25+1)/1.4=0.893, gap=0.179 < 0.20
        # odds=1.3, edge=0.20 → implied=0.769, model_prob=(0.20+1)/1.3=0.923, gap=0.154 < 0.20
        # odds=1.5, edge=0.35 → implied=0.667, model_prob=(0.35+1)/1.5=0.90, gap=0.233 ∈(0.20,0.35)
        result = validate_prediction_context(
            hxg=1.5, axg=1.2, confidence=70,
            edge=0.35, market_key="home", odds=1.5
        )
        assert "caution_prob_gap_high" in result["flags"] or \
               "anomaly_prob_gap_extreme" in result["flags"]

    def test_normal_gap_no_flag(self):
        """Normal edge + normal odds → prob gap flag yok"""
        # odds=2.0, edge=0.10 → implied=0.50, model_prob=(0.10+1)/2=0.55, gap=0.05
        result = v(edge=0.10, odds=2.0)
        assert "anomaly_prob_gap_extreme"  not in result["flags"]
        assert "caution_prob_gap_high"     not in result["flags"]


# ══════════════════════════════════════════════════════════════════════════════
# Birleşik senaryolar
# ══════════════════════════════════════════════════════════════════════════════

class TestCombinedScenarios:

    def test_xg_extreme_overrides_all(self):
        """xG anomalisi + normal edge → still reject"""
        result = v(hxg=4.5, axg=0.8, edge=0.08)
        assert result["reject"] is True

    def test_multiple_flags_accumulated(self):
        """xG gap + high edge → birden fazla flag"""
        result = v(hxg=3.2, axg=0.3, edge=0.22)
        assert len(result["flags"]) >= 2

    def test_flags_are_list(self):
        result = v()
        assert isinstance(result["flags"], list)

    def test_reject_is_bool(self):
        result = v()
        assert isinstance(result["reject"], bool)
