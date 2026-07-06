"""Canlı öneri güven kapısı"""
import json,os,logging
from config import BACKTEST_MIN_BETS, CLV_POSITIVE_RATE_MIN

logger = logging.getLogger(__name__)

TRUST_STORE=os.path.join(os.path.dirname(__file__),"trust_data.json")

MIN_BETS=10
MIN_ROI=0.0
MAX_BRIER=0.25
MAX_CAL_GAP=12.0

def load_trust_data()->dict:
    try:
        with open(TRUST_STORE,"r") as f:return json.load(f)
    except FileNotFoundError:return{}
    except Exception:
        logger.warning("trust_data load failed",exc_info=True)
        return{}

def save_trust_data(data:dict):
    with open(TRUST_STORE,"w") as f:json.dump(data,f)

def update_trust_from_backtest(league_key:str,backtest_result:dict):
    td=load_trust_data()
    if league_key not in td:td[league_key]={}
    mr=backtest_result.get("market_results",{})
    cal=backtest_result.get("calibration",[])
    avg_gap=sum(c.get("gap",0) for c in cal)/max(len(cal),1) if cal else 99
    for mkt,stats in mr.items():
        td[league_key][mkt]={
            "bets":stats.get("bets_placed",0),
            "roi":stats.get("market_roi",0),
            "brier":stats.get("brier_score",1.0),
            "hit_rate":stats.get("hit_rate",0),
            "cal_gap":round(avg_gap,1),
        }
    save_trust_data(td)

def is_trusted_market(league_key:str,market_key:str,stats:dict=None)->bool:
    """
    Backtest verisi yoksa default True (benefit of the doubt).
    False yalnızca veri VAR ve ROI/Brier/cal_gap threshold'u aşıldığında.
    BACKTEST_MIN_BETS sadece warnings'e yazılır, trusted kararını etkilemez.
    """
    if stats is None:
        td=load_trust_data()
        stats=td.get(league_key,{}).get(market_key)
    if not stats:
        return True  # veri yok → varsayılan güven
    if stats.get("bets",0)<MIN_BETS:
        return True  # yetersiz veri → karar veremeyiz, soft warning yeterli
    if stats.get("roi",0)<=MIN_ROI:return False
    if stats.get("brier",1.0)>MAX_BRIER:return False
    if stats.get("cal_gap",99)>MAX_CAL_GAP:return False
    return True

def get_trusted_markets(league_key:str)->list:
    td=load_trust_data()
    lg=td.get(league_key,{})
    return[mkt for mkt in lg if is_trusted_market(league_key,mkt,lg[mkt])]

def get_all_trust_status(clv_by_market: dict = None) -> dict:
    td = load_trust_data()
    result = {}
    for lg, mkts in td.items():
        result[lg] = {}
        for mkt, s in mkts.items():
            warnings = []
            bets_n = s.get("bets", 0)
            if bets_n < BACKTEST_MIN_BETS:
                warnings.append("insufficient_data")
            if clv_by_market:
                clv_mkt = clv_by_market.get(mkt)
                if clv_mkt is not None:
                    pr = clv_mkt.get("positive_rate")
                    if pr is not None and pr / 100.0 < CLV_POSITIVE_RATE_MIN:
                        warnings.append("clv_warning")
            result[lg][mkt] = {
                "trusted": is_trusted_market(lg, mkt, s),
                "bets_count": bets_n,
                "warnings": warnings,
                **s,
            }
    return result
