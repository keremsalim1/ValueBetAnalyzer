"""
test_probability_model.py
─────────────────────────
Kapsanan davranışlar:
  • poi()             — temel Poisson PMF, sıfır/negatif lambda kenar durumları
  • dixon_coles_rho() — dört düşük skor hücresi, diğer hücreler 1.0 döner
  • match_probs()     — matris toplamı 1.0, bilinen lambda beklentileri,
                        rho=0 vs rho=-0.05 farkı, tarafsız saha, çıktı anahtarları
  • estimate_rho()    — yetersiz veri fallback, aralık sınırları, yön testi
"""
import math
import pytest
from probability_model import poi, dixon_coles_rho, match_probs, estimate_rho

# ─── yardımcı ─────────────────────────────────────────────────────────────────
APPROX = pytest.approx


# ══════════════════════════════════════════════════════════════════════════════
# poi()
# ══════════════════════════════════════════════════════════════════════════════

class TestPoi:
    def test_zero_lambda_k0(self):
        """lambda=0 → P(X=0)=1"""
        assert poi(0, 0) == 1.0

    def test_zero_lambda_k1(self):
        """lambda=0 → P(X=1)=0"""
        assert poi(0, 1) == 0.0

    def test_negative_lambda(self):
        """negatif lambda → lambda=0 gibi davranır"""
        assert poi(-1.0, 0) == 1.0
        assert poi(-1.0, 3) == 0.0

    def test_unit_lambda_k0(self):
        """lambda=1 → P(X=0) = e^{-1}"""
        assert poi(1.0, 0) == APPROX(math.exp(-1), rel=1e-9)

    def test_unit_lambda_k1(self):
        """lambda=1 → P(X=1) = e^{-1}"""
        assert poi(1.0, 1) == APPROX(math.exp(-1), rel=1e-9)

    def test_lambda_2_k2(self):
        """lambda=2 → P(X=2) = 2^2 * e^{-2} / 2! = 2*e^{-2}"""
        expected = 4 * math.exp(-2) / 2
        assert poi(2.0, 2) == APPROX(expected, rel=1e-9)

    def test_noninteger_lambda(self):
        """ondalıklı lambda kabul edilmeli"""
        result = poi(1.5, 1)
        expected = 1.5 * math.exp(-1.5)
        assert result == APPROX(expected, rel=1e-9)

    def test_pmf_sums_to_one(self):
        """Poisson PMF: k=0..30 toplamı ≈ 1.0"""
        lam = 2.5
        total = sum(poi(lam, k) for k in range(31))
        assert total == APPROX(1.0, abs=1e-6)


# ══════════════════════════════════════════════════════════════════════════════
# dixon_coles_rho()
# ══════════════════════════════════════════════════════════════════════════════

class TestDixonColesRho:
    LAM, MU, RHO = 1.5, 1.2, -0.05

    def test_other_scores_return_one(self):
        """Düşük skor hücreleri dışındaki her şey 1.0 döner"""
        assert dixon_coles_rho(2, 0, self.LAM, self.MU, self.RHO) == 1.0
        assert dixon_coles_rho(0, 2, self.LAM, self.MU, self.RHO) == 1.0
        assert dixon_coles_rho(3, 3, self.LAM, self.MU, self.RHO) == 1.0

    def test_00_formula(self):
        """0-0: 1 − λ·μ·ρ"""
        expected = 1 - self.LAM * self.MU * self.RHO
        assert dixon_coles_rho(0, 0, self.LAM, self.MU, self.RHO) == APPROX(expected)

    def test_10_formula(self):
        """1-0: 1 + μ·ρ"""
        expected = 1 + self.MU * self.RHO
        assert dixon_coles_rho(1, 0, self.LAM, self.MU, self.RHO) == APPROX(expected)

    def test_01_formula(self):
        """0-1: 1 + λ·ρ"""
        expected = 1 + self.LAM * self.RHO
        assert dixon_coles_rho(0, 1, self.LAM, self.MU, self.RHO) == APPROX(expected)

    def test_11_formula(self):
        """1-1: 1 − ρ"""
        expected = 1 - self.RHO
        assert dixon_coles_rho(1, 1, self.LAM, self.MU, self.RHO) == APPROX(expected)

    def test_rho_zero_returns_one_everywhere(self):
        """rho=0 → düzeltme yok, tüm hücreler 1.0"""
        for h, a in [(0,0),(1,0),(0,1),(1,1),(2,1)]:
            assert dixon_coles_rho(h, a, self.LAM, self.MU, 0.0) == APPROX(1.0)

    def test_negative_rho_lowers_00(self):
        """rho<0 → 0-0 hücresi ham Poisson'dan büyük (1 − lam*mu*rho > 1)"""
        factor = dixon_coles_rho(0, 0, 1.5, 1.2, -0.05)
        assert factor > 1.0

    def test_negative_rho_lowers_11(self):
        """rho<0 → 1-1 hücresi ham Poisson'dan büyük (1 − rho > 1)"""
        factor = dixon_coles_rho(1, 1, 1.5, 1.2, -0.05)
        assert factor > 1.0


# ══════════════════════════════════════════════════════════════════════════════
# match_probs()
# ══════════════════════════════════════════════════════════════════════════════

class TestMatchProbs:

    # ── gerekli çıktı anahtarları ────────────────────────────────────────────
    REQUIRED_KEYS = {
        "home_win","draw","away_win",
        "over25","under25","over15","under15","over35","under35",
        "btts_yes","btts_no",
        "dc_1x","dc_x2","dc_12",
        "ht_home","ht_draw","ht_away",
        "iy_ms","top_scores",
        "corners_expected",
        "corner_o85","corner_u85",
        "corner_o95","corner_u95",
        "corner_o105","corner_u105",
        "corner_o115","corner_u115",
    }

    def _probs(self, hxg=1.5, axg=1.2, **kw):
        return match_probs(hxg, axg, **kw)

    # ── 1X2 toplamı 1.0 ─────────────────────────────────────────────────────
    def test_1x2_sum_to_one(self):
        p = self._probs()
        total = p["home_win"] + p["draw"] + p["away_win"]
        assert total == APPROX(1.0, abs=1e-4)

    def test_over_under_25_complement(self):
        p = self._probs()
        assert p["over25"] + p["under25"] == APPROX(1.0, abs=1e-4)

    def test_over_under_15_complement(self):
        """over15 + under15 = 1.0"""
        p = self._probs()
        assert p["over15"] + p["under15"] == APPROX(1.0, abs=1e-4)

    def test_over_under_35_complement(self):
        """over35 + under35 = 1.0"""
        p = self._probs()
        assert p["over35"] + p["under35"] == APPROX(1.0, abs=1e-4)

    def test_over15_greater_than_over25(self):
        """over15 > over25: daha düşük eşik → daha yüksek olasılık"""
        p = self._probs()
        assert p["over15"] > p["over25"]

    def test_over25_greater_than_over35(self):
        """over25 > over35: hiyerarşi doğru"""
        p = self._probs()
        assert p["over25"] > p["over35"]

    def test_btts_complement(self):
        p = self._probs()
        assert p["btts_yes"] + p["btts_no"] == APPROX(1.0, abs=1e-4)

    # ── güçlü ev sahibi avantajı ─────────────────────────────────────────────
    def test_strong_home_favourite(self):
        """hxg=2.5, axg=0.5 → ev sahibi kazanma olasılığı %60+ olmalı"""
        p = match_probs(2.5, 0.5)
        assert p["home_win"] > 0.60

    def test_strong_away_favourite(self):
        """hxg=0.5, axg=2.5 → deplasman kazanma olasılığı %60+ olmalı"""
        p = match_probs(0.5, 2.5)
        assert p["away_win"] > 0.60

    def test_equal_teams_draw_most_likely_market(self):
        """hxg=axg=1.2 → beraberlik en yüksek tek sonuç olasılığı değil ama
        home_win ≈ away_win (simetri)"""
        p = match_probs(1.2, 1.2)
        assert abs(p["home_win"] - p["away_win"]) < 0.01

    # ── rho=0 vs rho=-0.05 farkı ─────────────────────────────────────────────
    def test_rho_effect_on_00_probability(self):
        """rho=-0.05 → 0-0 olasılığı rho=0'dan farklı olmalı"""
        p0   = match_probs(1.5, 1.2, rho=0.0)
        pneg = match_probs(1.5, 1.2, rho=-0.05)
        # Dixon-Coles rho<0 ile 0-0 faktörü > 1 → 0-0 olasılığı yüksek
        # Normalize sonrası fark küçük ama sıfır olmamalı
        assert p0["draw"] != APPROX(pneg["draw"], abs=1e-6)

    def test_rho_zero_preserves_poisson(self):
        """rho=0 → dc düzeltmesi yok, pure Poisson ile aynı 1x2"""
        p_rho0 = match_probs(1.5, 1.2, rho=0.0)
        # Pure Poisson referansı (manuel hesap)
        hxg, axg = 1.5, 1.2
        hw = sum(
            poi(hxg, i) * poi(axg, j)
            for i in range(8) for j in range(8) if i > j
        )
        # Normalize için toplam
        total = sum(
            poi(hxg, i) * poi(axg, j)
            for i in range(8) for j in range(8)
        )
        hw_pure = hw / total
        assert p_rho0["home_win"] == APPROX(hw_pure, abs=1e-3)

    # ── tarafsız saha ────────────────────────────────────────────────────────
    def test_neutral_ground_symmetry(self):
        """neutral=True + hxg==axg → home_win ≈ away_win"""
        p = match_probs(1.5, 1.5, neutral=True)
        assert abs(p["home_win"] - p["away_win"]) < 0.001

    def test_neutral_averages_xg(self):
        """neutral=True → hxg ve axg ortalaması kullanılır; sonuç simetriktir"""
        p = match_probs(2.0, 1.0, neutral=True)
        # ortalama xg = 1.5 her iki tarafa → simetri
        assert abs(p["home_win"] - p["away_win"]) < 0.001

    # ── küçük xg sınır koruması ──────────────────────────────────────────────
    def test_tiny_xg_clamped(self):
        """hxg=0 → 0.1'e yükseltilir, crash yok"""
        p = match_probs(0.0, 0.0)
        assert p["home_win"] + p["draw"] + p["away_win"] == APPROX(1.0, abs=1e-4)

    # ── çıktı anahtarları ────────────────────────────────────────────────────
    def test_all_required_keys_present(self):
        p = self._probs()
        for key in self.REQUIRED_KEYS:
            assert key in p, f"Eksik anahtar: {key}"

    def test_iyms_nine_combinations(self):
        """İY/MS dict tam 9 kombinasyon içermeli"""
        p = self._probs()
        assert len(p["iy_ms"]) == 9

    def test_iyms_sum_to_one(self):
        """Normalize edilmiş İY/MS toplamı ≈ 1.0"""
        p = self._probs()
        total = sum(p["iy_ms"].values())
        assert total == APPROX(1.0, abs=1e-3)

    def test_top_scores_ten_entries(self):
        """top_scores en fazla 10 eleman"""
        p = self._probs()
        assert len(p["top_scores"]) <= 10

    def test_top_scores_descending(self):
        """top_scores olasılığa göre azalan sıralı"""
        p = self._probs()
        probs_list = [v for _, v in p["top_scores"]]
        assert probs_list == sorted(probs_list, reverse=True)

    def test_corner_complement(self):
        """Korner over+under çiftleri tamamlayıcı"""
        p = self._probs()
        for over, under in [
            ("corner_o85","corner_u85"),
            ("corner_o95","corner_u95"),
            ("corner_o105","corner_u105"),
            ("corner_o115","corner_u115"),
        ]:
            assert p[over] + p[under] == APPROX(1.0, abs=1e-4), f"{over}+{under}≠1"

    # ── double chance tümleme ────────────────────────────────────────────────
    def test_dc_1x_equals_hw_plus_draw(self):
        p = self._probs()
        assert p["dc_1x"] == APPROX(p["home_win"] + p["draw"], abs=1e-4)

    def test_dc_x2_equals_draw_plus_aw(self):
        p = self._probs()
        assert p["dc_x2"] == APPROX(p["draw"] + p["away_win"], abs=1e-4)

    def test_dc_12_equals_hw_plus_aw(self):
        p = self._probs()
        assert p["dc_12"] == APPROX(p["home_win"] + p["away_win"], abs=1e-4)


# ══════════════════════════════════════════════════════════════════════════════
# estimate_rho()
# ══════════════════════════════════════════════════════════════════════════════

class TestEstimateRho:

    def _make_matches(self, n, score_pairs):
        """n maçlık liste; score_pairs = [(hs, as), ...] döngüsel olarak tekrar"""
        matches = []
        for i in range(n):
            hs, as_ = score_pairs[i % len(score_pairs)]
            matches.append({"hs": hs, "as": as_})
        return matches

    def test_insufficient_data_returns_default(self):
        """<30 maç → varsayılan -0.05"""
        matches = self._make_matches(20, [(1,1),(2,0),(0,2)])
        assert estimate_rho(matches) == -0.05

    def test_result_in_valid_range(self):
        """Sonuç her zaman [-0.20, 0.0] aralığında"""
        matches = self._make_matches(100, [(1,1),(2,0),(0,1),(3,2),(0,0)])
        rho = estimate_rho(matches)
        assert -0.20 <= rho <= 0.0

    def test_all_zero_goals_fallback(self):
        """Tüm gol ortalamaları sıfır → -0.05 fallback"""
        matches = [{"hs": 0, "as": 0}] * 50
        assert estimate_rho(matches) == -0.05

    def test_high_00_rate_gives_more_negative_rho(self):
        """0-0 maç oranı yüksekse rho daha negatif (daha güçlü düzeltme)"""
        # Çok 0-0 içeren veri seti
        many_zeros = [{"hs":0,"as":0}]*50 + [{"hs":2,"as":1}]*50
        rho_many   = estimate_rho(many_zeros)
        # Az 0-0 içeren veri seti
        few_zeros  = [{"hs":0,"as":0}]*5 + [{"hs":2,"as":1}]*95
        rho_few    = estimate_rho(few_zeros)
        assert rho_many <= rho_few

    def test_returns_float(self):
        matches = self._make_matches(60, [(1,0),(0,1),(1,1),(2,1)])
        result  = estimate_rho(matches)
        assert isinstance(result, float)
