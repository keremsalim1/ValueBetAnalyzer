"""Risk yönetimi v8 - adaptif Kelly, drawdown, limitler, korelasyon"""
import math
import logging
from config import KELLY_HARD_CAP, MIN_CONFIDENCE, DAILY_RISK_CAP, WEEKLY_RISK_CAP, MAX_CORRELATED_BETS, MIN_EDGE

logger = logging.getLogger(__name__)

def value_calc(prob:float, odds:float)->float:
    return round(prob*odds-1, 4) if odds>1.0 else -1.0

def adaptive_kelly(prob:float, odds:float, confidence:int, market_class:str, bankroll:float)->dict:
    b=odds-1
    if b<=0 or prob<=0:return{"fraction":0,"bet":0,"reason":"invalid_odds"}
    
    if confidence<MIN_CONFIDENCE:
        return{"fraction":0,"bet":0,"reason":"low_confidence"}
    
    edge=prob*odds-1
    if edge<MIN_EDGE:return{"fraction":0,"bet":0,"reason":"below_min_edge"}
    if edge>0.40:return{"fraction":0,"bet":0,"reason":"edge_too_high"}
    
    raw_f=(b*prob-(1-prob))/b
    raw_f=max(0.0,raw_f)
    
    conf_mult=confidence/100.0
    mkt_mult={"tradable":1.0,"informational":0.7,"experimental":0.4,"disabled":0.0}.get(market_class,0.5)
    
    if edge>0.25:edge_mult=0.08
    elif edge>0.15:edge_mult=0.12
    elif edge>0.10:edge_mult=0.18
    elif edge>0.05:edge_mult=0.20
    else:edge_mult=0.15
    
    adj_f=raw_f*edge_mult*conf_mult*mkt_mult
    adj_f=adj_f**0.75
    adj_f=min(adj_f,KELLY_HARD_CAP)
    bet=round(adj_f*bankroll)
    
    return{"fraction":round(adj_f,4),"bet":max(0,bet),"reason":"ok"}

def filter_correlated_bets(value_bets:list)->list:
    """
    Aynı maçtan max MAX_CORRELATED_BETS value bet.
    En yüksek edge'li olanları tut.
    """
    match_counts={}
    filtered=[]
    for vb in sorted(value_bets, key=lambda x:x.get("value_pct",0), reverse=True):
        match_key=vb.get("match","")
        match_counts[match_key]=match_counts.get(match_key,0)+1
        if match_counts[match_key]<=MAX_CORRELATED_BETS:
            filtered.append(vb)
    return filtered

def apply_risk_limits(value_bets:list, bankroll:float, weekly_spent:float=0.0)->list:
    """
    Günlük ve haftalık risk limiti uygula.
    weekly_spent: bu hafta zaten yapılmış bahislerin toplamı (paper_bets veya harici tracker).
    """
    daily_cap=bankroll*DAILY_RISK_CAP
    weekly_cap=bankroll*WEEKLY_RISK_CAP
    running_total=0
    capped=[]

    # Haftalık cap zaten dolmuşsa hiç bahis önerme
    if weekly_spent>=weekly_cap:
        return []

    for vb in value_bets:
        bet=vb.get("bet",0)
        # Haftalık kontrol
        if weekly_spent+running_total+bet>weekly_cap:
            remaining_weekly=weekly_cap-(weekly_spent+running_total)
            if remaining_weekly>5:
                vb_copy=dict(vb)
                vb_copy["bet"]=round(remaining_weekly)
                vb_copy["reason_flags"]=vb.get("reason_flags",[])+["weekly_risk_capped"]
                capped.append(vb_copy)
            break
        # Günlük kontrol
        if running_total+bet<=daily_cap:
            capped.append(vb)
            running_total+=bet
        else:
            remaining=daily_cap-running_total
            if remaining>5:
                vb_copy=dict(vb)
                vb_copy["bet"]=round(remaining)
                vb_copy["reason_flags"]=vb.get("reason_flags",[])+["daily_risk_capped"]
                capped.append(vb_copy)
            break
    return capped

def build_reason_flags(edge:float, confidence:int, market_class:str)->list:
    flags=[]
    if edge>=0.10:flags.append("strong_edge")
    elif edge>=0.05:flags.append("moderate_edge")
    else:flags.append("marginal_edge")
    
    if confidence>=70:flags.append("high_confidence")
    elif confidence>=50:flags.append("ok_confidence")
    elif confidence>=30:flags.append("low_confidence")
    else:flags.append("very_low_confidence")
    
    if market_class=="experimental":flags.append("experimental_market")
    if market_class=="informational":flags.append("no_real_odds_typical")
    
    # Uyarılar
    if edge>0.20:flags.append("⚠️ unusually_high_edge")
    
    return flags
