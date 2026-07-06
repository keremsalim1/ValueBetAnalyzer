"""
test_settlement.py
──────────────────
Kapsanan davranışlar:
  • settle_bet() → 13 market için 2-1, 0-0, 1-1, 3-0 skorlarıyla
    kesin beklenen sonuç (True/False)
  • ht marketleri → ht_home/ht_away eksikse ValueError
  • Bilinmeyen market → ValueError
  • Sınır değerleri: over/under eşik skorları
"""
import pytest
from settlement import settle_bet


# ── yardımcı ──────────────────────────────────────────────────────────────────
def s(market, h, a, ht_h=None, ht_a=None):
    return settle_bet(market, h, a, ht_home=ht_h, ht_away=ht_a)


# ══════════════════════════════════════════════════════════════════════════════
# 1X2
# ══════════════════════════════════════════════════════════════════════════════

class TestHomeDrawAway:

    # ── home ─────────────────────────────────────────────────────────────────
    def test_home_wins_2_1(self):
        assert s("home", 2, 1) is True

    def test_home_loses_0_1(self):
        assert s("home", 0, 1) is False

    def test_home_draw_0_0(self):
        assert s("home", 0, 0) is False

    def test_home_wins_1_0(self):
        assert s("home", 1, 0) is True

    # ── draw ─────────────────────────────────────────────────────────────────
    def test_draw_0_0(self):
        assert s("draw", 0, 0) is True

    def test_draw_2_2(self):
        assert s("draw", 2, 2) is True

    def test_draw_false_on_2_1(self):
        assert s("draw", 2, 1) is False

    def test_draw_false_on_0_1(self):
        assert s("draw", 0, 1) is False

    # ── away ─────────────────────────────────────────────────────────────────
    def test_away_wins_0_1(self):
        assert s("away", 0, 1) is True

    def test_away_wins_1_3(self):
        assert s("away", 1, 3) is True

    def test_away_false_on_2_1(self):
        assert s("away", 2, 1) is False

    def test_away_false_on_draw(self):
        assert s("away", 1, 1) is False


# ══════════════════════════════════════════════════════════════════════════════
# Üst/Alt
# ══════════════════════════════════════════════════════════════════════════════

class TestOverUnder:

    # ── over25 / under25 ─────────────────────────────────────────────────────
    def test_over25_true_on_3_goals(self):
        assert s("over25", 2, 1) is True   # 3 gol

    def test_over25_true_on_4_goals(self):
        assert s("over25", 3, 1) is True

    def test_over25_false_on_2_goals(self):
        assert s("over25", 1, 1) is False  # 2 gol

    def test_over25_false_on_0_0(self):
        assert s("over25", 0, 0) is False

    def test_under25_true_on_0_0(self):
        assert s("under25", 0, 0) is True

    def test_under25_true_on_2_goals(self):
        assert s("under25", 1, 1) is True

    def test_under25_false_on_3_goals(self):
        assert s("under25", 2, 1) is False

    # ── over15 / under15 ─────────────────────────────────────────────────────
    def test_over15_true_on_2_goals(self):
        assert s("over15", 1, 1) is True

    def test_over15_false_on_1_goal(self):
        assert s("over15", 1, 0) is False

    def test_under15_true_on_1_goal(self):
        assert s("under15", 1, 0) is True

    def test_under15_false_on_2_goals(self):
        assert s("under15", 2, 0) is False

    # ── over35 / under35 ─────────────────────────────────────────────────────
    def test_over35_true_on_4_goals(self):
        assert s("over35", 3, 1) is True

    def test_over35_false_on_3_goals(self):
        assert s("over35", 2, 1) is False

    def test_under35_true_on_3_goals(self):
        assert s("under35", 2, 1) is True

    def test_under35_false_on_4_goals(self):
        assert s("under35", 3, 1) is False


# ══════════════════════════════════════════════════════════════════════════════
# BTTS
# ══════════════════════════════════════════════════════════════════════════════

class TestBtts:

    def test_btts_yes_both_score(self):
        assert s("btts_yes", 2, 1) is True

    def test_btts_yes_false_when_away_no_goal(self):
        assert s("btts_yes", 2, 0) is False

    def test_btts_yes_false_0_0(self):
        assert s("btts_yes", 0, 0) is False

    def test_btts_no_clean_sheet(self):
        assert s("btts_no", 2, 0) is True

    def test_btts_no_false_both_score(self):
        assert s("btts_no", 1, 1) is False

    def test_btts_no_true_0_0(self):
        assert s("btts_no", 0, 0) is True


# ══════════════════════════════════════════════════════════════════════════════
# Double Chance
# ══════════════════════════════════════════════════════════════════════════════

class TestDoubleChance:

    # dc_1x: ev veya beraberlik
    def test_dc_1x_home_win(self):
        assert s("dc_1x", 2, 1) is True

    def test_dc_1x_draw(self):
        assert s("dc_1x", 1, 1) is True

    def test_dc_1x_away_win(self):
        assert s("dc_1x", 0, 1) is False

    # dc_x2: beraberlik veya deplasman
    def test_dc_x2_away_win(self):
        assert s("dc_x2", 0, 1) is True

    def test_dc_x2_draw(self):
        assert s("dc_x2", 1, 1) is True

    def test_dc_x2_home_win(self):
        assert s("dc_x2", 2, 0) is False

    # dc_12: ev veya deplasman (beraberlik yok)
    def test_dc_12_home_win(self):
        assert s("dc_12", 2, 1) is True

    def test_dc_12_away_win(self):
        assert s("dc_12", 0, 2) is True

    def test_dc_12_draw_false(self):
        assert s("dc_12", 1, 1) is False

    def test_dc_12_0_0_false(self):
        assert s("dc_12", 0, 0) is False


# ══════════════════════════════════════════════════════════════════════════════
# İlk Yarı Marketleri
# ══════════════════════════════════════════════════════════════════════════════

class TestHalfTime:

    def test_ht_home_win(self):
        assert s("ht_home", 2, 1, ht_h=1, ht_a=0) is True

    def test_ht_home_false_draw_ht(self):
        assert s("ht_home", 2, 1, ht_h=0, ht_a=0) is False

    def test_ht_draw(self):
        assert s("ht_draw", 2, 1, ht_h=0, ht_a=0) is True

    def test_ht_draw_false(self):
        assert s("ht_draw", 2, 1, ht_h=1, ht_a=0) is False

    def test_ht_away_win(self):
        assert s("ht_away", 2, 3, ht_h=0, ht_a=1) is True

    def test_ht_away_false(self):
        assert s("ht_away", 2, 3, ht_h=1, ht_a=0) is False

    def test_ht_missing_scores_raises(self):
        """İY skoru verilmezse ValueError fırlatılmalı"""
        with pytest.raises(ValueError, match="ilk yarı skoru"):
            s("ht_home", 2, 1)

    def test_ht_none_scores_raises(self):
        with pytest.raises(ValueError):
            settle_bet("ht_draw", 1, 1, ht_home=None, ht_away=None)


# ══════════════════════════════════════════════════════════════════════════════
# Hata Durumları
# ══════════════════════════════════════════════════════════════════════════════

class TestErrors:

    def test_unknown_market_raises(self):
        with pytest.raises(ValueError, match="Desteklenmeyen market"):
            s("corner_o85", 2, 1)

    def test_completely_unknown_raises(self):
        with pytest.raises(ValueError):
            s("nonexistent_market", 1, 0)


# ══════════════════════════════════════════════════════════════════════════════
# Kapsamlı matris: 2-1 ve 0-0 için tüm 13 market
# ══════════════════════════════════════════════════════════════════════════════

class TestAllMarketsMatrix:
    """
    2-1 skoru ve 0-0 skoru için tüm non-ht marketların beklenen sonucu.
    """

    MARKETS_2_1 = {
        "home":     True,
        "draw":     False,
        "away":     False,
        "over25":   True,    # 2+1=3 ≥ 3
        "under25":  False,
        "over15":   True,    # 3 ≥ 2
        "under15":  False,
        "over35":   False,   # 3 < 4
        "under35":  True,
        "btts_yes": True,    # 2>0 AND 1>0 → her iki takım da gol attı
        "btts_no":  False,
        "dc_1x":    True,
        "dc_x2":    False,
        "dc_12":    True,
    }

    MARKETS_0_0 = {
        "home":     False,
        "draw":     True,
        "away":     False,
        "over25":   False,
        "under25":  True,
        "over15":   False,
        "under15":  True,
        "over35":   False,
        "under35":  True,
        "btts_yes": False,
        "btts_no":  True,
        "dc_1x":    True,
        "dc_x2":    True,
        "dc_12":    False,
    }

    @pytest.mark.parametrize("market,expected", MARKETS_2_1.items())
    def test_score_2_1(self, market, expected):
        assert s(market, 2, 1) is expected

    @pytest.mark.parametrize("market,expected", MARKETS_0_0.items())
    def test_score_0_0(self, market, expected):
        assert s(market, 0, 0) is expected
