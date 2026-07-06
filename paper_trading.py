"""Kağıt üstü canlı test"""
import json,os,logging
from datetime import datetime
from settlement import settle_bet

logger = logging.getLogger(__name__)

STORE=os.path.join(os.path.dirname(__file__),"paper_bets.json")
INITIAL_BANKROLL=1000

def _load()->list:
    try:
        with open(STORE,"r") as f:return json.load(f)
    except FileNotFoundError:return[]
    except Exception:
        logger.warning("paper_bets load failed",exc_info=True)
        return[]

def _save(data:list):
    with open(STORE,"w") as f:json.dump(data,f)

def create_paper_bet(entry:dict)->dict:
    bets=_load()
    bet={
        "id":len(bets)+1,
        "match":entry.get("match",""),
        "market":entry.get("market",""),
        "key":entry.get("key",""),
        "odds":entry.get("odds",0),
        "prob":entry.get("prob",0),
        "value_pct":entry.get("value_pct",0),
        "stake":entry.get("bet",entry.get("stake",20)),
        "confidence":entry.get("confidence",0),
        "reason_flags":entry.get("reason_flags",[]),
        "league":entry.get("league",""),
        "status":"pending",
        "result":None,
        "pnl":0,
        "created":datetime.utcnow().isoformat()+"Z",
        "settled":None,
    }
    bets.append(bet)
    _save(bets)
    return bet

def settle_paper_bet(bet_id:int,home_goals:int,away_goals:int,
                     ht_home:int=None,ht_away:int=None)->dict:
    bets=_load()
    for b in bets:
        if b["id"]==bet_id and b["status"]=="pending":
            won=settle_bet(b["key"],home_goals,away_goals,ht_home,ht_away)
            b["status"]="won" if won else "lost"
            b["pnl"]=round(b["stake"]*(b["odds"]-1),2) if won else -b["stake"]
            b["result"]=f"{home_goals}-{away_goals}"
            b["settled"]=datetime.utcnow().isoformat()+"Z"
            _save(bets)
            return b
    return{"error":"Bet bulunamadı veya zaten sonuçlanmış"}

def get_paper_bets()->list:
    return _load()

def get_paper_stats()->dict:
    bets=_load()
    settled=[b for b in bets if b["status"] in("won","lost")]
    pending=[b for b in bets if b["status"]=="pending"]
    if not settled:
        return{"total_bets":len(bets),"settled":0,"pending":len(pending),
               "wins":0,"losses":0,"roi":0,"yield":0,"total_staked":0,
               "total_profit":0,"bankroll":INITIAL_BANKROLL,"bankroll_curve":[INITIAL_BANKROLL]}

    wins=sum(1 for b in settled if b["status"]=="won")
    losses=len(settled)-wins
    total_staked=sum(b["stake"] for b in settled)
    total_profit=sum(b["pnl"] for b in settled)
    roi=round(total_profit/INITIAL_BANKROLL*100,2)
    yld=round(total_profit/total_staked*100,2) if total_staked>0 else 0

    bankroll=INITIAL_BANKROLL
    curve=[bankroll]
    for b in sorted(settled,key=lambda x:x.get("settled","")):
        bankroll+=b["pnl"]
        curve.append(round(bankroll,2))

    return{
        "total_bets":len(bets),"settled":len(settled),"pending":len(pending),
        "wins":wins,"losses":losses,
        "hit_rate":round(wins/len(settled)*100,1),
        "total_staked":round(total_staked,2),
        "total_profit":round(total_profit,2),
        "roi":roi,"yield":yld,
        "bankroll":round(bankroll,2),
        "bankroll_curve":curve,
    }

def clear_paper_bets():
    _save([])
