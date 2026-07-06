"""Market oluşturucu v8"""
import json
import os
import logging
from datetime import date
from config import (get_market_class, MIN_EDGE, MIN_CONFIDENCE,
                    MIN_ODDS, MAX_ODDS, REQUIRE_STEAM_ALIGNMENT, MAX_BETS_PER_DAY)
from risk_manager import value_calc, adaptive_kelly, build_reason_flags
from sanity_checks import validate_prediction_context

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_DAILY_BETS_PATH = os.path.join(_DATA_DIR, "daily_bets.json")
_FILTER_STATS_PATH = os.path.join(_DATA_DIR, "filter_stats.json")


def _ensure_data_dir():
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except Exception as e:
        logger.error("data dir oluşturulamadı: %s", e)


def _load_daily_bets() -> dict:
    _ensure_data_dir()
    today = date.today().isoformat()
    try:
        with open(_DAILY_BETS_PATH, "r") as f:
            data = json.load(f)
        if data.get("date") != today:
            return {"date": today, "count": 0}
        return data
    except Exception:
        return {"date": today, "count": 0}


def _save_daily_bets(data: dict):
    _ensure_data_dir()
    try:
        with open(_DAILY_BETS_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error("daily_bets kayıt hatası: %s", e)


def load_filter_stats() -> dict:
    """Günlük filtre istatistiklerini oku (daily-review için dışa açık)."""
    _ensure_data_dir()
    today = date.today().isoformat()
    try:
        with open(_FILTER_STATS_PATH, "r") as f:
            data = json.load(f)
        if data.get("date") != today:
            return {"date": today, "odds_band_rejected": 0, "steam_rejected": 0}
        return data
    except Exception:
        return {"date": today, "odds_band_rejected": 0, "steam_rejected": 0}


def _save_filter_stats(data: dict):
    _ensure_data_dir()
    try:
        with open(_FILTER_STATS_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error("filter_stats kayıt hatası: %s", e)


def get_daily_review_stats() -> dict:
    """filter_stats + daily_bets birleştirerek daily-review için hazır dict döner."""
    fs = load_filter_stats()
    db = _load_daily_bets()
    return {
        "odds_band_rejected": fs.get("odds_band_rejected", 0),
        "steam_rejected": fs.get("steam_rejected", 0),
        "daily_limit_hit": db.get("count", 0) >= MAX_BETS_PER_DAY,
        "bets_today": db.get("count", 0),
        "max_bets_per_day": MAX_BETS_PER_DAY,
    }


def build_markets(probs: dict, best_odds: dict, bankroll: float, match_confidence: int,
                  hxg: float = 0, axg: float = 0, best_odds_detail: dict = None,
                  steam_move: bool = False, odds_movement: dict = None) -> tuple:
    """
    Market listesi + metadata döner.
    Returns: (markets_list, {"daily_limit_reached": bool})
    """
    defs=[
        ("home","MS 1",probs["home_win"]),("draw","MS X",probs["draw"]),("away","MS 2",probs["away_win"]),
        ("over25","Üst 2.5",probs["over25"]),("under25","Alt 2.5",probs["under25"]),
        ("over15","Üst 1.5",probs["over15"]),("over35","Üst 3.5",probs["over35"]),
        ("btts_yes","KG Var",probs["btts_yes"]),("btts_no","KG Yok",probs["btts_no"]),
        ("dc_1x","ÇŞ 1X",probs["dc_1x"]),("dc_x2","ÇŞ X2",probs["dc_x2"]),("dc_12","ÇŞ 12",probs["dc_12"]),
        ("ht_home","İY 1",probs["ht_home"]),("ht_draw","İY X",probs["ht_draw"]),("ht_away","İY 2",probs["ht_away"]),
        ("corner_o85",f"Korner Ü8.5 ({probs['corners_expected']})",probs["corner_o85"]),
        ("corner_u85","Korner A8.5",probs["corner_u85"]),
        ("corner_o95","Korner Ü9.5",probs["corner_o95"]),("corner_u95","Korner A9.5",probs["corner_u95"]),
        ("corner_o105","Korner Ü10.5",probs["corner_o105"]),("corner_u105","Korner A10.5",probs["corner_u105"]),
        ("corner_o115","Korner Ü11.5",probs["corner_o115"]),("corner_u115","Korner A11.5",probs["corner_u115"]),
    ]
    for lb,prob in probs.get("iy_ms",{}).items():defs.append((f"iyms_{lb}",f"İY/MS {lb}",prob))
    for score,prob in probs.get("top_scores",[]):defs.append((f"cs_{score}",f"Skor {score}",prob))

    daily_data = _load_daily_bets()
    filter_stats = load_filter_stats()
    daily_limit_reached = False
    filter_stats_dirty = False
    daily_bets_dirty = False

    markets=[]
    value_count=0
    reject_count=0
    for key,label,prob in defs:
        mclass=get_market_class(key)
        if mclass=="disabled":continue

        real_odd=best_odds.get(key,0)
        has_real=real_odd>1.0
        model_fair_odd=round(1/prob,2) if prob>0.005 else 200.0
        display_odd=real_odd if has_real else model_fair_odd

        value_eligible=has_real and mclass=="tradable"

        if value_eligible and match_confidence>=MIN_CONFIDENCE:
            v=value_calc(prob,real_odd)
            is_val=v>=MIN_EDGE
            if is_val:
                sc=validate_prediction_context(hxg,axg,match_confidence,v,key,real_odd)
                if sc["reject"]:
                    is_val=False;bet=0;kfrac=0
                    reject_count+=1
                    flags=build_reason_flags(v,match_confidence,mclass)+sc["flags"]
                else:
                    kd=adaptive_kelly(prob,real_odd,match_confidence,mclass,bankroll)
                    bet=kd["bet"];kfrac=kd["fraction"]
                    if kd["reason"]!="ok":is_val=False;bet=0;kfrac=0
                    flags=build_reason_flags(v,match_confidence,mclass)+sc["flags"]

                # ── Filtre 1: Odds band ──────────────────────────────────────
                if is_val and not (MIN_ODDS <= real_odd <= MAX_ODDS):
                    is_val = False
                    bet = 0; kfrac = 0
                    filter_stats["odds_band_rejected"] = filter_stats.get("odds_band_rejected", 0) + 1
                    filter_stats_dirty = True
                    logger.debug("odds_band_rejected market=%s odds=%.2f", key, real_odd)

                # ── Filtre 2: Steam ──────────────────────────────────────────
                if is_val and REQUIRE_STEAM_ALIGNMENT and steam_move:
                    mv = (odds_movement or {}).get(key, {})
                    # Oranın yükselişi = o tarafa karşı steam → model yönüne ters
                    if mv.get("direction") == "up":
                        is_val = False
                        bet = 0; kfrac = 0
                        filter_stats["steam_rejected"] = filter_stats.get("steam_rejected", 0) + 1
                        filter_stats_dirty = True
                        logger.debug("steam_rejected market=%s direction=up", key)

                # ── Filtre 3: Günlük limit ───────────────────────────────────
                if is_val:
                    if daily_data["count"] >= MAX_BETS_PER_DAY:
                        daily_limit_reached = True
                        is_val = False
                        bet = 0; kfrac = 0
                        logger.debug("daily_limit_reached market=%s count=%d", key, daily_data["count"])
                    else:
                        daily_data["count"] += 1
                        daily_bets_dirty = True
                        value_count += 1
            else:
                bet=0;kfrac=0;flags=[]
        else:
            v=-1;is_val=False;bet=0;kfrac=0;flags=[]

        detail = (best_odds_detail or {}).get(key, {})
        markets.append({
            "key":key,"label":label,"prob":round(prob*100,1),
            "odds":round(display_odd,2),
            "model_fair_odds":model_fair_odd,
            "implied":round(100/display_odd,1) if display_odd>0 else 0,
            "value_pct":round(v*100,1) if v>-1 else 0,
            "is_value":is_val,
            "value_eligible":value_eligible,
            "market_class":mclass,
            "kelly":kfrac,"bet":bet,
            "odds_source":"real" if has_real else "model",
            "best_odds_source":detail.get("bookmaker") if has_real else None,
            "all_odds":detail.get("all_odds",[]) if has_real else [],
            "reason_flags":flags,
        })

    if filter_stats_dirty:
        _save_filter_stats(filter_stats)
    if daily_bets_dirty:
        _save_daily_bets(daily_data)

    logger.info(
        "build_markets analyzed=%d value=%d rejected=%d confidence=%d",
        len(markets), value_count, reject_count, match_confidence,
    )
    return markets, {"daily_limit_reached": daily_limit_reached}
