"""Takım güç modeli v8 - Glicko-2 blend + contextual features (rest, h2h, form, position)"""
import math
import logging
from datetime import datetime
from config import DECAY_HALF_LIFE, SHRINK_N, STRENGTH_CAP

logger = logging.getLogger(__name__)


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


# ─── CONTEXTUAL FEATURE FONKSİYONLARI ────────────────────────────────────────

def compute_rest_days(name: str, matches: list, match_date: str) -> dict:
    """
    Takımın son maçından match_date'e kadar geçen gün sayısı.
    matches: kronolojik sıralı (date alanı ISO8601).
    Döner: {"days": int|None, "multiplier": float, "label": str}
      rest < 3  → fatigue penalty:  atk × 0.95
      rest > 7  → freshness bonus:  atk × 1.03
      else      → nötr: 1.0
    """
    if not match_date:
        return {"days": None, "multiplier": 1.0, "label": "unknown"}

    try:
        ref = datetime.fromisoformat(match_date.replace("Z", ""))
    except ValueError:
        return {"days": None, "multiplier": 1.0, "label": "unknown"}

    last_date = None
    for m in reversed(matches):          # reversed → en son maç önce
        if m.get("hs") is None or m.get("as") is None:
            continue
        if m.get("ht") != name and m.get("at") != name:
            continue
        d_str = m.get("date", "")
        if not d_str:
            continue
        try:
            d = datetime.fromisoformat(d_str.replace("Z", ""))
            if d < ref:                  # gelecek maçı atla
                last_date = d
                break
        except ValueError:
            continue

    if last_date is None:
        return {"days": None, "multiplier": 1.0, "label": "unknown"}

    days = (ref - last_date).days

    if days < 3:
        mult = 0.95
        label = "fatigue"
    elif days > 7:
        mult = 1.03
        label = "fresh"
    else:
        mult = 1.0
        label = "normal"

    return {"days": days, "multiplier": round(mult, 3), "label": label}


def compute_form_trend(name: str, matches: list, n: int = 5) -> dict:
    """
    Son n maçtaki gol farkı (GF-GA) üzerinde lineer regresyon eğimi.
    Döner: {"slope": float, "multiplier": float, "diffs": list}
      atk × clamp(1 + slope × 0.1, 0.90, 1.10)
    """
    team_matches = []
    for m in matches:
        if m.get("hs") is None or m.get("as") is None:
            continue
        if m["ht"] == name:
            team_matches.append(m["hs"] - m["as"])
        elif m["at"] == name:
            team_matches.append(m["as"] - m["hs"])

    recent = team_matches[-n:]
    if len(recent) < 2:
        return {"slope": 0.0, "multiplier": 1.0, "diffs": recent}

    k = len(recent)
    xs = list(range(k))
    sum_x  = sum(xs)
    sum_y  = sum(recent)
    sum_xy = sum(x * y for x, y in zip(xs, recent))
    sum_x2 = sum(x * x for x in xs)

    denom = k * sum_x2 - sum_x ** 2
    slope = (k * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0

    mult = clamp(1.0 + slope * 0.1, 0.90, 1.10)

    return {"slope": round(slope, 3), "multiplier": round(mult, 3), "diffs": recent}


def compute_h2h_factor(hname: str, aname: str, matches: list, n: int = 5) -> dict:
    """
    Son n karşılaşmada ev sahibi galibiyet oranı.
    Döner: {"win_rate": float|None, "total": int, "home_wins": int, "multiplier": float}
      h2h > 0.6 → home_atk × 1.05
      h2h < 0.3 → home_atk × 0.95
      veri yoksa → nötr 1.0
    """
    h2h_matches = [
        m for m in matches
        if m.get("hs") is not None and m.get("as") is not None
        and {m.get("ht"), m.get("at")} == {hname, aname}
    ]
    recent = h2h_matches[-n:]
    total = len(recent)

    if total == 0:
        return {"win_rate": None, "total": 0, "home_wins": 0, "multiplier": 1.0}

    home_wins = sum(
        1 for m in recent
        if m["ht"] == hname and m["hs"] > m["as"]
    )
    win_rate = home_wins / total

    if win_rate > 0.6:
        mult = 1.05
    elif win_rate < 0.3:
        mult = 0.95
    else:
        mult = 1.0

    return {
        "win_rate": round(win_rate, 2),
        "total": total,
        "home_wins": home_wins,
        "multiplier": round(mult, 3),
    }


def compute_standings(matches: list) -> dict:
    """
    Geçmiş maçlardan basit puan tablosu oluşturur.
    Döner: {team: {"points": int, "played": int, "gd": int, "position": int}}
    Sıralama: puan → gol farkı → gol attı
    """
    table: dict = {}

    def _get(t: str) -> dict:
        if t not in table:
            table[t] = {"points": 0, "played": 0, "gd": 0, "gf": 0}
        return table[t]

    for m in matches:
        hs, aws = m.get("hs"), m.get("as")
        if hs is None or aws is None:
            continue
        ht, at = m["ht"], m["at"]
        h = _get(ht)
        a = _get(at)
        h["played"] += 1
        a["played"] += 1
        h["gf"] += hs
        a["gf"] += aws
        h["gd"] += (hs - aws)
        a["gd"] += (aws - hs)
        if hs > aws:
            h["points"] += 3
        elif hs == aws:
            h["points"] += 1
            a["points"] += 1
        else:
            a["points"] += 3

    sorted_teams = sorted(
        table.items(),
        key=lambda x: (x[1]["points"], x[1]["gd"], x[1]["gf"]),
        reverse=True,
    )
    for pos, (team, data) in enumerate(sorted_teams, start=1):
        data["position"] = pos

    return table


def compute_position_gap(hname: str, aname: str, standings: dict) -> dict:
    """
    Puan tablosundaki sıralama farkına göre confidence ayarlaması.
    gap = abs(home_pos - away_pos)
      gap > 10 → conf_adj = +3  (belirgin favori)
      gap <  3 → conf_adj = -2  (çok yakın takımlar)
      else     → conf_adj =  0
    Döner: {"home_pos": int|None, "away_pos": int|None, "gap": int|None, "conf_adj": int}
    """
    h_data = standings.get(hname, {})
    a_data = standings.get(aname, {})
    h_pos  = h_data.get("position")
    a_pos  = a_data.get("position")

    if h_pos is None or a_pos is None:
        return {"home_pos": h_pos, "away_pos": a_pos, "gap": None, "conf_adj": 0}

    gap = abs(h_pos - a_pos)

    if gap > 10:
        conf_adj = 3
    elif gap < 3:
        conf_adj = -2
    else:
        conf_adj = 0

    return {
        "home_pos": h_pos,
        "away_pos": a_pos,
        "gap": gap,
        "conf_adj": conf_adj,
    }


def apply_context_features(
    hxg: float, axg: float,
    home_rest: dict, away_rest: dict,
    home_trend: dict, away_trend: dict,
    h2h: dict,
) -> tuple:
    """
    rest + form + h2h çarpanlarını xG değerlerine uygular.
    Döner: (adj_hxg, adj_axg)
    position_gap confidence'ı etkiler (backend'de uygulanır).
    """
    h = hxg
    a = axg

    # rest days
    h *= home_rest["multiplier"]
    a *= away_rest["multiplier"]

    # form trend
    h *= home_trend["multiplier"]
    a *= away_trend["multiplier"]

    # h2h — sadece ev sahibi ataklarına uygulanır
    h *= h2h["multiplier"]

    return round(max(0.10, h), 2), round(max(0.10, a), 2)


# ─── TEK TAKIM TEMEL GÜÇ HESABI ──────────────────────────────────────────────

def team_strength(name: str, matches: list, avg_h: float, avg_a: float,
                  elo_ratings: dict = None) -> dict:
    """
    Zaman ağırlıklı + ev/deplasman ayrımı + shrinkage + outlier cap + Glicko-2 blend.
    Context features (rest, h2h, form, position) ayrı fonksiyonlarla uygulanır.
    """
    team_matches = []
    for m in matches:
        hs, aws = m.get("hs"), m.get("as")
        if hs is None or aws is None:
            continue
        if m["ht"] == name:
            team_matches.append(("home", hs, aws))
        elif m["at"] == name:
            team_matches.append(("away", aws, hs))

    total_n = len(team_matches)
    if total_n < 3:
        return {
            "atk": 1.0, "def": 1.0,
            "home_atk": 1.0, "home_def": 1.0,
            "away_atk": 1.0, "away_def": 1.0,
            "n": total_n, "home_n": 0, "away_n": 0, "confidence": 15,
        }

    h_gf = h_ga = h_w = a_gf = a_ga = a_w = 0.0
    for i, (_type, gf, ga) in enumerate(reversed(team_matches)):
        weight = math.exp(-math.log(2) * i / DECAY_HALF_LIFE)
        if _type == "home":
            h_gf += gf * weight; h_ga += ga * weight; h_w += weight
        else:
            a_gf += gf * weight; a_ga += ga * weight; a_w += weight

    la_h = max(avg_h, 0.5)
    la_a = max(avg_a, 0.5)
    raw_ha = (h_gf / h_w / la_h) if h_w > 0 else 1.0
    raw_hd = (h_ga / h_w / la_a) if h_w > 0 else 1.0
    raw_aa = (a_gf / a_w / la_a) if a_w > 0 else 1.0
    raw_ad = (a_ga / a_w / la_h) if a_w > 0 else 1.0

    home_n = sum(1 for t, _, _ in team_matches if t == "home")
    away_n = sum(1 for t, _, _ in team_matches if t == "away")

    def shrink(raw, n):
        alpha = min(n / SHRINK_N, 1.0)
        return alpha * raw + (1 - alpha) * 1.0

    ha = clamp(shrink(raw_ha, home_n), *STRENGTH_CAP)
    hd = clamp(shrink(raw_hd, home_n), *STRENGTH_CAP)
    aa = clamp(shrink(raw_aa, away_n), *STRENGTH_CAP)
    ad = clamp(shrink(raw_ad, away_n), *STRENGTH_CAP)

    # ─── Glicko-2 blend ───────────────────────────────────────────────────────
    elo_data = None
    if elo_ratings and name in elo_ratings:
        from elo_rating import elo_normalized
        er = elo_ratings[name]
        if er.get("n", 0) >= 5 and er.get("rd", 350) < 250:
            en_atk = elo_normalized(er["rating"])
            en_def = max(0.5, min(1.5, 2.0 - en_atk))
            ha = clamp(0.7 * ha + 0.3 * en_atk, *STRENGTH_CAP)
            hd = clamp(0.7 * hd + 0.3 * en_def, *STRENGTH_CAP)
            aa = clamp(0.7 * aa + 0.3 * en_atk, *STRENGTH_CAP)
            ad = clamp(0.7 * ad + 0.3 * en_def, *STRENGTH_CAP)
            elo_data = {
                "rating": er["rating"], "rd": er["rd"],
                "trend_last5": er.get("trend_last5", 0.0),
            }
    # ─────────────────────────────────────────────────────────────────────────

    atk = round((ha + aa) / 2, 2)
    dfn = round((hd + ad) / 2, 2)
    balance = min(home_n, away_n) / (max(home_n, away_n) + 0.001)
    conf = min(100, int(min(total_n / 20, 1.0) * 70 + balance * 30))

    result = {
        "atk": atk, "def": dfn,
        "home_atk": round(ha, 2), "home_def": round(hd, 2),
        "away_atk": round(aa, 2), "away_def": round(ad, 2),
        "n": total_n, "home_n": home_n, "away_n": away_n,
        "confidence": conf,
    }
    if elo_data:
        result["elo"] = elo_data
    return result
