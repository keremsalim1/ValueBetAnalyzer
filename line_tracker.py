"""Closing line tracker v2
Real closing line via The Odds API historical endpoint (paid plan).
Fallback: rolling average of last 3 pseudo-closing snapshots.
CLV formula: (opening_odds / closing_odds - 1) * 100
"""
import json, os, logging, httpx
from datetime import datetime
from typing import Optional
from config import ODDS_KEY, ODDS_BASE, ODDSPAPI_KEY

logger = logging.getLogger(__name__)

STORE_PATH = os.path.join(os.path.dirname(__file__), "line_snapshots.json")
MAX_SNAPSHOTS = 3  # pseudo-closing için tutulacak snapshot sayısı


def _load() -> dict:
    try:
        with open(STORE_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        logger.warning("line_snapshots load failed", exc_info=True)
        return {}


def _save(data: dict):
    with open(STORE_PATH, "w") as f:
        json.dump(data, f)


# ─── SNAPSHOT YAZMA ────────────────────────────────────────────────────────────

async def save_opening_snapshot(match_key: str, odds_dict: dict, timestamp: str = None,
                               event_id: str = None, sport_key: str = None,
                               commence_time: str = None,
                               home_team: str = None, away_team: str = None):
    """İlk oran snapshot'u. Zaten varsa overwrite etmez.
    ODDSPAPI_KEY varsa Pinnacle opening da çekilir.
    """
    data = _load()
    if match_key not in data:
        snap: dict = {
            "opening": {"odds": odds_dict, "ts": timestamp or datetime.utcnow().isoformat() + "Z"},
            "snapshots": [],
            "latest": None,
            "closing": None,
        }
        if event_id:
            snap["event_id"] = event_id
        if sport_key:
            snap["sport_key"] = sport_key
        if commence_time:
            snap["commence_time"] = commence_time

        # OddsPapi: Pinnacle opening line
        if ODDSPAPI_KEY and home_team and away_team and commence_time:
            try:
                from pinnacle_tracker import get_fixture_id, get_pinnacle_opening
                fx_id = await get_fixture_id(home_team, away_team, commence_time)
                if fx_id:
                    snap["oddspapi_fixture_id"] = fx_id
                    opening = await get_pinnacle_opening(fx_id)
                    if opening:
                        snap["pinnacle_opening"] = opening
                        logger.info(
                            "pinnacle_opening saved match=%s fixture=%s", match_key, fx_id
                        )
            except Exception as e:
                logger.debug("pinnacle opening fetch error match=%s err=%s", match_key, e)

        data[match_key] = snap
        _save(data)


def save_pre_match_snapshot(match_key: str, odds_dict: dict, timestamp: str = None):
    """Background refresh her çağrıldığında snapshot listesini günceller (son MAX_SNAPSHOTS korunur)."""
    data = _load()
    ts = timestamp or datetime.utcnow().isoformat() + "Z"
    if match_key not in data:
        data[match_key] = {
            "opening": {"odds": odds_dict, "ts": ts},
            "snapshots": [],
            "latest": None,
            "closing": None,
        }
    snap = data[match_key]
    snap.setdefault("snapshots", [])
    snap.setdefault("closing", None)

    snap["snapshots"].append({"odds": odds_dict, "ts": ts})
    if len(snap["snapshots"]) > MAX_SNAPSHOTS:
        snap["snapshots"] = snap["snapshots"][-MAX_SNAPSHOTS:]

    snap["latest"] = {"odds": odds_dict, "ts": ts}  # geriye dönük uyumluluk
    _save(data)


def save_closing_snapshot(match_key: str, odds_dict: dict, source: str = "historical_api"):
    """Gerçek kapanış oranı (The Odds API historical) kaydeder. Üzerine yazmaz."""
    data = _load()
    if match_key not in data:
        return
    if data[match_key].get("closing"):
        return  # zaten gerçek closing var
    data[match_key]["closing"] = {
        "odds": odds_dict,
        "ts": datetime.utcnow().isoformat() + "Z",
        "source": source,
    }
    _save(data)


# ─── PSEUDO CLOSING ────────────────────────────────────────────────────────────

def _pseudo_closing(snap: dict) -> Optional[dict]:
    """Son MAX_SNAPSHOTS snapshot'ın market bazlı ortalaması. Fallback: latest."""
    snapshots = snap.get("snapshots", [])
    if not snapshots:
        latest = snap.get("latest")
        return latest.get("odds") if latest else None

    to_avg = snapshots[-MAX_SNAPSHOTS:]
    if len(to_avg) == 1:
        return to_avg[0]["odds"]

    all_mkts: set = set()
    for s in to_avg:
        all_mkts.update(s["odds"].keys())

    result = {}
    for mkt in all_mkts:
        vals = [s["odds"][mkt] for s in to_avg
                if mkt in s["odds"] and s["odds"][mkt] > 1.0]
        if vals:
            result[mkt] = round(sum(vals) / len(vals), 3)
    return result if result else None


def _get_closing_odds(snap: dict) -> Optional[dict]:
    """Önce gerçek closing, yoksa pseudo closing döndürür."""
    closing = snap.get("closing")
    if closing and closing.get("odds"):
        return closing["odds"]
    return _pseudo_closing(snap)


# ─── GERÇEK KAPANIŞ ORANI (The Odds API historical) ───────────────────────────

async def fetch_real_closing_odds(event_id: str, sport_key: str,
                                   commence_time: str = None) -> Optional[dict]:
    """
    The Odds API historical endpoint ile gerçek kapanış oranını çeker.
    Endpoint: GET /v4/historical/sports/{sport_key}/odds
    Plan desteklemiyorsa (402/422) None döner → pseudo-closing fallback devreye girer.
    """
    if not ODDS_KEY or not event_id or not sport_key:
        return None

    date_param = commence_time or datetime.utcnow().isoformat() + "Z"

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{ODDS_BASE}/historical/sports/{sport_key}/odds",
                params={
                    "apiKey": ODDS_KEY,
                    "regions": "eu",
                    "markets": "h2h,totals",
                    "oddsFormat": "decimal",
                    "date": date_param,
                    "eventIds": event_id,
                },
            )

        if r.status_code in (402, 422):
            logger.debug("historical_odds plan_not_supported sport=%s event=%s", sport_key, event_id)
            return None
        if r.status_code != 200:
            logger.debug("historical_odds failed status=%d sport=%s event=%s", r.status_code, sport_key, event_id)
            return None

        payload = r.json()
        events = payload.get("data", []) if isinstance(payload, dict) else payload
        for ev in (events or []):
            if ev.get("id") != event_id:
                continue
            # En iyi oranları bookmaker'lardan topla
            best: dict = {}
            for bk in ev.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    oc = {o["name"]: o["price"] for o in mk.get("outcomes", [])}
                    if mk["key"] == "h2h":
                        for label, key in [(ev.get("home_team", ""), "home"),
                                           ("Draw", "draw"),
                                           (ev.get("away_team", ""), "away")]:
                            v = oc.get(label, 0)
                            if v > 1.0:
                                best[key] = max(best.get(key, 0), v)
                    elif mk["key"] == "totals":
                        for o in mk.get("outcomes", []):
                            if o.get("point") == 2.5:
                                key = "over25" if o["name"] == "Over" else "under25"
                                best[key] = max(best.get(key, 0), o["price"])
            if best:
                logger.info("historical_odds success event=%s markets=%s", event_id, list(best.keys()))
                return best

    except Exception as e:
        logger.debug("historical_odds exception event=%s err=%s", event_id, e)

    return None


async def try_update_closing(match_key: str) -> bool:
    """
    3 katmanlı closing önceliği:
    1. OddsPapi Pinnacle historical (clv_reliability="high")
    2. The Odds API historical (clv_reliability="medium")
    3. Pseudo / fallback — hiçbir şey kaydedilmez, get_clv_report bunu otomatik kullanır.
    """
    data = _load()
    snap = data.get(match_key)
    if not snap or snap.get("closing"):
        return False  # zaten var

    # ── Tier 1: OddsPapi Pinnacle historical ───────────────────────────────────
    fx_id = snap.get("oddspapi_fixture_id", "")
    if fx_id and ODDSPAPI_KEY:
        try:
            from pinnacle_tracker import get_pinnacle_closing
            closing = await get_pinnacle_closing(fx_id)
            if closing:
                save_closing_snapshot(match_key, closing, source="pinnacle_historical")
                # reliability metadata
                data = _load()
                if match_key in data and data[match_key].get("closing"):
                    data[match_key]["closing"]["clv_reliability"] = "high"
                    _save(data)
                logger.info("closing_tier1 pinnacle match=%s fixture=%s", match_key, fx_id)
                return True
        except Exception as e:
            logger.debug("pinnacle closing error match=%s err=%s", match_key, e)

    # ── Tier 2: The Odds API historical ────────────────────────────────────────
    event_id = snap.get("event_id", "")
    sport_key = snap.get("sport_key", "")
    commence_time = snap.get("commence_time", "")

    if event_id and sport_key:
        odds = await fetch_real_closing_odds(event_id, sport_key, commence_time)
        if odds:
            save_closing_snapshot(match_key, odds, source="historical_api")
            data = _load()
            if match_key in data and data[match_key].get("closing"):
                data[match_key]["closing"]["clv_reliability"] = "medium"
                _save(data)
            logger.info("closing_tier2 historical_api match=%s event=%s", match_key, event_id)
            return True

    return False


# ─── CLV HESABI ────────────────────────────────────────────────────────────────

def compute_clv(opening_odds: float, closing_odds: float, market_key: str = "") -> dict:
    """
    CLV = (opening_odds / closing_odds - 1) × 100
    Pozitif → açılış oranı kapanışı geçti (değerli bet).
    Negatif → kapanış daha iyi (değer kaçırıldı).
    """
    if opening_odds <= 1 or closing_odds <= 1:
        return {"clv_pct": 0.0, "clv_direction": "no_data"}

    clv_pct = round((opening_odds / closing_odds - 1) * 100, 2)

    if clv_pct > 0.5:
        direction = "positive"
    elif clv_pct < -0.5:
        direction = "negative"
    else:
        direction = "neutral"

    return {"clv_pct": clv_pct, "clv_direction": direction}


# ─── CLV RAPORU ────────────────────────────────────────────────────────────────

def get_clv_report() -> list:
    """Her maç/market için CLV kaydı döndürür. Mevcut callers için liste formatı korunur."""
    data = _load()
    report = []
    for mk, snap in data.items():
        opening = snap.get("opening", {})
        if not opening:
            continue
        o_odds = opening.get("odds", {})
        c_odds = _get_closing_odds(snap)
        if not c_odds:
            continue

        # Determine closing source + reliability
        real_closing = snap.get("closing")
        if real_closing:
            cs_raw = real_closing.get("source", "historical_api")
            if cs_raw == "pinnacle_historical":
                closing_source = "pinnacle_historical"
                clv_reliability = "high"
            else:
                closing_source = "historical_api"
                clv_reliability = real_closing.get("clv_reliability", "medium")
        else:
            closing_source = "pseudo"
            clv_reliability = "low"

        for market in set(list(o_odds.keys()) + list(c_odds.keys())):
            oo = o_odds.get(market, 0)
            co = c_odds.get(market, 0)
            if oo <= 1 or co <= 1:
                continue
            clv = compute_clv(oo, co, market)
            report.append({
                "match": mk,
                "market": market,
                "opening_odds": oo,
                "closing_odds": co,
                "closing_source": closing_source,
                "clv_reliability": clv_reliability,
                "opening_ts": opening.get("ts", ""),
                "closing_ts": real_closing.get("ts", "") if real_closing else "",
                "clv_pct": clv["clv_pct"],
                "clv_direction": clv["clv_direction"],
                # backward compat
                "clv_diff": clv["clv_pct"],
            })

    report.sort(key=lambda x: abs(x["clv_pct"]), reverse=True)
    return report


def get_clv_stats(report: list) -> dict:
    """
    Report listesinden özet istatistikler çıkarır:
      avg_clv_percent, positive_rate, by_market breakdown.
    """
    if not report:
        return {
            "avg_clv_percent": None,
            "positive_rate": None,
            "by_market": {},
            "total_entries": 0,
        }

    total = len(report)
    clv_sum = sum(r["clv_pct"] for r in report)
    positive = sum(1 for r in report if r["clv_direction"] == "positive")

    by_market: dict = {}
    for r in report:
        mkt = r["market"]
        if mkt not in by_market:
            by_market[mkt] = {"count": 0, "clv_sum": 0.0, "positive": 0}
        by_market[mkt]["count"] += 1
        by_market[mkt]["clv_sum"] += r["clv_pct"]
        if r["clv_direction"] == "positive":
            by_market[mkt]["positive"] += 1

    by_market_summary = {}
    for mkt, s in by_market.items():
        n = s["count"]
        by_market_summary[mkt] = {
            "n": n,
            "avg_clv_pct": round(s["clv_sum"] / n, 2),
            "positive_rate": round(s["positive"] / n * 100, 1),
        }

    # Reliability breakdown
    reliability_breakdown: dict = {"high": 0, "medium": 0, "low": 0}
    rel_clv: dict = {"high": [], "medium": [], "low": []}
    for r in report:
        rel = r.get("clv_reliability", "low")
        reliability_breakdown[rel] = reliability_breakdown.get(rel, 0) + 1
        rel_clv.setdefault(rel, []).append(r["clv_pct"])

    avg_clv_by_reliability: dict = {}
    for rel, vals in rel_clv.items():
        avg_clv_by_reliability[rel] = round(sum(vals) / len(vals), 2) if vals else None

    from pinnacle_tracker import get_requests_today
    try:
        from config import ODDSPAPI_DAILY_LIMIT
        oddspapi_requests_today = get_requests_today()
        oddspapi_daily_limit = ODDSPAPI_DAILY_LIMIT
    except Exception:
        oddspapi_requests_today = 0
        oddspapi_daily_limit = 25

    return {
        "avg_clv_percent": round(clv_sum / total, 2),
        "positive_rate": round(positive / total * 100, 1),
        "by_market": by_market_summary,
        "total_entries": total,
        "reliability_breakdown": reliability_breakdown,
        "avg_clv_by_reliability": avg_clv_by_reliability,
        "oddspapi_requests_today": oddspapi_requests_today,
        "oddspapi_daily_limit": oddspapi_daily_limit,
    }


def clear_snapshots():
    _save({})
