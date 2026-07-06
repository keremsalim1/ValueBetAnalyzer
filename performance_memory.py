"""Geçmiş performans hafızası - backtest sonuçlarıyla beslenir"""
import json,os,logging
import config

logger = logging.getLogger(__name__)

PERF_STORE=os.path.join(os.path.dirname(__file__),"performance_data.json")

def _load()->dict:
    try:
        with open(PERF_STORE,"r") as f:return json.load(f)
    except FileNotFoundError:return{}
    except Exception:
        logger.warning("performance_data load failed",exc_info=True)
        return{}

def _save(data:dict):
    with open(PERF_STORE,"w") as f:json.dump(data,f)

def update_from_backtest(league_key:str,backtest_result:dict):
    data=_load()
    if league_key not in data:data[league_key]={}
    mr=backtest_result.get("market_results",{})
    cal=backtest_result.get("calibration",[])
    avg_cal_gap=sum(c.get("gap",0) for c in cal)/max(len(cal),1) if cal else 99
    overall_brier=backtest_result.get("avg_brier_score",0.30)
    overall_roi=backtest_result.get("roi",0)

    for mkt,stats in mr.items():
        data[league_key][mkt]={
            "bets":stats.get("bets_placed",0),
            "roi":stats.get("market_roi",0),
            "brier":stats.get("brier_score",1.0),
            "hit_rate":stats.get("hit_rate",0),
            "avg_pred":stats.get("avg_predicted_prob",0),
            "cal_gap":round(avg_cal_gap,1),
            "overall_brier":overall_brier,
            "overall_roi":overall_roi,
        }
    _save(data)

def get_market_performance_score(market_key:str,league_key:str=None)->int:
    if market_key in config.DISABLED_MARKETS:return -15
    if market_key not in config.TRADABLE_MARKETS:return -5

    data=_load()
    if not league_key or league_key not in data:return 0
    mkt_data=data[league_key].get(market_key)
    if not mkt_data:return 0

    score=0
    roi=mkt_data.get("roi",0)
    bets=mkt_data.get("bets",0)
    brier=mkt_data.get("brier",0.30)

    if bets<5:return 0
    if roi>5:score+=10
    elif roi>0:score+=5
    elif roi>-5:score-=3
    else:score-=10

    if brier<0.20:score+=5
    elif brier<0.23:score+=2
    elif brier>0.27:score-=5

    return max(-15,min(15,score))

def get_calibration_penalty(market_key:str,league_key:str=None)->int:
    if market_key in config.DISABLED_MARKETS:return -10

    data=_load()
    if not league_key or league_key not in data:return 0
    mkt_data=data[league_key].get(market_key)
    if not mkt_data:return 0

    cal_gap=mkt_data.get("cal_gap",0)
    if cal_gap>15:return -10
    if cal_gap>10:return -5
    if cal_gap>7:return -2
    return 0

def get_league_performance(league_key:str)->dict:
    data=_load()
    return data.get(league_key,{})

def get_all_performance()->dict:
    return _load()
