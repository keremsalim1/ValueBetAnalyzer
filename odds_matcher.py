"""Odds eşleştirme v8.3 - multi-bookmaker, best odds detail, margin comparison, odds movement"""
import json, os, logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

MIN_MATCH_CONFIDENCE = 60
MAX_BOOKMAKER_MARGIN = 0.08

_SNAP_PATH = os.path.join(os.path.dirname(__file__), "line_snapshots.json")

def _load_snapshots() -> dict:
    try:
        with open(_SNAP_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        logger.warning("line_snapshots load failed", exc_info=True)
        return {}


def normalize_name(s: str) -> str:
    for r in ["fc ", "cf ", "ac ", "sc ", " fc", " cf", " ac", " sc", " de", " cd"]:
        s = s.lower().replace(r, " ")
    return s.replace(".", " ").replace("-", " ").replace("  ", " ").strip()


def name_match(a: str, b: str) -> float:
    if a == b: return 1.0
    wa = {w for w in a.split() if len(w) >= 3}
    wb = {w for w in b.split() if len(w) >= 3}
    if not wa or not wb: return 0.0
    intersection = wa & wb
    union = wa | wb
    jaccard = len(intersection) / len(union)
    sub_bonus = 0.2 if (a in b or b in a) else 0.0
    return min(1.0, jaccard + sub_bonus)


def find_odds(odds_data: list, hname: str, aname: str, match_date: str = None) -> Optional[dict]:
    hn = normalize_name(hname)
    an = normalize_name(aname)

    best_match = None
    best_score = 0

    for ev in odds_data:
        eh = normalize_name(ev.get("home_team", ""))
        ea = normalize_name(ev.get("away_team", ""))

        h_score = name_match(hn, eh)
        a_score = name_match(an, ea)
        combined = (h_score + a_score) / 2

        if match_date and ev.get("commence_time"):
            try:
                md = datetime.fromisoformat(match_date.replace("Z", ""))
                ed = datetime.fromisoformat(ev["commence_time"].replace("Z", ""))
                diff_hours = abs((md - ed).total_seconds()) / 3600
                if diff_hours < 3: combined += 0.2
                elif diff_hours < 24: combined += 0.1
            except ValueError:
                pass  # bozuk tarih formatı → sadece isim skoru kullanılır

        if combined > best_score and combined >= 0.5:
            best_score = combined
            best_match = ev

    if not best_match:
        logger.debug("odds_match no_match home=%s away=%s", hname, aname)
        return None

    match_conf = min(100, round(best_score * 100))
    if match_conf < MIN_MATCH_CONFIDENCE:
        logger.debug("odds_match low_confidence home=%s away=%s conf=%d", hname, aname, match_conf)
        return None

    odds_timestamp = best_match.get("commence_time", "")

    res = {
        "bookmakers": [], "match_confidence": match_conf, "odds_timestamp": odds_timestamp,
        "event_id": best_match.get("id", ""), "sport_key": best_match.get("sport_key", ""),
        "commence_time": best_match.get("commence_time", ""),
    }

    for bk in best_match.get("bookmakers", []):
        bo = {"name": bk["title"], "markets": {}, "last_update": "", "margin": None, "totals_margin": None}

        for mk in bk.get("markets", []):
            oc = {o["name"]: o["price"] for o in mk.get("outcomes", [])}
            lu = mk.get("last_update", "")
            if lu: bo["last_update"] = lu

            if mk["key"] == "h2h":
                h = oc.get(best_match["home_team"], 0)
                d = oc.get("Draw", 0)
                a = oc.get(best_match["away_team"], 0)
                if h > 1 and d > 1 and a > 1:
                    margin = (1 / h + 1 / d + 1 / a) - 1
                    bo["margin"] = round(margin, 4)
                    # Store regardless of margin — extract_best_odds applies the filter
                    bo["markets"]["home"] = h
                    bo["markets"]["draw"] = d
                    bo["markets"]["away"] = a

            elif mk["key"] == "totals":
                point = None
                for o in mk.get("outcomes", []):
                    if "point" in o: point = o["point"]
                if point is not None and point != 2.5:
                    continue
                over = oc.get("Over", 0)
                under = oc.get("Under", 0)
                if over > 1 and under > 1:
                    bo["totals_margin"] = round((1 / over + 1 / under) - 1, 4)
                    bo["markets"]["over25"] = over
                    bo["markets"]["under25"] = under

            elif mk["key"] == "btts":
                # Both Teams To Score: Yes / No
                for o in mk.get("outcomes", []):
                    name = o.get("name", "").strip().lower()
                    price = o.get("price", 0)
                    if price > 1.0:
                        if name == "yes":
                            bo["markets"]["btts_yes"] = price
                        elif name == "no":
                            bo["markets"]["btts_no"] = price

            elif mk["key"] == "double_chance":
                # Double Chance: 1X / 12 / X2
                for o in mk.get("outcomes", []):
                    name = o.get("name", "").strip().lower().replace(" ", "")
                    price = o.get("price", 0)
                    if price > 1.0:
                        if name in ("1x", "home/draw", "homedraw"):
                            bo["markets"]["dc_1x"] = price
                        elif name in ("x2", "draw/away", "drawaway"):
                            bo["markets"]["dc_x2"] = price
                        elif name in ("12", "home/away", "homeaway"):
                            bo["markets"]["dc_12"] = price

        if bo["markets"]:
            res["bookmakers"].append(bo)

    if not res["bookmakers"]:
        logger.debug("odds_match no_bookmakers home=%s away=%s conf=%d", hname, aname, match_conf)
        return None

    logger.debug("odds_match matched home=%s away=%s conf=%d bookmakers=%d",
                 hname, aname, match_conf, len(res["bookmakers"]))
    return res


def extract_best_odds(bookmakers: list) -> dict:
    """Backward compat: {market: best_price}. H2H markets filtered by margin."""
    H2H = {"home", "draw", "away"}
    all_mk: set = set()
    for bk in bookmakers:
        all_mk.update(bk["markets"].keys())

    best = {}
    for mk in all_mk:
        vals = []
        for bk in bookmakers:
            p = bk["markets"].get(mk, 0)
            if p <= 1.0:
                continue
            margin = bk.get("margin")
            if mk in H2H and margin is not None and margin > MAX_BOOKMAKER_MARGIN:
                continue
            vals.append(p)
        if vals:
            best[mk] = max(vals)
    return best


def get_best_odds_detail(bookmakers: list) -> dict:
    """
    Per-market rich structure:
      {market: {"best_odds": 2.15, "bookmaker": "Pinnacle",
                "all_odds": [{"bk": "bet365", "odds": 2.05}, ...]}}
    Best is selected from low-margin bookmakers (h2h only); totals always eligible.
    """
    H2H = {"home", "draw", "away"}
    all_mk: set = set()
    for bk in bookmakers:
        all_mk.update(bk["markets"].keys())

    result = {}
    for mk in all_mk:
        entries = []
        for bk in bookmakers:
            p = bk["markets"].get(mk, 0)
            if p <= 1.0:
                continue
            margin = bk.get("margin")
            within_margin = (mk not in H2H) or (margin is None) or (margin <= MAX_BOOKMAKER_MARGIN)
            entries.append({
                "bk": bk["name"],
                "odds": p,
                "margin": margin,
                "eligible": within_margin,
            })

        if not entries:
            continue

        eligible = [e for e in entries if e["eligible"]]
        pool = eligible if eligible else entries
        best_entry = max(pool, key=lambda e: e["odds"])

        result[mk] = {
            "best_odds": best_entry["odds"],
            "bookmaker": best_entry["bk"],
            "all_odds": [{"bk": e["bk"], "odds": e["odds"]} for e in
                         sorted(entries, key=lambda e: e["odds"], reverse=True)],
        }
    return result


def get_margin_comparison(bookmakers: list) -> list:
    """
    Per-bookmaker margin list, sorted ascending (lowest first).
    Lowest margin bookmaker is flagged with lowest_margin=True.
    Uses h2h margin if available, else totals_margin.
    """
    margins = []
    for bk in bookmakers:
        m = bk.get("margin") if bk.get("margin") is not None else bk.get("totals_margin")
        if m is None:
            continue
        margins.append({
            "bookmaker": bk["name"],
            "margin": m,
            "margin_pct": round(m * 100, 2),
            "market_type": "h2h" if bk.get("margin") is not None else "totals",
            "lowest_margin": False,
        })

    if not margins:
        return []

    margins.sort(key=lambda x: x["margin"])
    margins[0]["lowest_margin"] = True
    return margins


def get_odds_movement(match_key: str, bookmakers: list) -> dict:
    """
    Compare each bookmaker's current prices against the stored opening snapshot.
    Returns per-market direction + steam_move flag.
    steam_move: 3+ bookmakers moved in the same direction on at least one market.
    Returns: {"movements": {market: {...}}, "steam_move": bool, "steam_markets": [...]}
    """
    try:
        data = _load_snapshots()
        snap = data.get(match_key)
        if not snap:
            return {"movements": {}, "steam_move": False, "steam_markets": []}

        opening = snap.get("opening", {}).get("odds", {})
        if not opening:
            return {"movements": {}, "steam_move": False, "steam_markets": []}

        all_mk: set = set()
        for bk in bookmakers:
            all_mk.update(bk["markets"].keys())

        movements = {}
        steam_markets = []

        for mk in all_mk:
            open_price = opening.get(mk, 0)
            if open_price <= 1.0:
                continue

            bk_moves = []
            for bk in bookmakers:
                curr = bk["markets"].get(mk, 0)
                if curr <= 1.0:
                    continue
                delta = round(curr - open_price, 3)
                direction = "up" if delta > 0.01 else ("down" if delta < -0.01 else "flat")
                bk_moves.append({
                    "bk": bk["name"],
                    "opening": open_price,
                    "current": curr,
                    "delta": delta,
                    "direction": direction,
                })

            if not bk_moves:
                continue

            up_count = sum(1 for b in bk_moves if b["direction"] == "up")
            down_count = sum(1 for b in bk_moves if b["direction"] == "down")

            steam = None
            if up_count >= 3:
                steam = "up"
                steam_markets.append(mk)
            elif down_count >= 3:
                steam = "down"
                steam_markets.append(mk)

            if up_count > down_count:
                overall = "up"
            elif down_count > up_count:
                overall = "down"
            else:
                overall = "flat"

            movements[mk] = {
                "direction": overall,
                "steam": steam,
                "bk_count": len(bk_moves),
                "up": up_count,
                "down": down_count,
                "details": bk_moves,
            }

        return {
            "movements": movements,
            "steam_move": bool(steam_markets),
            "steam_markets": steam_markets,
        }

    except Exception as e:
        logger.debug("odds_movement error match=%s err=%s", match_key, e)
        return {"movements": {}, "steam_move": False, "steam_markets": []}
