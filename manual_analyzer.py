"""Manuel veri girişli analiz - API gerektirmez"""
import logging
from config import LEAGUES, STRENGTH_CAP, MIN_EDGE, get_market_class
from probability_model import match_probs
from risk_manager import value_calc, adaptive_kelly, build_reason_flags

logger = logging.getLogger(__name__)

DEFAULT_AVG_H = 1.45
DEFAULT_AVG_A = 1.15
DEFAULT_CORNER = 10.0

LEAGUE_DEFAULTS = {
    "league": {"avg_h": 1.45, "avg_a": 1.15, "avg_corner": 10.0},
    "cup":    {"avg_h": 1.35, "avg_a": 1.05, "avg_corner": 9.5},
}

# ─── FAKTÖR TANIMLARI ───
FACTOR_EFFECTS = {
    "motivation_normal":  {"atk": 0.00, "def": 0.00},
    "motivation_high":    {"atk": 0.08, "def": 0.05},
    "motivation_low":     {"atk":-0.08, "def":-0.05},
    "motivation_must_win":{"atk": 0.12, "def": 0.03},
    "form_normal":        {"atk": 0.00, "def": 0.00},
    "form_hot":           {"atk": 0.07, "def": 0.05},
    "form_cold":          {"atk":-0.07, "def":-0.05},
    "form_inconsistent":  {"atk":-0.03, "def":-0.03},
    "rest_normal":        {"atk": 0.00, "def": 0.00},
    "rest_short":         {"atk":-0.05, "def":-0.04},
    "rest_long":          {"atk": 0.04, "def": 0.03},
}

# Sakatlık/ceza etkisi oyuncu tipine göre (eski sistem, geriye uyumluluk)
ABSENCE_IMPACT = {
    "bench":      {"atk":-0.02, "def":-0.01},
    "starter":    {"atk":-0.06, "def":-0.04},
    "key_player": {"atk":-0.12, "def":-0.07},
    "top_scorer": {"atk":-0.18, "def":-0.03},
    "captain":    {"atk":-0.08, "def":-0.10},
    "goalkeeper":  {"atk": 0.00, "def":-0.15},
}

# ─── YENİ KADRO / SAKATLIK SİSTEMİ ───────────────────────────────────────────

# Pozisyon → {stat: multiplier_when_present}
# Eksiklikte: etkisi = (1 - mult) × severity
POSITION_EFFECTS = {
    "GK": {"def": 0.92},
    "CB": {"def": 0.95},
    "FB": {"def": 0.97, "atk": 0.98},
    "CM": {"atk": 0.97, "def": 0.97},
    "AM": {"atk": 0.93},
    "ST": {"atk": 0.88},
    "WG": {"atk": 0.91},
}

SEVERITY_MULT = {
    "definite_out": 1.0,
    "75pct_out":    0.75,
    "doubtful":     0.50,
}

# ─── HAVA DURUMU / MAÇ ÖNEMİ ─────────────────────────────────────────────────

WEATHER_ATK = {
    "heavy_rain": 0.94,
    "snow":       0.94,
    "rain":       0.97,
    "wind":       0.96,
    "normal":     1.0,
}

WEATHER_LABELS = {
    "heavy_rain": "Atak ×0.94, O2.5 ×0.93",
    "snow":       "Atak ×0.94, O2.5 ×0.93",
    "rain":       "Atak ×0.97",
    "wind":       "Atak ×0.96",
    "normal":     "Etki yok",
}

IMPORTANCE_LABELS = {
    "must_win":   "Ev sahibi Atak ×1.05",
    "relegation": "Ev sahibi Atak ×1.05",
    "cup_final":  "Varyans +%5",
    "derby":      "Varyans +%10",
    "normal":     "Etki yok",
}


def _compute_injury_mults(injuries: list, team: str) -> tuple:
    """
    Yeni pozisyon bazlı sakatlık sistemi.
    injuries: [{"team","player_name","position","severity",...}]
    Returns: (atk_mult, def_mult, players_out_labels)
    CAP: minimum 0.70
    """
    atk_mult = 1.0
    def_mult = 1.0
    players = []
    for inj in injuries:
        if inj.get("team") != team:
            continue
        pos  = inj.get("position", "CM")
        sev  = SEVERITY_MULT.get(inj.get("severity", "doubtful"), 0.5)
        effects = POSITION_EFFECTS.get(pos, {"atk": 0.97, "def": 0.97})
        for stat, pos_mult in effects.items():
            effect = (1 - pos_mult) * sev
            if stat == "atk":
                atk_mult *= (1 - effect)
            else:
                def_mult *= (1 - effect)
        name = inj.get("player_name") or "?"
        players.append(f"{name} ({pos})")
    return max(0.70, round(atk_mult, 3)), max(0.70, round(def_mult, 3)), players


def _rest_mult(days: int) -> float:
    """Dinlenme günü → xG çarpanı (strength_model.py mantığı)."""
    if days < 3:  return 0.95   # yorgunluk
    if days > 7:  return 1.03   # dinç
    return 1.0


def _avg(games: list) -> tuple:
    if not games:
        return 0.0, 0.0
    gs = sum(g[0] for g in games) / len(games)
    gc = sum(g[1] for g in games) / len(games)
    return gs, gc


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _factors_to_adjustment(factors: list, absences: list = None) -> tuple:
    """
    factors: ["motivation_high", "form_hot", "rest_short"] gibi string listesi
    absences: [{"type":"key_player"},{"type":"starter"},{"type":"goalkeeper"}] gibi dict listesi
    """
    atk_adj = 0.0
    def_adj = 0.0
    for f in factors:
        if f in FACTOR_EFFECTS:
            atk_adj += FACTOR_EFFECTS[f]["atk"]
            def_adj += FACTOR_EFFECTS[f]["def"]
    # Sakatlık/ceza listesi
    if absences:
        for ab in absences:
            ab_type = ab.get("type", "starter") if isinstance(ab, dict) else str(ab)
            if ab_type in ABSENCE_IMPACT:
                atk_adj += ABSENCE_IMPACT[ab_type]["atk"]
                def_adj += ABSENCE_IMPACT[ab_type]["def"]
    return atk_adj, def_adj


def _compute_strength(last_10, home_5, away_5, avg_h, avg_a, atk_adj, def_adj):
    gs_10, gc_10 = _avg(last_10)
    gs_home, gc_home = _avg(home_5)
    gs_away, gc_away = _avg(away_5)

    la = (avg_h + avg_a) / 2 if (avg_h + avg_a) > 0 else 1.0

    if home_5:
        home_atk = gs_home / avg_h if avg_h > 0 else 1.0
        home_def = gc_home / avg_a if avg_a > 0 else 1.0
    else:
        home_atk = gs_10 / la if la > 0 else 1.0
        home_def = gc_10 / la if la > 0 else 1.0

    if away_5:
        away_atk = gs_away / avg_a if avg_a > 0 else 1.0
        away_def = gc_away / avg_h if avg_h > 0 else 1.0
    else:
        away_atk = gs_10 / la if la > 0 else 1.0
        away_def = gc_10 / la if la > 0 else 1.0

    home_atk *= (1 + atk_adj)
    home_def *= (1 + def_adj)
    away_atk *= (1 + atk_adj)
    away_def *= (1 + def_adj)

    home_atk = _clamp(home_atk, *STRENGTH_CAP)
    home_def = _clamp(home_def, *STRENGTH_CAP)
    away_atk = _clamp(away_atk, *STRENGTH_CAP)
    away_def = _clamp(away_def, *STRENGTH_CAP)

    n = len(last_10) if last_10 else 0
    home_n = len(home_5) if home_5 else 0
    away_n = len(away_5) if away_5 else 0

    return {
        "atk": round((home_atk + away_atk) / 2, 2),
        "def": round((home_def + away_def) / 2, 2),
        "home_atk": round(home_atk, 2),
        "home_def": round(home_def, 2),
        "away_atk": round(away_atk, 2),
        "away_def": round(away_def, 2),
        "n": n,
        "home_n": home_n,
        "away_n": away_n,
    }


def _compute_confidence(data: dict, hs: dict, as_: dict, has_odds: bool, total_adj: float) -> int:
    score = 60

    h10 = data.get("home_last_10") or []
    a10 = data.get("away_last_10") or []
    if len(h10) < 5:
        score -= 10
    if len(a10) < 5:
        score -= 10
    if not data.get("home_last_5_home"):
        score -= 5
    if not data.get("away_last_5_away"):
        score -= 5
    if data.get("neutral"):
        score -= 5
    if has_odds:
        score += 10
    # Çok fazla negatif faktör varsa güven düşer
    if total_adj < -0.20:
        score -= 8
    elif total_adj < -0.10:
        score -= 4

    return _clamp(score, 0, 100)


def analyze_manual_input(data: dict) -> dict:
    league_type = data.get("league_type", "league")
    neutral = bool(data.get("neutral", False))
    bankroll = float(data.get("bankroll", 1000))

    ld = LEAGUE_DEFAULTS.get(league_type, LEAGUE_DEFAULTS["league"])
    avg_h = ld["avg_h"]
    avg_a = ld["avg_a"]
    avg_corner = ld["avg_corner"]

    home_last_10 = data.get("home_last_10") or []
    away_last_10 = data.get("away_last_10") or []
    home_last_5_home = data.get("home_last_5_home") or []
    away_last_5_away = data.get("away_last_5_away") or []

    # Faktörlerden adjustment hesapla
    home_factors = data.get("home_factors") or []
    away_factors = data.get("away_factors") or []
    home_absences = data.get("home_absences") or []
    away_absences = data.get("away_absences") or []
    h_atk_adj, h_def_adj = _factors_to_adjustment(home_factors, home_absences)
    a_atk_adj, a_def_adj = _factors_to_adjustment(away_factors, away_absences)

    # Eski format desteği (geriye uyumluluk)
    h_atk_adj += data.get("home_attack_adjustment", 0.0)
    h_def_adj += data.get("home_defense_adjustment", 0.0)
    a_atk_adj += data.get("away_attack_adjustment", 0.0)
    a_def_adj += data.get("away_defense_adjustment", 0.0)

    hs = _compute_strength(
        home_last_10, home_last_5_home, None,
        avg_h, avg_a, h_atk_adj, h_def_adj,
    )
    as_ = _compute_strength(
        away_last_10, None, away_last_5_away,
        avg_h, avg_a, a_atk_adj, a_def_adj,
    )

    hxg = round(hs["home_atk"] * as_["away_def"] * avg_h, 2)
    axg = round(as_["away_atk"] * hs["home_def"] * avg_a, 2)
    hxg = max(hxg, 0.1)
    axg = max(axg, 0.1)

    # ─── YENİ: Kadro / Sakatlik ──────────────────────────────────────────────
    injuries = data.get("injuries") or []
    h_atk_m, h_def_m, h_out = _compute_injury_mults(injuries, "home")
    a_atk_m, a_def_m, a_out = _compute_injury_mults(injuries, "away")
    # Saldırı: kendi atk düşer; Savunma: zayıf savunma rakibin golünü artırır
    hxg = hxg * h_atk_m * (2.0 - a_def_m)
    axg = axg * a_atk_m * (2.0 - h_def_m)

    injury_summary = None
    if injuries:
        injury_summary = {
            "home_atk_mult": h_atk_m,
            "home_def_mult": h_def_m,
            "away_atk_mult": a_atk_m,
            "away_def_mult": a_def_m,
            "home_players_out": h_out,
            "away_players_out": a_out,
        }

    # ─── YENİ: Bağlam Parametreleri ──────────────────────────────────────────
    weather    = data.get("weather", "normal")
    importance = data.get("match_importance", "normal")
    neutral_venue = bool(data.get("neutral_venue", False))
    home_rest  = max(1, min(14, int(data.get("home_rest_days", 4) or 4)))
    away_rest  = max(1, min(14, int(data.get("away_rest_days", 4) or 4)))

    # Tarafsız saha
    neutral = neutral or neutral_venue

    # Hava durumu
    w_mult = WEATHER_ATK.get(weather, 1.0)
    hxg *= w_mult
    axg *= w_mult

    # Maç önemi
    rho_adj = 1.0
    if importance in ("must_win", "relegation"):
        hxg *= 1.05   # ev sahibi daha motive
    elif importance == "cup_final":
        rho_adj = 0.9
    elif importance == "derby":
        rho_adj = 0.8

    # Dinlenme günleri
    hxg *= _rest_mult(home_rest)
    axg *= _rest_mult(away_rest)

    hxg = max(round(hxg, 2), 0.1)
    axg = max(round(axg, 2), 0.1)

    context_effects = {
        "weather":          weather,
        "weather_effect":   WEATHER_LABELS.get(weather, ""),
        "importance":       importance,
        "importance_effect": IMPORTANCE_LABELS.get(importance, ""),
        "neutral_venue":    neutral_venue,
        "home_rest_days":   home_rest,
        "away_rest_days":   away_rest,
    }

    # ─── OLASILIK ────────────────────────────────────────────────────────────
    rho = -0.05 * rho_adj
    probs = match_probs(hxg, axg, avg_corner, avg_h + avg_a, neutral, rho=rho)

    # Hava sonrası over25 ek düzeltme
    if weather in ("heavy_rain", "snow"):
        probs["over25"]  = probs.get("over25", 0) * 0.93
        probs["under25"] = max(0.0, 1.0 - probs["over25"])

    # ─── YENİ: Kullanıcı Tahmini ─────────────────────────────────────────────
    estimate_comparison = None
    estimate_error = None
    user_est = data.get("user_estimate")
    if user_est and user_est.get("home_win_pct") is not None:
        try:
            u_h = float(user_est.get("home_win_pct") or 0)
            u_d = float(user_est.get("draw_pct") or 0)
            u_a = float(user_est.get("away_win_pct") or 0)
            total = u_h + u_d + u_a
            if abs(total - 100) > 2:
                estimate_error = f"Toplam {total:.1f} olmalı (100 ± 2)"
            else:
                u_h /= 100; u_d /= 100; u_a /= 100
                m_h = probs["home_win"]; m_d = probs["draw"]; m_a = probs["away_win"]
                diffs = {"home": abs(m_h - u_h), "draw": abs(m_d - u_d), "away": abs(m_a - u_a)}
                max_diff = max(diffs.values())
                agreement = "high" if max_diff < 0.05 else "medium" if max_diff < 0.10 else "low"
                estimate_comparison = {
                    "model_home": round(m_h, 3), "user_home": round(u_h, 3),
                    "diff_home":  round(m_h - u_h, 3),
                    "model_draw": round(m_d, 3), "user_draw": round(u_d, 3),
                    "diff_draw":  round(m_d - u_d, 3),
                    "model_away": round(m_a, 3), "user_away": round(u_a, 3),
                    "diff_away":  round(m_a - u_a, 3),
                    "agreement_level":      agreement,
                    "largest_disagreement": max(diffs, key=diffs.get),
                }
        except Exception:
            estimate_error = "Geçersiz tahmin değerleri"

    # ─── ─────────────────────────────────────────────────────────────────────
    odds_input = data.get("odds") or {}
    has_odds = bool(odds_input)

    total_adj = h_atk_adj + h_def_adj + a_atk_adj + a_def_adj
    confidence = _compute_confidence(data, hs, as_, has_odds, total_adj)

    # Uygulanan faktörleri raporla
    applied_factors = {
        "home": {"factors": home_factors, "absences": home_absences, "atk_adj": round(h_atk_adj, 3), "def_adj": round(h_def_adj, 3)},
        "away": {"factors": away_factors, "absences": away_absences, "atk_adj": round(a_atk_adj, 3), "def_adj": round(a_def_adj, 3)},
    }

    prob_map = {
        "home": probs["home_win"],
        "draw": probs["draw"],
        "away": probs["away_win"],
        "over25": probs["over25"],
        "under25": probs["under25"],
        "over15": probs["over15"],
        "over35": probs["over35"],
        "btts_yes": probs["btts_yes"],
        "btts_no": probs["btts_no"],
        "dc_1x": probs["dc_1x"],
        "dc_x2": probs["dc_x2"],
        "dc_12": probs["dc_12"],
        "ht_home": probs["ht_home"],
        "ht_draw": probs["ht_draw"],
        "ht_away": probs["ht_away"],
    }

    markets = []
    value_bets = []

    for key, prob in prob_map.items():
        mclass = get_market_class(key)
        label = {
            "home": "MS 1", "draw": "MS X", "away": "MS 2",
            "over25": "Üst 2.5", "under25": "Alt 2.5",
            "over15": "Üst 1.5", "over35": "Üst 3.5",
            "btts_yes": "KG Var", "btts_no": "KG Yok",
            "dc_1x": "ÇŞ 1X", "dc_x2": "ÇŞ X2", "dc_12": "ÇŞ 12",
            "ht_home": "İY 1", "ht_draw": "İY X", "ht_away": "İY 2",
        }.get(key, key)

        fair_odds = round(1 / prob, 2) if prob > 0.005 else 200.0
        real_odd = odds_input.get(key, 0)
        has_real = real_odd > 1.0
        display_odd = real_odd if has_real else fair_odds

        if has_real and mclass == "tradable":
            v = value_calc(prob, real_odd)
            is_val = v >= MIN_EDGE
            if is_val:
                kd = adaptive_kelly(prob, real_odd, confidence, mclass, bankroll)
                bet = kd["bet"]
                kelly_f = kd["fraction"]
                if kd["reason"] != "ok":
                    is_val = False
                    bet = 0
                    kelly_f = 0
                flags = build_reason_flags(v, confidence, mclass)
            else:
                bet = 0
                kelly_f = 0
                flags = []
        else:
            v = -1
            is_val = False
            bet = 0
            kelly_f = 0
            flags = []

        entry = {
            "key": key,
            "label": label,
            "prob": round(prob * 100, 1),
            "odds": round(display_odd, 2),
            "model_fair_odds": fair_odds,
            "value_pct": round(v * 100, 1) if v > -1 else 0,
            "is_value": is_val,
            "market_class": mclass,
            "odds_source": "manual" if has_real else "model",
            "kelly": kelly_f,
            "bet": bet,
            "reason_flags": flags,
        }
        markets.append(entry)

        if is_val:
            value_bets.append(entry)

    for label, prob in probs.get("iy_ms", {}).items():
        markets.append({
            "key": f"iyms_{label}", "label": f"İY/MS {label}",
            "prob": round(prob * 100, 1),
            "odds": round(1 / prob, 2) if prob > 0.005 else 200.0,
            "model_fair_odds": round(1 / prob, 2) if prob > 0.005 else 200.0,
            "value_pct": 0, "is_value": False,
            "market_class": "informational", "odds_source": "model",
            "kelly": 0, "bet": 0, "reason_flags": [],
        })

    for score_str, prob in probs.get("top_scores", []):
        markets.append({
            "key": f"cs_{score_str}", "label": f"Skor {score_str}",
            "prob": round(prob * 100, 1),
            "odds": round(1 / prob, 2) if prob > 0.005 else 200.0,
            "model_fair_odds": round(1 / prob, 2) if prob > 0.005 else 200.0,
            "value_pct": 0, "is_value": False,
            "market_class": "informational", "odds_source": "model",
            "kelly": 0, "bet": 0, "reason_flags": [],
        })

    markets.sort(key=lambda x: x["value_pct"], reverse=True)
    value_bets.sort(key=lambda x: x["value_pct"], reverse=True)

    result = {
        "home_team": data.get("home_team", "Ev Sahibi"),
        "away_team": data.get("away_team", "Deplasman"),
        "league_type": league_type,
        "neutral": neutral,
        "home_strength": hs,
        "away_strength": as_,
        "expected_goals": {"home": hxg, "away": axg},
        "probabilities": {
            "home_win": probs["home_win"],
            "draw": probs["draw"],
            "away_win": probs["away_win"],
            "over25": probs["over25"],
            "btts_yes": probs["btts_yes"],
        },
        "confidence": confidence,
        "applied_factors": applied_factors,
        "markets": markets,
        "value_bets": value_bets,
        "corners_expected": probs.get("corners_expected", 0),
        "top_scores": probs.get("top_scores", []),
        "model_version": "v8-manual",
        # ─── Yeni alanlar ────────────────────────────────────────────────
        "injury_summary":      injury_summary,
        "context_effects":     context_effects,
        "estimate_comparison": estimate_comparison,
    }
    if estimate_error:
        result["estimate_error"] = estimate_error
    return result
