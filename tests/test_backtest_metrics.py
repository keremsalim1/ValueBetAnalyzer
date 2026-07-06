"""
test_backtest_metrics.py
────────────────────────
compute_log_loss, compute_rps, compute_calibration_curve
için unit testler. run_backtest çağrılmaz — saf fonksiyonlar test edilir.
"""
import math
import pytest
from backtest import compute_log_loss, compute_rps, compute_calibration_curve

APPROX = pytest.approx


# ══════════════════════════════════════════════════════════════════════════════
# compute_log_loss()
# ══════════════════════════════════════════════════════════════════════════════

class TestLogLoss:

    def test_empty_returns_none(self):
        assert compute_log_loss([]) is None

    def test_perfect_prediction_near_zero(self):
        """prob=1.0 kazandı → loss ≈ 0"""
        records = [{"prob": 1.0, "outcome": 1}] * 10
        assert compute_log_loss(records) == APPROX(0.0, abs=1e-3)

    def test_perfect_wrong_prediction_large_loss(self):
        """prob=1.0 ama kaybetti → log(eps) → büyük ceza"""
        records = [{"prob": 1.0, "outcome": 0}]
        result = compute_log_loss(records)
        assert result > 10.0   # -log(eps) çok büyük

    def test_random_prediction_near_ln2(self):
        """prob=0.5 her zaman → log loss = ln(2) ≈ 0.693"""
        records = [{"prob": 0.5, "outcome": o} for o in [1, 0] * 50]
        assert compute_log_loss(records) == APPROX(math.log(2), abs=0.01)

    def test_good_model_lower_loss_than_bad(self):
        """İyi model (prob=0.8 kazandı) → kötü modelden (prob=0.3) düşük loss"""
        good = [{"prob": 0.8, "outcome": 1}] * 20 + [{"prob": 0.2, "outcome": 0}] * 20
        bad  = [{"prob": 0.3, "outcome": 1}] * 20 + [{"prob": 0.7, "outcome": 0}] * 20
        assert compute_log_loss(good) < compute_log_loss(bad)

    def test_symmetry(self):
        """prob=p kazandı ≡ prob=1-p kaybetti (aynı loss)"""
        r1 = compute_log_loss([{"prob": 0.7, "outcome": 1}])
        r2 = compute_log_loss([{"prob": 0.3, "outcome": 0}])
        assert r1 == APPROX(r2, abs=1e-4)

    def test_returns_float(self):
        records = [{"prob": 0.6, "outcome": 1}]
        assert isinstance(compute_log_loss(records), float)

    def test_single_correct_prediction(self):
        """prob=0.6 kazandı → -log(0.6)"""
        records = [{"prob": 0.6, "outcome": 1}]
        expected = -math.log(0.6)
        assert compute_log_loss(records) == APPROX(expected, rel=1e-4)

    def test_single_wrong_prediction(self):
        """prob=0.6 kaybetti → -log(1-0.6) = -log(0.4)"""
        records = [{"prob": 0.6, "outcome": 0}]
        expected = -math.log(0.4)
        assert compute_log_loss(records) == APPROX(expected, rel=1e-4)

    def test_average_over_multiple(self):
        """İki kaydın ortalaması"""
        r1 = -math.log(0.7)   # prob=0.7, won
        r2 = -math.log(0.4)   # prob=0.6, lost → -log(1-0.6)
        expected = round((r1 + r2) / 2, 4)
        records = [{"prob": 0.7, "outcome": 1}, {"prob": 0.6, "outcome": 0}]
        assert compute_log_loss(records) == APPROX(expected, rel=1e-3)


# ══════════════════════════════════════════════════════════════════════════════
# compute_rps()
# ══════════════════════════════════════════════════════════════════════════════

class TestRps:

    def _match(self, home, draw, away, result):
        return {"home": home, "draw": draw, "away": away, "result": result}

    def test_empty_returns_none(self):
        assert compute_rps([]) is None

    def test_perfect_home_prediction(self):
        """p_home=1.0, gerçek=home → RPS=0"""
        m = [self._match(1.0, 0.0, 0.0, "home")]
        assert compute_rps(m) == APPROX(0.0, abs=1e-6)

    def test_perfect_draw_prediction(self):
        """p_draw=1.0, gerçek=draw → RPS=0"""
        m = [self._match(0.0, 1.0, 0.0, "draw")]
        assert compute_rps(m) == APPROX(0.0, abs=1e-6)

    def test_perfect_away_prediction(self):
        """p_away=1.0, gerçek=away → RPS=0"""
        m = [self._match(0.0, 0.0, 1.0, "away")]
        assert compute_rps(m) == APPROX(0.0, abs=1e-6)

    def test_worst_home_prediction(self):
        """p_away=1.0 ama gerçek=home → en kötü durum (max RPS)"""
        m_worst = [self._match(0.0, 0.0, 1.0, "home")]
        m_bad   = [self._match(0.0, 1.0, 0.0, "home")]  # draw tahmini, home geldi
        assert compute_rps(m_worst) > compute_rps(m_bad)

    def test_adjacent_error_less_than_far_error(self):
        """
        Draw tahminle home sonucu (1 adım) →
        Away tahminle home sonucu (2 adım) 'dan düşük RPS.
        RPS sıralı uzaklığı cezalandırır.
        """
        adjacent = [self._match(0.0, 1.0, 0.0, "home")]  # draw tahmini, home geldi
        far      = [self._match(0.0, 0.0, 1.0, "home")]  # away tahmini, home geldi
        assert compute_rps(adjacent) < compute_rps(far)

    def test_uniform_prediction_middle_value(self):
        """p=1/3 her zaman → RPS sabit, orta düzey"""
        m = [self._match(1/3, 1/3, 1/3, "home")] * 30
        rps = compute_rps(m)
        # RPS = 0.5*[(1/3-1)^2 + (2/3-1)^2] = 0.5*[4/9+1/9] = 5/18 ≈ 0.2778
        assert rps == APPROX(5/18, abs=0.001)

    def test_returns_float(self):
        m = [self._match(0.5, 0.3, 0.2, "home")]
        assert isinstance(compute_rps(m), float)

    def test_rps_in_valid_range(self):
        """RPS [0, 1] aralığında olmalı"""
        matches = [
            self._match(0.5, 0.3, 0.2, "home"),
            self._match(0.2, 0.5, 0.3, "draw"),
            self._match(0.3, 0.2, 0.5, "away"),
        ]
        rps = compute_rps(matches)
        assert 0.0 <= rps <= 1.0

    def test_average_over_multiple_matches(self):
        """Ortalama: 2 maçın RPS'i elle hesaplanmış değerle eşleşmeli"""
        # Maç 1: p=[0.7,0.2,0.1], sonuç=home
        # F1=0.7, F2=0.9; G1=1, G2=1 → 0.5*[(0.7-1)^2+(0.9-1)^2] = 0.5*[0.09+0.01]=0.05
        # Maç 2: p=[0.1,0.2,0.7], sonuç=away
        # F1=0.1, F2=0.3; G1=0, G2=0 → 0.5*[(0.1)^2+(0.3)^2] = 0.5*[0.01+0.09]=0.05
        m = [
            self._match(0.7, 0.2, 0.1, "home"),
            self._match(0.1, 0.2, 0.7, "away"),
        ]
        assert compute_rps(m) == APPROX(0.05, abs=1e-4)

    def test_manual_rps_draw_result(self):
        """p=[0.5,0.3,0.2], sonuç=draw → manuel hesap"""
        # F1=0.5, F2=0.8; G1=0, G2=1
        # RPS = 0.5*[(0.5-0)^2 + (0.8-1)^2] = 0.5*[0.25+0.04] = 0.145
        m = [self._match(0.5, 0.3, 0.2, "draw")]
        assert compute_rps(m) == APPROX(0.145, abs=1e-4)


# ══════════════════════════════════════════════════════════════════════════════
# compute_calibration_curve()
# ══════════════════════════════════════════════════════════════════════════════

class TestCalibrationCurve:

    def test_empty_returns_ten_bins(self):
        """Boş girdi → 10 bin, hepsi n=0"""
        result = compute_calibration_curve([])
        assert len(result) == 10
        for b in result:
            assert b["n"] == 0

    def test_always_ten_bins(self):
        """Her zaman tam 10 bin döner"""
        records = [{"prob": 0.5, "outcome": 1}] * 20
        result = compute_calibration_curve(records)
        assert len(result) == 10

    def test_bin_labels_correct(self):
        """Bin etiketleri '0-10%' … '90-100%' formatında"""
        result = compute_calibration_curve([])
        expected = [f"{i*10}-{(i+1)*10}%" for i in range(10)]
        assert [b["bin"] for b in result] == expected

    def test_all_predictions_in_correct_bin(self):
        """prob=0.75 → 70-80% bin'ine düşmeli"""
        records = [{"prob": 0.75, "outcome": 1}] * 10
        result = compute_calibration_curve(records)
        bin_70_80 = result[7]   # index 7 = 70-80%
        assert bin_70_80["n"] == 10

    def test_perfect_calibration_zero_gap(self):
        """
        50% bin'de tam %50 isabet → gap=0, direction=calibrated.
        prob=0.50 olan 10 tahmin, 5'i kazandı 5'i kaybetti.
        """
        records = ([{"prob": 0.50, "outcome": 1}] * 5 +
                   [{"prob": 0.50, "outcome": 0}] * 5)
        result = compute_calibration_curve(records)
        bin_40_50 = result[4]   # 0.50 → index=min(9,int(0.5*10))=5 → 50-60% bin
        bin_50_60 = result[5]
        # 0.50 * 10 = 5.0 → int(5.0)=5 → index 5 = 50-60% bin
        assert bin_50_60["n"] == 10
        assert bin_50_60["gap"] == APPROX(0.0, abs=1.0)   # ±1pp tolerans

    def test_overfit_direction(self):
        """Tahmin > gerçek → direction=overfit"""
        # prob=0.8, ama hiç kazanmadı
        records = [{"prob": 0.8, "outcome": 0}] * 10
        result = compute_calibration_curve(records)
        bin_80_90 = result[8]
        assert bin_80_90["direction"] == "overfit"
        assert bin_80_90["predicted"] > bin_80_90["actual"]

    def test_underfit_direction(self):
        """Tahmin < gerçek → direction=underfit"""
        # prob=0.2, ama hep kazandı
        records = [{"prob": 0.2, "outcome": 1}] * 10
        result = compute_calibration_curve(records)
        bin_20_30 = result[2]
        assert bin_20_30["direction"] == "underfit"
        assert bin_20_30["predicted"] < bin_20_30["actual"]

    def test_empty_bin_has_none_values(self):
        """Veri olmayan bin'de predicted/actual/gap = None"""
        records = [{"prob": 0.5, "outcome": 1}] * 5   # sadece 50-60% bin dolu
        result = compute_calibration_curve(records)
        # İlk bin (0-10%) boş olmalı
        assert result[0]["predicted"] is None
        assert result[0]["actual"]    is None
        assert result[0]["gap"]       is None

    def test_predicted_actual_in_percent(self):
        """predicted ve actual değerleri 0-100 arası yüzde olmalı"""
        records = [{"prob": 0.6, "outcome": 1}] * 10
        result = compute_calibration_curve(records)
        bin_60_70 = result[6]
        if bin_60_70["predicted"] is not None:
            assert 0 <= bin_60_70["predicted"] <= 100
            assert 0 <= bin_60_70["actual"]    <= 100

    def test_gap_always_non_negative(self):
        """gap = |predicted - actual|, hiçbir zaman negatif olamaz"""
        records = ([{"prob": 0.3, "outcome": 1}] * 7 +
                   [{"prob": 0.7, "outcome": 0}] * 7)
        result = compute_calibration_curve(records)
        for b in result:
            if b["gap"] is not None:
                assert b["gap"] >= 0

    def test_boundary_prob_1_goes_to_last_bin(self):
        """prob=1.0 → index = min(9, int(1.0*10)) = min(9,10) = 9 → 90-100% bin"""
        records = [{"prob": 1.0, "outcome": 1}] * 5
        result = compute_calibration_curve(records)
        assert result[9]["n"] == 5

    def test_boundary_prob_0_goes_to_first_bin(self):
        """prob=0.0 → index=0 → 0-10% bin"""
        records = [{"prob": 0.0, "outcome": 0}] * 5
        result = compute_calibration_curve(records)
        assert result[0]["n"] == 5
