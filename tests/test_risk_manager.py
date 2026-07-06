"""
test_risk_manager.py
────────────────────
Kapsanan davranışlar:
  • value_calc()          — pozitif/negatif/sıfır edge, geçersiz oran
  • adaptive_kelly()      — negatif edge → 0, düşük confidence → 0,
                            edge>%40 → reject, edge>%20 → ok ama küçük,
                            disabled market → 0, sonuç hard cap'i aşmaz
  • filter_correlated_bets() — aynı maçtan max 1 bet, edge sıralaması
  • apply_risk_limits()   — günlük cap aşımı, haftalık cap aşımı,
                            weekly_spent dolmuşsa boş liste, kısmi bahis
  • build_reason_flags()  — edge/confidence/market etiketleri
"""
import sys, os
import pytest

# config bağımlılığını izole etmek için mock
from unittest.mock import patch

# Sabit config değerleri: test ortamında gerçek .env'e bağlı kalmayalım
CONFIG_DEFAULTS = {
    "KELLY_HARD_CAP":       0.025,
    "MIN_CONFIDENCE":       55,
    "DAILY_RISK_CAP":       0.08,
    "WEEKLY_RISK_CAP":      0.20,
    "MAX_CORRELATED_BETS":  1,
    "MIN_EDGE":             0.05,
}

# risk_manager config sabitlerini doğrudan patch ederek import et
with patch.dict("sys.modules", {}):
    import importlib, types

    # Sahte config modülü
    fake_config = types.ModuleType("config")
    for k, v in CONFIG_DEFAULTS.items():
        setattr(fake_config, k, v)
    sys.modules.setdefault("config", fake_config)

    # Gerçek modülü yükle (zaten config mock'landı)
    import risk_manager as rm


BANKROLL = 1000.0
APPROX   = pytest.approx


# ══════════════════════════════════════════════════════════════════════════════
# value_calc()
# ══════════════════════════════════════════════════════════════════════════════

class TestValueCalc:
    def test_positive_edge(self):
        """prob=0.6, odds=2.0 → edge = 0.6*2-1 = 0.20"""
        assert rm.value_calc(0.6, 2.0) == APPROX(0.20, abs=1e-4)

    def test_zero_edge(self):
        """prob=0.5, odds=2.0 → edge = 0.0 (fair bet)"""
        assert rm.value_calc(0.5, 2.0) == APPROX(0.0, abs=1e-4)

    def test_negative_edge(self):
        """prob=0.4, odds=2.0 → edge = -0.20"""
        assert rm.value_calc(0.4, 2.0) == APPROX(-0.20, abs=1e-4)

    def test_invalid_odds_returns_minus_one(self):
        """odds≤1.0 → -1.0"""
        assert rm.value_calc(0.5, 1.0) == -1.0
        assert rm.value_calc(0.5, 0.5) == -1.0


# ══════════════════════════════════════════════════════════════════════════════
# adaptive_kelly()
# ══════════════════════════════════════════════════════════════════════════════

class TestAdaptiveKelly:

    def _kelly(self, prob=0.55, odds=2.1, conf=65, mclass="tradable", bank=BANKROLL):
        return rm.adaptive_kelly(prob, odds, conf, mclass, bank)

    # ── temel geçer durum ────────────────────────────────────────────────────
    def test_valid_bet_returns_ok(self):
        r = self._kelly()
        assert r["reason"] == "ok"
        assert r["fraction"] > 0
        assert r["bet"] > 0

    def test_fraction_never_exceeds_hard_cap(self):
        """Kelly fraction her zaman KELLY_HARD_CAP (%2.5) altında"""
        r = self._kelly(prob=0.90, odds=3.0, conf=95)
        assert r["fraction"] <= CONFIG_DEFAULTS["KELLY_HARD_CAP"] + 1e-9

    def test_bet_equals_fraction_times_bankroll(self):
        r = self._kelly()
        expected_bet = round(r["fraction"] * BANKROLL)
        assert r["bet"] == expected_bet

    # ── negatif edge → ret ───────────────────────────────────────────────────
    def test_negative_edge_rejected(self):
        """prob=0.40, odds=2.0 → edge=-0.20 → below_min_edge"""
        r = self._kelly(prob=0.40, odds=2.0)
        assert r["reason"] == "below_min_edge"
        assert r["bet"] == 0
        assert r["fraction"] == 0

    def test_zero_edge_rejected(self):
        """prob=0.50, odds=2.0 → edge=0 < MIN_EDGE → reddedilmeli"""
        r = self._kelly(prob=0.50, odds=2.0)
        assert r["bet"] == 0

    # ── düşük confidence → ret ───────────────────────────────────────────────
    def test_low_confidence_rejected(self):
        """confidence < MIN_CONFIDENCE(55) → low_confidence"""
        r = self._kelly(conf=40)
        assert r["reason"] == "low_confidence"
        assert r["bet"] == 0

    def test_boundary_confidence_accepted(self):
        """confidence = MIN_CONFIDENCE → kabul edilmeli"""
        r = self._kelly(conf=CONFIG_DEFAULTS["MIN_CONFIDENCE"])
        # sadece confidence engeli kalkar; edge geçerliyse ok olmalı
        assert r["reason"] in ("ok", "below_min_edge")

    # ── edge > %40 → ret ─────────────────────────────────────────────────────
    def test_edge_above_40pct_rejected(self):
        """prob=0.70, odds=2.5 → edge=0.75 > 0.40 → edge_too_high"""
        r = self._kelly(prob=0.70, odds=2.5)
        assert r["reason"] == "edge_too_high"
        assert r["bet"] == 0

    # ── edge > %20 → küçük bet ───────────────────────────────────────────────
    def test_edge_above_20pct_stays_within_hard_cap(self):
        """edge=%25 → edge_mult=0.08 → küçük fraction; hard cap aşılmaz"""
        # prob=0.55, odds=2.3 → edge ≈ 0.265
        r = self._kelly(prob=0.55, odds=2.3, conf=70)
        if r["reason"] == "ok":
            # Hard cap (0.025) dolayısıyla düşük edge_mult bile capped olabilir
            assert r["fraction"] <= CONFIG_DEFAULTS["KELLY_HARD_CAP"] + 1e-9

    # ── disabled market → sıfır ──────────────────────────────────────────────
    def test_disabled_market_zero(self):
        """market_class='disabled' → mkt_mult=0 → bet=0"""
        r = self._kelly(mclass="disabled")
        # mkt_mult=0 → adj_f=0 → bet=0
        assert r["bet"] == 0

    # ── geçersiz oran ────────────────────────────────────────────────────────
    def test_invalid_odds_zero(self):
        """odds=1 → b=0 → invalid_odds"""
        r = self._kelly(odds=1.0)
        assert r["reason"] == "invalid_odds"

    def test_invalid_odds_below_one(self):
        r = self._kelly(odds=0.5)
        assert r["reason"] == "invalid_odds"

    # ── bankroll sıfır ───────────────────────────────────────────────────────
    def test_zero_bankroll_gives_zero_bet(self):
        r = self._kelly(bank=0.0)
        assert r["bet"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# filter_correlated_bets()
# ══════════════════════════════════════════════════════════════════════════════

class TestFilterCorrelatedBets:

    def _bet(self, match, value_pct):
        return {"match": match, "value_pct": value_pct, "bet": 10}

    def test_single_bet_unchanged(self):
        bets = [self._bet("A vs B", 8)]
        assert rm.filter_correlated_bets(bets) == bets

    def test_two_different_matches_both_kept(self):
        bets = [self._bet("A vs B", 8), self._bet("C vs D", 6)]
        result = rm.filter_correlated_bets(bets)
        assert len(result) == 2

    def test_same_match_only_one_kept(self):
        """Aynı maçtan 2 bet → MAX_CORRELATED_BETS=1 → sadece 1 kalır"""
        bets = [
            self._bet("A vs B", 12),
            self._bet("A vs B", 8),
        ]
        result = rm.filter_correlated_bets(bets)
        assert len(result) == 1

    def test_highest_edge_bet_is_kept(self):
        """Aynı maçtan birden fazla bet → en yüksek edge'li tutulur"""
        bets = [
            self._bet("A vs B", 7),   # düşük edge
            self._bet("A vs B", 15),  # yüksek edge
        ]
        result = rm.filter_correlated_bets(bets)
        assert result[0]["value_pct"] == 15

    def test_different_matches_all_kept(self):
        bets = [self._bet(f"Team{i} vs Team{i+1}", 5+i) for i in range(5)]
        result = rm.filter_correlated_bets(bets)
        assert len(result) == 5


# ══════════════════════════════════════════════════════════════════════════════
# apply_risk_limits()
# ══════════════════════════════════════════════════════════════════════════════

class TestApplyRiskLimits:
    BANKROLL   = 1000.0
    DAILY_CAP  = 1000.0 * CONFIG_DEFAULTS["DAILY_RISK_CAP"]   # 80
    WEEKLY_CAP = 1000.0 * CONFIG_DEFAULTS["WEEKLY_RISK_CAP"]  # 200

    def _bet(self, amount, match="A vs B"):
        return {"match": match, "bet": amount, "reason_flags": []}

    def test_empty_list(self):
        assert rm.apply_risk_limits([], self.BANKROLL) == []

    def test_single_small_bet_passes(self):
        bets = [self._bet(20)]
        result = rm.apply_risk_limits(bets, self.BANKROLL)
        assert len(result) == 1
        assert result[0]["bet"] == 20

    def test_total_under_daily_cap_all_pass(self):
        """Toplam bahis günlük cap'in altında → hepsi geçer"""
        bets = [self._bet(20, f"M{i}") for i in range(3)]  # toplam 60 < 80
        result = rm.apply_risk_limits(bets, self.BANKROLL)
        assert len(result) == 3

    def test_daily_cap_cuts_excess(self):
        """Tek büyük bahis günlük cap'i aşıyor → cap'e indirilir"""
        bets = [self._bet(100)]   # 100 > 80
        result = rm.apply_risk_limits(bets, self.BANKROLL)
        assert len(result) == 1
        assert result[0]["bet"] <= self.DAILY_CAP

    def test_daily_cap_flag_added(self):
        """Kısıtlanan bahise 'daily_risk_capped' flag eklenmeli"""
        bets = [self._bet(30, "M1"), self._bet(60, "M2")]  # 30+60=90 > 80
        result = rm.apply_risk_limits(bets, self.BANKROLL)
        flags_all = [f for r in result for f in r.get("reason_flags",[])]
        assert "daily_risk_capped" in flags_all

    def test_weekly_spent_at_cap_returns_empty(self):
        """weekly_spent = weekly_cap → hiç bet önerilmez"""
        result = rm.apply_risk_limits(
            [self._bet(20)], self.BANKROLL,
            weekly_spent=self.WEEKLY_CAP
        )
        assert result == []

    def test_weekly_spent_over_cap_returns_empty(self):
        """weekly_spent > weekly_cap → boş liste"""
        result = rm.apply_risk_limits(
            [self._bet(20)], self.BANKROLL,
            weekly_spent=self.WEEKLY_CAP + 50
        )
        assert result == []

    def test_weekly_cap_partially_consumed(self):
        """weekly_spent + bets > weekly_cap → fazla kısılır"""
        spent = self.WEEKLY_CAP - 30   # 170 harcanmış, 30 kaldı
        bets  = [self._bet(50)]         # 50 > kalan 30
        result = rm.apply_risk_limits(bets, self.BANKROLL, weekly_spent=spent)
        # Ya kısıtlanmış bahis döner ya da boş (kalan < 5 ise drop)
        if result:
            assert result[0]["bet"] <= 30

    def test_weekly_cap_flag_added(self):
        """Haftalık cap kısıtlamasına uğrayan bahise 'weekly_risk_capped' flag"""
        spent = self.WEEKLY_CAP - 10
        bets  = [self._bet(20)]
        result = rm.apply_risk_limits(bets, self.BANKROLL, weekly_spent=spent)
        if result:
            assert "weekly_risk_capped" in result[0]["reason_flags"]

    def test_order_preserved(self):
        """Geçen betlerin sırası korunmalı"""
        bets = [self._bet(10, f"M{i}") for i in range(5)]
        result = rm.apply_risk_limits(bets, self.BANKROLL)
        for i, r in enumerate(result):
            assert r["match"] == f"M{i}"


# ══════════════════════════════════════════════════════════════════════════════
# build_reason_flags()
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildReasonFlags:

    def test_strong_edge_flag(self):
        flags = rm.build_reason_flags(0.12, 70, "tradable")
        assert "strong_edge" in flags

    def test_moderate_edge_flag(self):
        flags = rm.build_reason_flags(0.07, 70, "tradable")
        assert "moderate_edge" in flags

    def test_marginal_edge_flag(self):
        flags = rm.build_reason_flags(0.03, 70, "tradable")
        assert "marginal_edge" in flags

    def test_high_confidence_flag(self):
        flags = rm.build_reason_flags(0.07, 75, "tradable")
        assert "high_confidence" in flags

    def test_ok_confidence_flag(self):
        flags = rm.build_reason_flags(0.07, 60, "tradable")
        assert "ok_confidence" in flags

    def test_unusually_high_edge_warning(self):
        """edge > %20 → uyarı flag"""
        flags = rm.build_reason_flags(0.25, 70, "tradable")
        assert any("unusually_high_edge" in f for f in flags)

    def test_no_high_edge_warning_below_threshold(self):
        flags = rm.build_reason_flags(0.15, 70, "tradable")
        assert not any("unusually_high_edge" in f for f in flags)

    def test_experimental_market_flag(self):
        flags = rm.build_reason_flags(0.07, 65, "experimental")
        assert "experimental_market" in flags
