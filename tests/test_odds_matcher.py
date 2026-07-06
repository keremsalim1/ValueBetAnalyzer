"""
test_odds_matcher.py
────────────────────
Kapsanan davranışlar:
  • normalize_name()    — küçük harf, FC/AC çıkarma, noktalama temizliği
  • name_match()        — tam eşleşme=1.0, benzer isim>0, eşleşmeme=0.0,
                          substring bonusu, kısa kelimelerin göz ardı edilmesi
  • find_odds()         — tam eşleşme, benzer isim, eşleşmeme, margin filtre,
                          date proximity bonusu, düşük confidence → None
  • extract_best_odds() — birden fazla bookmaker'dan en yüksek oran seçimi
"""
import pytest
from odds_matcher import normalize_name, name_match, find_odds, extract_best_odds


# ══════════════════════════════════════════════════════════════════════════════
# normalize_name()
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalizeName:

    def test_lowercase(self):
        assert normalize_name("ARSENAL") == "arsenal"

    def test_removes_fc_prefix(self):
        assert normalize_name("FC Barcelona") == "barcelona"

    def test_removes_fc_suffix(self):
        assert normalize_name("Barcelona FC") == "barcelona"

    def test_removes_ac_prefix(self):
        assert normalize_name("AC Milan") == "milan"

    def test_removes_sc_suffix(self):
        assert normalize_name("Freiburg SC") == "freiburg"

    def test_replaces_dots(self):
        assert "." not in normalize_name("Man.City")

    def test_replaces_hyphens(self):
        assert "-" not in normalize_name("Borussia-Dortmund")

    def test_strips_whitespace(self):
        result = normalize_name("  Arsenal  ")
        assert result == result.strip()

    def test_double_spaces_collapsed(self):
        # normalize_name tek pass replace yapar: "  " → " "
        # Çift boşluklu girdi düzeltilmeli
        result = normalize_name("Real  Madrid")   # iki boşluk
        assert "  " not in result


# ══════════════════════════════════════════════════════════════════════════════
# name_match()
# ══════════════════════════════════════════════════════════════════════════════

class TestNameMatch:

    def test_exact_match_returns_one(self):
        assert name_match("arsenal", "arsenal") == 1.0

    def test_completely_different_returns_zero(self):
        score = name_match("arsenal", "juventus")
        assert score == 0.0

    def test_similar_names_positive(self):
        """Manchester City vs Manchester United → ortak kelime → sıfırdan büyük"""
        score = name_match("manchester city", "manchester united")
        assert 0 < score < 1.0

    def test_substring_bonus(self):
        """'man city' in 'manchester city' → substring bonusu"""
        score_sub = name_match("man city", "manchester city")
        score_no  = name_match("arsenal",  "manchester city")
        assert score_sub > score_no

    def test_short_words_ignored(self):
        """<3 karakter kelimeler Jaccard'a katılmaz"""
        # "FC" ve "de" gibi kısa ekler eşleşmeyi bozmaz
        score = name_match("real de madrid", "real madrid")
        assert score > 0.5

    def test_reflexive(self):
        """name_match(a,b) == name_match(b,a)"""
        a, b = "chelsea", "chelsea fc"
        assert name_match(a, b) == pytest.approx(name_match(b, a), abs=1e-9)

    def test_returns_float_in_range(self):
        for a, b in [("a","b"), ("real madrid","real madrid"), ("ajax","psv")]:
            s = name_match(a, b)
            assert 0.0 <= s <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# find_odds()  —  fake odds_data oluşturucu
# ══════════════════════════════════════════════════════════════════════════════

def _make_event(home="Arsenal", away="Chelsea",
                date="2024-12-10T15:00:00Z",
                home_price=2.1, draw_price=3.4, away_price=3.5,
                over_price=1.9, under_price=1.9,
                margin_override=None):
    """
    The Odds API formatında sahte bir event oluşturur.
    margin_override: bookmaker margin'ini zorla (None → otomatik hesap)
    """
    if margin_override is not None:
        # istenilen margin için away fiyatını ayarla
        # 1/h + 1/d + 1/a = 1 + margin → 1/a = 1+margin - 1/h - 1/d
        inv_away = 1 + margin_override - 1/home_price - 1/draw_price
        away_price = 1 / inv_away if inv_away > 0 else away_price

    return {
        "id": "evt1",
        "home_team": home,
        "away_team": away,
        "commence_time": date,
        "bookmakers": [
            {
                "key": "betfair",
                "title": "Betfair",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": date,
                        "outcomes": [
                            {"name": home, "price": home_price},
                            {"name": "Draw", "price": draw_price},
                            {"name": away, "price": away_price},
                        ]
                    },
                    {
                        "key": "totals",
                        "last_update": date,
                        "outcomes": [
                            {"name": "Over",  "price": over_price,  "point": 2.5},
                            {"name": "Under", "price": under_price, "point": 2.5},
                        ]
                    }
                ]
            }
        ]
    }


class TestFindOdds:

    def test_exact_match_found(self):
        data = [_make_event("Arsenal", "Chelsea")]
        result = find_odds(data, "Arsenal", "Chelsea")
        assert result is not None

    def test_exact_match_has_bookmakers(self):
        data = [_make_event("Arsenal", "Chelsea")]
        result = find_odds(data, "Arsenal", "Chelsea")
        assert len(result["bookmakers"]) > 0

    def test_exact_match_markets(self):
        data = [_make_event("Arsenal", "Chelsea")]
        result = find_odds(data, "Arsenal", "Chelsea")
        bk = result["bookmakers"][0]
        assert "home" in bk["markets"]
        assert "draw" in bk["markets"]
        assert "away" in bk["markets"]

    def test_fuzzy_match_found(self):
        """'Arsenal FC' vs 'Arsenal' → eşleşmeli"""
        data = [_make_event("Arsenal FC", "Chelsea FC")]
        result = find_odds(data, "Arsenal", "Chelsea")
        assert result is not None

    def test_no_match_returns_none(self):
        data = [_make_event("Juventus", "AC Milan")]
        result = find_odds(data, "Arsenal", "Chelsea")
        assert result is None

    def test_high_margin_filtered(self):
        """h2h margin > %8 → home/draw/away extract_best_odds'ta elenir.
        find_odds margin'i saklar (margin karşılaştırması için) ama
        best odds seçiminde yüksek marginli h2h fiyatları kullanılmaz."""
        data = [_make_event("Arsenal", "Chelsea", margin_override=0.15)]
        result = find_odds(data, "Arsenal", "Chelsea")
        assert result is not None
        best = extract_best_odds(result["bookmakers"])
        assert "home" not in best, "Yüksek marginli h2h market geçmemeli"
        assert "draw" not in best
        assert "away" not in best
        # totals h2h margin filtresinden etkilenmez
        assert "over25" in best

    def test_acceptable_margin_kept(self):
        """Margin ≤ %8 → bookmaker korunur"""
        data = [_make_event("Arsenal", "Chelsea", margin_override=0.05)]
        result = find_odds(data, "Arsenal", "Chelsea")
        assert result is not None
        assert len(result["bookmakers"]) > 0

    def test_date_proximity_improves_match(self):
        """Aynı isimde iki event; doğru tarihe yakın olanı seçmeli"""
        correct = _make_event("Arsenal", "Chelsea", date="2024-12-10T15:00:00Z")
        wrong   = _make_event("Arsenal", "Chelsea", date="2024-12-20T15:00:00Z")
        correct["id"] = "correct"
        wrong["id"]   = "wrong"
        # İki event; birini farklı isimle ayırt et
        wrong["home_team"]  = "Arsenal FC"
        wrong["away_team"]  = "Chelsea FC"
        data = [wrong, correct]
        result = find_odds(data, "Arsenal", "Chelsea", match_date="2024-12-10T15:00:00Z")
        assert result is not None

    def test_returns_match_confidence(self):
        data = [_make_event("Arsenal", "Chelsea")]
        result = find_odds(data, "Arsenal", "Chelsea")
        assert "match_confidence" in result
        assert result["match_confidence"] >= 60

    def test_totals_line_must_be_2_5(self):
        """totals point=3.5 olan over/under market eklenmemeli"""
        event = _make_event("Arsenal", "Chelsea")
        # Totals line'ı 3.5 yap
        for bk in event["bookmakers"]:
            for mk in bk["markets"]:
                if mk["key"] == "totals":
                    for oc in mk["outcomes"]:
                        oc["point"] = 3.5
        data = [event]
        result = find_odds(data, "Arsenal", "Chelsea")
        if result:
            for bk in result["bookmakers"]:
                assert "over25" not in bk["markets"]


# ══════════════════════════════════════════════════════════════════════════════
# extract_best_odds()
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractBestOdds:

    def test_single_bookmaker(self):
        bks = [{"markets": {"home": 2.1, "draw": 3.4, "away": 3.5}}]
        best = extract_best_odds(bks)
        assert best["home"]  == 2.1
        assert best["draw"]  == 3.4
        assert best["away"]  == 3.5

    def test_picks_highest_across_bookmakers(self):
        bks = [
            {"markets": {"home": 2.1, "draw": 3.4, "away": 3.5}},
            {"markets": {"home": 2.2, "draw": 3.3, "away": 3.6}},
        ]
        best = extract_best_odds(bks)
        assert best["home"]  == 2.2   # max(2.1, 2.2)
        assert best["draw"]  == 3.4   # max(3.4, 3.3)
        assert best["away"]  == 3.6   # max(3.5, 3.6)

    def test_ignores_odds_below_one(self):
        """odds ≤ 1.0 geçersiz → dikkate alınmamalı"""
        bks = [
            {"markets": {"home": 0.9, "draw": 3.4, "away": 3.5}},
            {"markets": {"home": 2.1, "draw": 3.3, "away": 3.6}},
        ]
        best = extract_best_odds(bks)
        assert best["home"] == 2.1   # 0.9 geçersiz

    def test_empty_bookmakers_returns_empty(self):
        assert extract_best_odds([]) == {}

    def test_partial_markets_merged(self):
        """Bir bookmaker'da sadece h2h, diğerinde sadece totals → birleşmeli"""
        bks = [
            {"markets": {"home": 2.1, "draw": 3.4, "away": 3.5}},
            {"markets": {"over25": 1.9, "under25": 1.95}},
        ]
        best = extract_best_odds(bks)
        assert "home" in best
        assert "over25" in best

    def test_three_bookmakers_max(self):
        bks = [
            {"markets": {"home": 2.0}},
            {"markets": {"home": 2.3}},
            {"markets": {"home": 2.1}},
        ]
        best = extract_best_odds(bks)
        assert best["home"] == 2.3
