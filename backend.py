"""
Value Bet Analyzer v8
=====================
Modüler yapı: config, strength_model, probability_model, risk_manager,
              odds_matcher, market_builder, backtest, data_fetch

v7→v8:
  - Dixon-Coles low-score düzeltmesi
  - İY/MS joint model (bağımsız çarpım değil)
  - Totals line doğrulaması (2.5 line kontrolü)
  - Event eşleştirme: Jaccard + zaman yakınlığı + confidence score
  - Season otomatik (Ağustos'tan itibaren yeni sezon)
  - Adaptif Kelly (edge+confidence+market_class bazlı)
  - Drawdown kontrolü + günlük/haftalık risk limiti
  - Korelasyonlu bahis engelleme (aynı maçtan max 2)
  - Backtest endpoint (walk-forward, ROI, Brier, calibration)
  - Kötü market otomatik kapatma altyapısı (DISABLED_MARKETS)
  - JSON/CSV export

Port: 2000
.env: FOOTBALL_DATA_API_KEY, ODDS_API_KEY
"""
import sys,os,json,csv,io,asyncio,logging
sys.path.insert(0,os.path.dirname(__file__))
import config

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager
from datetime import datetime,timedelta
from fastapi import FastAPI,HTTPException,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse,Response

from config import LEAGUES,SEASON,MIN_EDGE,KELLY_HARD_CAP,MIN_CONFIDENCE,DAILY_RISK_CAP,MAX_CORRELATED_BETS,REAL_BETTING_MODE,EXPANSION_MARKETS,EXPANSION_MIN_BETS,EXPANSION_MIN_ROI
from strength_model import (team_strength, compute_rest_days, compute_form_trend,
                             compute_h2h_factor, compute_standings, compute_position_gap,
                             apply_context_features)
from probability_model import match_probs,estimate_rho
from elo_rating import get_team_ratings
from odds_matcher import find_odds,extract_best_odds,get_best_odds_detail,get_margin_comparison,get_odds_movement
from market_builder import build_markets, get_daily_review_stats
from risk_manager import filter_correlated_bets,apply_risk_limits
from data_fetch import fd_fetch,odds_fetch,clear_cache,get_historical_matches,get_upcoming_matches
from manual_analyzer import analyze_manual_input
from trust_gate import is_trusted_market,get_trusted_markets,update_trust_from_backtest,get_all_trust_status,load_trust_data
from line_tracker import save_opening_snapshot,save_pre_match_snapshot,get_clv_report,get_clv_stats,clear_snapshots,try_update_closing
from paper_trading import create_paper_bet,settle_paper_bet as settle_paper,get_paper_bets,get_paper_stats,clear_paper_bets
from apifootball import enrich_match,blend_xg,injuries_to_adjustments,find_fixture_id

# ─── CLV BACKGROUND REFRESH ───
async def _clv_odds_refresh():
    """
    Saatte bir tüm ligler için oran snapshotlarını güncelle.
    Açılış oranı (opening) ilk /analyze çağrısında kaydedilir.
    Bu task ise 'latest' snapshot'u sürekli taze tutar → gerçek CLV.
    Ayrıca event_id'si olan maçlar için The Odds API historical endpoint denenır.
    """
    await asyncio.sleep(1800)  # başlangıçta 30dk bekle
    while True:
        # 1) Mevcut pseudo-closing snapshot güncellemesi
        for lc,lg in LEAGUES.items():
            if not lg.get("odds"):continue
            try:
                real_odds=await odds_fetch(lg["odds"],"h2h,totals")
                upcoming=await get_upcoming_matches(lg["fd"],days=7)
                for m in upcoming:
                    hname=m["homeTeam"]["name"];aname=m["awayTeam"]["name"]
                    matched=find_odds(real_odds,hname,aname,m.get("utcDate"))
                    if matched:
                        best=extract_best_odds(matched["bookmakers"])
                        if best:
                            mk=f"{hname} vs {aname}"
                            save_pre_match_snapshot(mk,best,matched.get("odds_timestamp",""))
            except Exception:
                pass  # API hatası loopı durdurmasın

        # 2) Gerçek kapanış oranı: event_id'si olan ve henüz closing kaydedilmemiş maçlar
        try:
            import json as _json
            from line_tracker import STORE_PATH as _snap_path
            with open(_snap_path,"r") as _f:
                _snaps=_json.load(_f)
            for _mk,_snap in _snaps.items():
                if _snap.get("closing") or not _snap.get("event_id"):
                    continue
                await try_update_closing(_mk)
        except Exception:
            pass

        await asyncio.sleep(3600)  # 1 saat bekle

@asynccontextmanager
async def lifespan(app:FastAPI):
    task=asyncio.create_task(_clv_odds_refresh())
    yield
    task.cancel()

from config import VERSION
app=FastAPI(title="Value Bet Analyzer",version=VERSION,lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:2000","http://127.0.0.1:2000"],allow_methods=["*"],allow_headers=["*"])

# ─── CONFIDENCE ───
from performance_memory import get_market_performance_score,get_calibration_penalty

def match_confidence(hs:dict,as_:dict,has_real:bool,odds_conf:int=100,league_key:str=None)->dict:
    h_n=hs.get("n",0);a_n=as_.get("n",0)
    data_quality=min(25,int((min(h_n,a_n)/15)*25))

    h_bal=min(hs.get("home_n",0),hs.get("away_n",0))/(max(hs.get("home_n",1),hs.get("away_n",1))+0.001)
    a_bal=min(as_.get("home_n",0),as_.get("away_n",0))/(max(as_.get("home_n",1),as_.get("away_n",1))+0.001)
    balance=int(((h_bal+a_bal)/2)*15)

    odds_quality=0
    if has_real:odds_quality+=15
    odds_quality+=int((odds_conf/100)*10)

    perf_scores=[]
    for mk in["home","draw","away","over25","under25"]:
        perf_scores.append(get_market_performance_score(mk,league_key))
    market_perf=max(-15,min(15,sum(perf_scores)//max(len(perf_scores),1)))

    cal_penalties=[]
    for mk in["home","draw","away","over25","under25"]:
        cal_penalties.append(get_calibration_penalty(mk,league_key))
    calibration=max(-10,min(0,sum(cal_penalties)//max(len(cal_penalties),1)))

    team_conf=int(((hs.get("confidence",50)+as_.get("confidence",50))/200)*15)

    total=data_quality+balance+odds_quality+market_perf+calibration+team_conf
    total=max(0,min(100,total))

    return{
        "score":total,
        "components":{
            "data_quality":data_quality,
            "balance":balance,
            "odds_quality":odds_quality,
            "market_performance":market_perf,
            "calibration":calibration,
            "team_confidence":team_conf,
        }
    }

# ─── ENDPOINTS ───
@app.get("/",response_class=HTMLResponse)
async def root():return FRONTEND_HTML

@app.get("/api")
async def api_info():
    from config import FD_KEY,ODDS_KEY,APIFOOTBALL_KEY
    return{"v":VERSION,"season":SEASON,"fd":bool(FD_KEY),"odds":bool(ODDS_KEY),
        "apifootball":bool(APIFOOTBALL_KEY),
        "leagues":list(LEAGUES.keys()),
        "features":["dixon_coles_data_rho","joint_iy_ms","adaptive_kelly","correlation_filter",
                     "daily_risk_cap","weekly_risk_cap","backtest","totals_line_check",
                     "event_matching_v2","real_xg_blend","auto_injury_adjust","clv_background_refresh"]}

@app.get("/leagues")
async def get_leagues():return{k:{"name":v["name"],"flag":v.get("flag",""),"type":v["type"]} for k,v in LEAGUES.items()}

@app.get("/analyze/{lc}")
async def analyze(lc:str,bankroll:float=Query(1000),days:int=Query(14)):
    if lc not in LEAGUES:raise HTTPException(400,f"Geçersiz: {lc}")
    lg=LEAGUES[lc];neutral=lg.get("neutral",False)
    
    hist=await get_historical_matches(lg["fd"])
    upcoming=await get_upcoming_matches(lg["fd"],days)

    if not hist:return{"league":lc,"error":"Veri yok","analyses":[],"top_value_bets":[]}

    ah=sum(m["hs"] for m in hist)/len(hist)
    aa=sum(m["as"] for m in hist)/len(hist)
    rho=estimate_rho(hist)  # veriden Dixon-Coles rho tahmini
    elo_ratings=get_team_ratings(hist)  # Glicko-2 derecelendirmeleri
    standings=compute_standings(hist)   # puan tablosu (position_gap için)
    teams=set()
    for m in hist:teams.add(m["ht"]);teams.add(m["at"])
    strengths={t:team_strength(t,hist,ah,aa,elo_ratings=elo_ratings) for t in teams}

    real_odds=await odds_fetch(lg.get("odds",""),"h2h,totals")
    analyses=[];all_vb=[]

    for m in upcoming:
        hname=m["homeTeam"]["name"];aname=m["awayTeam"]["name"]
        match_date=m.get("utcDate","")
        hs=strengths.get(hname,{"atk":1.0,"def":1.0,"home_atk":1.0,"home_def":1.0,"away_atk":1.0,"away_def":1.0,"n":0,"home_n":0,"away_n":0,"confidence":15})
        as_=strengths.get(aname,{"atk":1.0,"def":1.0,"home_atk":1.0,"home_def":1.0,"away_atk":1.0,"away_def":1.0,"n":0,"home_n":0,"away_n":0,"confidence":15})

        # Model xG (temel)
        hxg=round(hs.get("home_atk",hs["atk"])*as_.get("away_def",as_["def"])*ah,2)
        axg=round(as_.get("away_atk",as_["atk"])*hs.get("home_def",hs["def"])*aa,2)

        # ─── API-Football: gerçek xG + sakatlık ───────────────────────────
        fixture_id=await find_fixture_id(hname,aname,match_date,lc,SEASON)
        enrichment=await enrich_match(hname,aname,lc,SEASON,fixture_id)
        af_available=enrichment.get("af_available",False)

        # xG blending (gerçek veri varsa modeli güçlendir)
        hxg,axg=blend_xg(hxg,axg,enrichment,home_is_home=not neutral)
        hxg=round(hxg,2);axg=round(axg,2)

        # Sakatlık/ceza ayarlaması (hücum + savunma)
        h_inj=enrichment.get("home_injuries",[])
        a_inj=enrichment.get("away_injuries",[])
        h_atk_inj,h_def_inj=injuries_to_adjustments(h_inj)
        a_atk_inj,a_def_inj=injuries_to_adjustments(a_inj)
        hxg=round(max(0.10, hxg*(1+h_atk_inj)*(1+a_def_inj)),2)
        axg=round(max(0.10, axg*(1+a_atk_inj)*(1+h_def_inj)),2)
        # ──────────────────────────────────────────────────────────────────

        # ─── Contextual features ───────────────────────────────────────────
        home_rest  = compute_rest_days(hname, hist, match_date)
        away_rest  = compute_rest_days(aname, hist, match_date)
        home_trend = compute_form_trend(hname, hist)
        away_trend = compute_form_trend(aname, hist)
        h2h_feat   = compute_h2h_factor(hname, aname, hist)
        pos_feat   = compute_position_gap(hname, aname, standings)
        hxg, axg   = apply_context_features(hxg, axg, home_rest, away_rest,
                                             home_trend, away_trend, h2h_feat)
        # ──────────────────────────────────────────────────────────────────

        h_elo=elo_ratings.get(hname,{})
        a_elo=elo_ratings.get(aname,{})
        elo_diff=round(h_elo.get("rating",1500)-a_elo.get("rating",1500),1)
        probs=match_probs(hxg,axg,lg.get("avg_corner",10.0),ah+aa,neutral,rho=rho,rating_diff=elo_diff)
        matched=find_odds(real_odds,hname,aname,m.get("utcDate"))
        
        bk_list=[];odds_match_conf=0
        if matched:
            bk_list=matched["bookmakers"]
            odds_match_conf=matched.get("match_confidence",50)
        best=extract_best_odds(bk_list)
        has_real=bool(best)

        match_key=f"{hname} vs {aname}"
        best_detail=get_best_odds_detail(bk_list)
        margin_comp=get_margin_comparison(bk_list)

        if has_real:
            odds_ts=matched.get("odds_timestamp","") if matched else ""
            await save_opening_snapshot(match_key,best,odds_ts,
                event_id=matched.get("event_id",""),
                sport_key=matched.get("sport_key",""),
                commence_time=matched.get("commence_time",""),
                home_team=hname,away_team=aname)
            save_pre_match_snapshot(match_key,best,odds_ts)

        odds_mv=get_odds_movement(match_key,bk_list)
        steam_move=odds_mv.get("steam_move",False)

        conf_result=match_confidence(hs,as_,has_real,odds_match_conf,lc)
        steam_adj=3 if steam_move else 0
        conf=min(100,max(0,conf_result["score"]+pos_feat["conf_adj"]+steam_adj))
        conf_components=conf_result["components"]
        markets,match_meta=build_markets(probs,best,bankroll,conf,hxg,axg,best_odds_detail=best_detail)
        
        for mkt in markets:
            if REAL_BETTING_MODE and mkt["is_value"] and not is_trusted_market(lc,mkt["key"]):
                mkt["is_value"]=False
                mkt["bet"]=0
                mkt["kelly"]=0
                mkt["reason_flags"]=mkt.get("reason_flags",[])+["not_trusted_live"]
            if mkt["is_value"]:
                all_vb.append({"match":f"{hname} vs {aname}","date":m.get("utcDate"),
                    "league":lc,"league_name":lg["name"],"market":mkt["label"],
                    "key":mkt["key"],"odds":mkt["odds"],"prob":mkt["prob"],
                    "value_pct":mkt["value_pct"],"bet":mkt["bet"],
                    "odds_source":"real","market_class":mkt["market_class"],
                    "confidence":conf,"reason_flags":mkt["reason_flags"]})
        
        analyses.append({"match_id":m.get("id"),"date":m.get("utcDate"),
            "matchday":m.get("matchday",""),"home_team":hname,"away_team":aname,
            "home_str":hs,"away_str":as_,"home_xg":hxg,"away_xg":axg,
            "odds_source":"real" if has_real else "model","confidence":conf,
            "confidence_components":conf_components,
            "bookmakers":bk_list,"best_odds":best,
            "best_odds_detail":best_detail,
            "margin":margin_comp,
            "odds_movement":odds_mv.get("movements",{}),
            "steam_move":steam_move,
            "steam_markets":odds_mv.get("steam_markets",[]),
            "daily_limit_reached":match_meta.get("daily_limit_reached",False),
            "markets":sorted(markets,key=lambda x:x["value_pct"],reverse=True),
            "top_scores":probs.get("top_scores",[]),
            "corners_expected":probs.get("corners_expected",0),"neutral":neutral,
            "xg_source":("real_rapidapi" if enrichment.get("rapidapi_available") else
                         "real" if enrichment.get("xg_available") else
                         "af_goals" if af_available else "model"),
            "af_available":af_available,
            "home_injuries":[{"player":i["player"],"position":i["position"],"type":i["type"],"reason":i["reason"]} for i in h_inj],
            "away_injuries":[{"player":i["player"],"position":i["position"],"type":i["type"],"reason":i["reason"]} for i in a_inj],
            "injury_adjustment":{"home_atk":round(h_atk_inj,3),"home_def":round(h_def_inj,3),
                                  "away_atk":round(a_atk_inj,3),"away_def":round(a_def_inj,3)},
            "home_elo":{"rating":h_elo.get("rating",1500),"rd":h_elo.get("rd",350),
                        "trend_last5":h_elo.get("trend_last5",0.0)} if h_elo else None,
            "away_elo":{"rating":a_elo.get("rating",1500),"rd":a_elo.get("rd",350),
                        "trend_last5":a_elo.get("trend_last5",0.0)} if a_elo else None,
            "elo_diff":elo_diff,
            "features":{
                "home_rest":{"days":home_rest["days"],"label":home_rest["label"],
                             "multiplier":home_rest["multiplier"]},
                "away_rest":{"days":away_rest["days"],"label":away_rest["label"],
                             "multiplier":away_rest["multiplier"]},
                "home_form":{"slope":home_trend["slope"],"multiplier":home_trend["multiplier"],
                             "diffs":home_trend["diffs"]},
                "away_form":{"slope":away_trend["slope"],"multiplier":away_trend["multiplier"],
                             "diffs":away_trend["diffs"]},
                "h2h":{"win_rate":h2h_feat["win_rate"],"total":h2h_feat["total"],
                       "home_wins":h2h_feat["home_wins"],"multiplier":h2h_feat["multiplier"]},
                "position":{"home_pos":pos_feat["home_pos"],"away_pos":pos_feat["away_pos"],
                            "gap":pos_feat["gap"],"conf_adj":pos_feat["conf_adj"]},
            }})
    
    trusted_live=get_trusted_markets(lc)

    # Expansion market performans özeti (trust_data'dan okunur)
    _trust_league=load_trust_data().get(lc,{})
    expansion_markets_summary={}
    for _mkt in EXPANSION_MARKETS:
        _s=_trust_league.get(_mkt)
        if _s:
            expansion_markets_summary[_mkt]={
                "bets":_s.get("bets",0),
                "roi":_s.get("roi",0),
                "hit_rate":_s.get("hit_rate",0),
                "status":"tradable" if _mkt in config.TRADABLE_MARKETS else "disabled",
                "ready_for_live":_s.get("bets",0)>=EXPANSION_MIN_BETS and _s.get("roi",0)>EXPANSION_MIN_ROI,
                "needs_bets":max(0,EXPANSION_MIN_BETS-_s.get("bets",0)),
            }
        else:
            expansion_markets_summary[_mkt]={"status":"not_backtested","bets":0,"ready_for_live":False}

    # Risk kontrolleri
    all_vb.sort(key=lambda x:x["value_pct"],reverse=True)
    all_vb=filter_correlated_bets(all_vb)
    all_vb=apply_risk_limits(all_vb,bankroll)
    
    # Live lock
    live_lock_reasons=[]
    if REAL_BETTING_MODE:
        if not trusted_live:
            live_lock_reasons.append("no_trusted_markets")
        else:
            all_vb=[vb for vb in all_vb if vb.get("key") in trusted_live]
        if len(hist)<100:
            live_lock_reasons.append("insufficient_backtest_coverage")
            all_vb=[]
        from line_tracker import get_clv_report
        clv=get_clv_report()
        if clv:
            neg=[c for c in clv if c["clv_direction"]=="negative"]
            if len(neg)>len(clv)*0.6:
                live_lock_reasons.append("negative_clv_trend")
                all_vb=[]
        if live_lock_reasons:
            all_vb=[]
    
    return{"league":lc,"league_name":lg["name"],"league_type":lg["type"],
        "bankroll":bankroll,"days_ahead":days,"hist_matches":len(hist),
        "avg_home":round(ah,2),"avg_away":round(aa,2),"upcoming":len(analyses),
        "value_bets_count":len(all_vb),
        "odds_source":"The Odds API" if real_odds else "Yok",
        "model_version":f"v{VERSION}","season":SEASON,"dixon_coles_rho":rho,
        "real_betting_mode":REAL_BETTING_MODE,
        "live_lock_reasons":live_lock_reasons,
        "risk_controls":{"daily_cap_pct":DAILY_RISK_CAP*100,"max_correlated":MAX_CORRELATED_BETS,"min_edge_pct":MIN_EDGE*100,"kelly_cap_pct":KELLY_HARD_CAP*100,"min_confidence":MIN_CONFIDENCE},
        "trusted_live_markets":trusted_live,
        "expansion_markets":expansion_markets_summary,
        "analyses":analyses,"top_value_bets":all_vb[:20]}

@app.get("/value-bets")
async def all_value_bets(bankroll:float=Query(1000),days:int=Query(14)):
    bets=[]
    for lc in LEAGUES:
        try:r=await analyze(lc,bankroll,days);bets.extend(r.get("top_value_bets",[]))
        except Exception:
            logger.warning("value_bets analyze failed league=%s",lc,exc_info=True)
    bets.sort(key=lambda x:x["value_pct"],reverse=True)
    bets=filter_correlated_bets(bets)
    bets=apply_risk_limits(bets,bankroll)
    return{"bankroll":bankroll,"total":len(bets),"bets":bets[:30],"model_version":f"v{VERSION}","season":SEASON}

@app.get("/backtest/{lc}")
async def backtest_league(lc:str,monte_carlo:bool=Query(False),sensitivity:bool=Query(False)):
    if lc not in LEAGUES:raise HTTPException(400,f"Geçersiz: {lc}")
    lg=LEAGUES[lc]
    hist=await get_historical_matches(lg["fd"],limit=500)
    if len(hist)<60:return{"league":lc,"error":f"Yeterli maç yok ({len(hist)}/60)"}
    ah=sum(m["hs"] for m in hist)/len(hist)
    aa=sum(m["as"] for m in hist)/len(hist)
    from backtest import run_backtest
    from performance_memory import update_from_backtest
    result=run_backtest(hist,ah,aa,warmup=50,avg_corner=lg.get("avg_corner",10.0),
                        run_monte_carlo=monte_carlo,run_sensitivity=sensitivity)
    result["league"]=lc;result["league_name"]=lg["name"];result["season"]=SEASON
    update_trust_from_backtest(lc,result)
    update_from_backtest(lc,result)
    result["trusted_live_markets"]=get_trusted_markets(lc)
    return result

@app.get("/export/json")
async def export_json(bankroll:float=Query(1000),days:int=Query(14)):
    data=await all_value_bets(bankroll,days)
    content=json.dumps(data,ensure_ascii=False,indent=2)
    return Response(content=content,media_type="application/json",headers={"Content-Disposition":"attachment; filename=value_bets.json"})

@app.get("/export/csv")
async def export_csv(bankroll:float=Query(1000),days:int=Query(14)):
    data=await all_value_bets(bankroll,days)
    output=io.StringIO()
    w=csv.writer(output)
    w.writerow(["Lig","Maç","Tarih","Market","Sınıf","Oran","Model%","Value%","Bahis₺","Güven","Nedenler"])
    for b in data.get("bets",[]):
        w.writerow([b.get("league_name",""),b["match"],b.get("date","")[:10],b["market"],
            b.get("market_class",""),b["odds"],b["prob"],b["value_pct"],b["bet"],
            b.get("confidence",""),"|".join(b.get("reason_flags",[]))])
    return Response(content=output.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=value_bets.csv"})

@app.delete("/cache")
async def do_clear_cache():clear_cache();return{"ok":True}

@app.get("/disabled-markets")
async def get_disabled_markets():
    return{"disabled":sorted(config.DISABLED_MARKETS),"tradable":sorted(config.TRADABLE_MARKETS)}

@app.get("/trust-status")
async def trust_status():
    clv = get_clv_report()
    clv_stats = get_clv_stats(clv)
    return get_all_trust_status(clv_by_market=clv_stats.get("by_market", {}))

@app.get("/clv-report")
async def clv_report():
    report=get_clv_report()
    stats=get_clv_stats(report)
    return{"report":report,**stats}

@app.delete("/clv-report")
async def clv_reset():
    clear_snapshots();return{"ok":True}

@app.post("/paper-bets/add")
async def paper_add(body:dict):
    return create_paper_bet(body)

@app.post("/paper-bets/settle")
async def paper_settle(body:dict):
    return settle_paper(body.get("id",0),body.get("home_goals",0),body.get("away_goals",0),
                        body.get("ht_home"),body.get("ht_away"))

@app.get("/paper-bets")
async def paper_list():
    return{"bets":get_paper_bets()}

@app.get("/paper-stats")
async def paper_statistics():
    return get_paper_stats()

@app.delete("/paper-bets")
async def paper_clear():
    clear_paper_bets();return{"ok":True}

@app.get("/daily-review")
async def daily_review():
    from datetime import date
    ps=get_paper_stats()
    bets=get_paper_bets()
    today=date.today().isoformat()
    today_bets=[b for b in bets if b.get("created","")[:10]==today]
    settled_today=[b for b in today_bets if b["status"] in("won","lost")]
    wins_today=sum(1 for b in settled_today if b["status"]=="won")
    clv=get_clv_report()
    clv_stats=get_clv_stats(clv)
    trust=get_all_trust_status(clv_by_market=clv_stats.get("by_market",{}))
    neg_clv=[c for c in clv if c["clv_direction"]=="negative"]
    suspicious=[b for b in bets if any("anomaly" in f or "unusually" in f for f in b.get("reason_flags",[]))]
    return{
        "date":today,
        "today_bets":len(today_bets),
        "today_settled":len(settled_today),
        "today_wins":wins_today,
        "today_hit_rate":round(wins_today/len(settled_today)*100,1) if settled_today else 0,
        "overall":{"total":ps.get("total_bets",0),"roi":ps.get("roi",0),"yield":ps.get("yield",0),"hit_rate":ps.get("hit_rate",0),"bankroll":ps.get("bankroll",1000)},
        "suspicious_edges":len(suspicious),
        "disabled_markets":sorted(config.DISABLED_MARKETS),
        "trusted_markets":trust,
        "clv_summary":{"total":len(clv),"negative":len(neg_clv),"negative_pct":round(len(neg_clv)/len(clv)*100,1) if clv else 0},
        "filter_stats":get_daily_review_stats(),
        "real_betting_mode":REAL_BETTING_MODE,
        "live_lock_active":not bool(get_trusted_markets("PL")),
    }

@app.post("/disabled-markets/reset")
async def reset_disabled_markets():
    from disabled_markets_store import save_disabled_markets
    config.DISABLED_MARKETS.clear()
    config.DISABLED_MARKETS.update(config._BASE_DISABLED)
    config.TRADABLE_MARKETS.clear()
    config.TRADABLE_MARKETS.update({"home","draw","away","over25","under25"})
    config.TRADABLE_MARKETS-=config.DISABLED_MARKETS
    save_disabled_markets(config.DISABLED_MARKETS)
    return{"disabled":sorted(config.DISABLED_MARKETS),"tradable":sorted(config.TRADABLE_MARKETS)}

@app.post("/analyze-manual")
async def analyze_manual(body:dict):
    try:
        result=analyze_manual_input(body)
        return result
    except Exception as e:
        raise HTTPException(400,str(e))

@app.get("/debug/{lc}")
async def debug_league(lc:str):
    if lc not in LEAGUES:raise HTTPException(400,f"Geçersiz: {lc}")
    lg=LEAGUES[lc];r={"season":SEASON}
    try:
        fd=await fd_fetch(f"/competitions/{lg['fd']}/matches",{"status":"FINISHED","limit":5,"season":SEASON})
        r["fd_matches"]=len(fd.get("matches",[]));r["fd_ok"]=True
    except Exception as e:r["fd_ok"]=False;r["fd_error"]=str(e)
    if lg.get("odds"):
        odds=await odds_fetch(lg["odds"])
        r["odds_events"]=len(odds);r["odds_ok"]=len(odds)>0
    # API-Football bağlantı testi
    from config import APIFOOTBALL_KEY
    from apifootball import get_league_teams, AF_LEAGUE_IDS
    r["af_key_set"]=bool(APIFOOTBALL_KEY)
    r["af_league_id"]=AF_LEAGUE_IDS.get(lc)
    if APIFOOTBALL_KEY and AF_LEAGUE_IDS.get(lc):
        teams=await get_league_teams(lc,SEASON)
        r["af_teams_count"]=len(teams)
        r["af_ok"]=len(teams)>0
    return{"league":lc,"name":lg["name"],"model":f"v{VERSION}","debug":r}

if __name__=="__main__":
    import uvicorn;uvicorn.run(app,host="0.0.0.0",port=2000)

# ─── FRONTEND ───
FRONTEND_HTML=r"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Value Bet Analyzer v8</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@400;700;800&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}body{font-family:'DM Sans',sans-serif;background:#0a0a0a;color:#e0e0e0;min-height:100vh;padding:16px}
.m{font-family:'JetBrains Mono',monospace}@keyframes spin{to{transform:rotate(360deg)}}
.sp{width:28px;height:28px;border:3px solid rgba(255,255,255,.08);border-top-color:#00e676;border-radius:50%;animation:spin .7s linear infinite}
.b{padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;display:inline-block}
.bh{background:linear-gradient(135deg,#00c853,#00e676);color:#003d00;box-shadow:0 2px 8px rgba(0,200,83,.3)}
.bm{background:linear-gradient(135deg,#ffd600,#ffea00);color:#5d4600}.bn{background:rgba(255,255,255,.06);color:#777}
.btn{padding:6px 14px;border-radius:20px;border:none;font-size:11px;cursor:pointer;font-weight:600;transition:.2s}
.ba{background:rgba(0,200,83,.15);color:#00e676;border:1px solid rgba(0,200,83,.3)}
.bi{background:rgba(255,255,255,.04);color:#777;border:1px solid rgba(255,255,255,.06)}.btn:hover{filter:brightness(1.3)}
.card{background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.06);border-radius:14px;padding:14px;cursor:pointer;transition:.3s;margin-bottom:8px}
.card:hover{border-color:rgba(255,255,255,.14)}.csel{background:linear-gradient(135deg,rgba(0,200,83,.08),rgba(0,230,118,.04))!important;border-color:rgba(0,200,83,.3)!important}
.mg{display:grid;grid-template-columns:repeat(5,1fr);gap:3px;margin-bottom:8px}
.mc{text-align:center;padding:5px 2px;border-radius:8px}.mv{background:rgba(0,200,83,.08);border:1px solid rgba(0,200,83,.2)}
.mn{background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.04)}
table{width:100%;border-collapse:separate;border-spacing:0 3px;font-size:11px}th{color:#666;font-size:9px;letter-spacing:1px;padding:4px 6px}td{padding:7px 6px}
.panel{background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.06);border-radius:14px;padding:18px;margin-top:14px}
.tag{font-size:9px;padding:2px 6px;border-radius:6px;font-weight:600}.tg{background:rgba(0,200,83,.12);color:#00e676}
.ty{background:rgba(255,152,0,.12);color:#ff9800}.tn{background:rgba(66,165,245,.12);color:#42a5f5}
.te{background:rgba(156,39,176,.12);color:#ce93d8}
.grp{display:flex;gap:5px;margin-bottom:8px;flex-wrap:wrap;align-items:center}
.glbl{font-size:9px;color:#555;letter-spacing:2px;font-weight:700;padding:2px 6px}
.cb{height:4px;border-radius:2px;background:rgba(255,255,255,.06);overflow:hidden;margin-top:4px}
.cf{height:100%;border-radius:2px;transition:width .3s}
</style></head><body>
<div style="text-align:center;margin-bottom:20px">
  <h1 style="font-size:22px;font-weight:800;background:linear-gradient(135deg,#00e676,#42a5f5);-webkit-background-clip:text;-webkit-text-fill-color:transparent">⚽ Value Bet Analyzer v8</h1>
  <p style="font-size:10px;color:#666">Dixon-Coles × Joint İY/MS × Adaptif Kelly × Backtest × Risk Kontrolü</p>
</div>
<div id="status"></div><div id="topbets" style="display:none"></div>
<div id="tabs"></div>
<div id="manual-panel" style="display:none"></div>
<div id="manual-result" style="display:none"></div>
<div id="stats" style="display:none;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:12px"></div>
<div id="tools" style="display:none;margin-bottom:12px"></div>
<div id="loading" style="display:flex;flex-direction:column;align-items:center;padding:40px;gap:10px"><div class="sp"></div><span style="font-size:12px;color:#888">Analiz ediliyor...</span></div>
<div id="list"></div><div id="detail"></div>
<div id="btresult" style="display:none"></div>
<div style="margin-top:24px;padding:12px;text-align:center;border-top:1px solid rgba(255,255,255,.04)">
  <p style="font-size:9px;color:#555;line-height:1.5">⚠️ Bu araç eğitim ve analiz amaçlıdır, bahis önerisi değildir. Sonuçlar geçmiş performansı yansıtır, gelecek garantisi vermez. Bahis finansal risk içerir.</p>
</div>
<script>
const API='';
const LIGLER={PL:{n:"Premier League",f:"🏴"},PD:{n:"La Liga",f:"🇪🇸"},BL1:{n:"Bundesliga",f:"🇩🇪"},SA:{n:"Serie A",f:"🇮🇹"},FL1:{n:"Ligue 1",f:"🇫🇷"},DED:{n:"Eredivisie",f:"🇳🇱"},PPL:{n:"Primeira Liga",f:"🇵🇹"}};
const KUPALAR={CL:{n:"Şampiyonlar Ligi",f:"⭐"},EL:{n:"Avrupa Ligi",f:"🟠"},UECL:{n:"Konferans Ligi",f:"🔵"},WC:{n:"Dünya Kupası",f:"🌍"}};
const ALL={...LIGLER,...KUPALAR};
const MC_L={"tradable":"İŞLEM","informational":"BİLGİ","experimental":"DENEY"};
const MC_C={"tradable":"tg","informational":"tn","experimental":"te"};
let CUR='PL',DATA=null,SEL=null,MODE='api';
function $(i){return document.getElementById(i)}
const bg=v=>{const p=(v*100).toFixed(1);return v>.1?`<span class="b bh">+${p}%</span>`:v>0?`<span class="b bm">+${p}%</span>`:`<span class="b bn">${p}%</span>`};
const cc=c=>c>=70?'#00e676':c>=40?'#ffd600':'#ff5252';
const cb=(c,w)=>`<div class="cb" style="width:${w||'100%'}"><div class="cf" style="width:${c}%;background:${cc(c)}"></div></div>`;

function setStatus(ok,info){const e=$('status');e.style.cssText=`border-radius:10px;padding:9px 12px;margin-bottom:12px;font-size:11px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:${ok?'rgba(0,200,83,.08)':'rgba(255,152,0,.08)'};border:1px solid ${ok?'rgba(0,200,83,.2)':'rgba(255,152,0,.2)'}`;e.innerHTML=`<div style="width:8px;height:8px;border-radius:50%;background:${ok?'#00e676':'#ff9800'}"></div><span style="color:${ok?'#00e676':'#ff9800'};font-weight:700">${ok?'v8 BAĞLI':'HATA'}</span><span style="color:#888">|</span><span style="color:#aaa">${info}</span>`}

function renderTabs(){
  const apiTabs=`<div class="grp"><span class="glbl">LİGLER</span>${Object.entries(LIGLER).map(([k,v])=>`<button class="btn ${MODE==='api'&&k===CUR?'ba':'bi'}" onclick="sw('${k}')">${v.f} ${v.n}</button>`).join('')}</div><div class="grp"><span class="glbl">KUPALAR</span>${Object.entries(KUPALAR).map(([k,v])=>`<button class="btn ${MODE==='api'&&k===CUR?'ba':'bi'}" onclick="sw('${k}')">${v.f} ${v.n}</button>`).join('')}</div>`;
  const manualBtn=`<div class="grp"><span class="glbl">ARAÇLAR</span><button class="btn ${MODE==='manual'?'ba':'bi'}" onclick="openManual()" style="border-color:${MODE==='manual'?'rgba(156,39,176,.4)':'rgba(255,255,255,.06)'}">✏️ Manuel Analiz</button></div>`;
  $('tabs').innerHTML=apiTabs+manualBtn;
}

function openManual(){
  MODE='manual';renderTabs();
  $('stats').style.display='none';$('tools').style.display='none';$('topbets').style.display='none';
  $('list').innerHTML='';$('detail').innerHTML='';$('loading').style.display='none';$('btresult').style.display='none';
  const mp=$('manual-panel');mp.style.display='block';
  const is=`background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:9px 11px;color:#e0e0e0;font-size:13px;font-family:'JetBrains Mono',monospace;outline:none;width:100%;box-sizing:border-box`;
  const ls=`font-size:10px;color:#777;letter-spacing:1px;margin-bottom:3px;display:block`;
  mp.innerHTML=`<div class="panel" style="border-color:rgba(156,39,176,.2)">
    <div style="font-size:12px;color:#ce93d8;letter-spacing:2px;font-weight:700;margin-bottom:14px">✏️ MANUEL MAÇ ANALİZİ</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
      <div><label style="${ls}">EV SAHİBİ</label><input id="mh" style="${is}" placeholder="Takım adı" value=""></div>
      <div><label style="${ls}">DEPLASMAN</label><input id="ma" style="${is}" placeholder="Takım adı" value=""></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
      <div><label style="${ls}">LİG TİPİ</label><select id="mlt" style="${is};cursor:pointer"><option value="league" style="background:#1a1a1a">Lig</option><option value="cup" style="background:#1a1a1a">Kupa</option></select></div>
      <div><label style="${ls}">NÖTR SAHA</label><select id="mn" style="${is};cursor:pointer"><option value="0" style="background:#1a1a1a">Hayır</option><option value="1" style="background:#1a1a1a">Evet</option></select></div>
    </div>

    <div style="font-size:10px;color:#666;letter-spacing:1px;margin-bottom:6px;font-weight:600">EV SAHİBİ SON 10 MAÇ (attığı-yediği, virgülle ayır)</div>
    <div style="margin-bottom:10px"><input id="mh10" style="${is}" placeholder="2-0, 1-1, 3-1, 0-0, 2-1, 1-0, 2-2, 4-1, 1-1, 2-0"></div>

    <div style="font-size:10px;color:#666;letter-spacing:1px;margin-bottom:6px;font-weight:600">DEPLASMAN SON 10 MAÇ</div>
    <div style="margin-bottom:10px"><input id="ma10" style="${is}" placeholder="1-1, 0-2, 2-1, 1-0, 1-1, 0-1, 2-0, 1-2, 0-0, 1-1"></div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
      <div><label style="${ls}">EV SAHİBİ SON 5 EVİNDE</label><input id="mh5h" style="${is}" placeholder="2-0, 3-1, 2-1, 4-1, 2-0"></div>
      <div><label style="${ls}">DEPLASMAN SON 5 DIŞARIDA</label><input id="ma5a" style="${is}" placeholder="0-2, 1-0, 0-1, 1-2, 0-0"></div>
    </div>

    <div style="font-size:10px;color:#666;letter-spacing:1px;margin-bottom:6px;font-weight:600">EV SAHİBİ DURUM FAKTÖRLERİ</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:8px">
      <div><label style="${ls}">Motivasyon</label><select id="hf_mot" style="${is};cursor:pointer"><option value="motivation_normal" style="background:#1a1a1a">Normal</option><option value="motivation_high" style="background:#1a1a1a">Yüksek (derbi vb.)</option><option value="motivation_must_win" style="background:#1a1a1a">Kazanmak zorunda</option><option value="motivation_low" style="background:#1a1a1a">Düşük (elenen)</option></select></div>
      <div><label style="${ls}">Form</label><select id="hf_form" style="${is};cursor:pointer"><option value="form_normal" style="background:#1a1a1a">Normal</option><option value="form_hot" style="background:#1a1a1a">Sıcak (4+ galibiyet)</option><option value="form_cold" style="background:#1a1a1a">Soğuk (4+ mağlubiyet)</option><option value="form_inconsistent" style="background:#1a1a1a">Tutarsız</option></select></div>
      <div><label style="${ls}">Dinlenme</label><select id="hf_rest" style="${is};cursor:pointer"><option value="rest_normal" style="background:#1a1a1a">Normal (4-6 gün)</option><option value="rest_short" style="background:#1a1a1a">Kısa (2-3 gün)</option><option value="rest_long" style="background:#1a1a1a">Uzun (7+ gün)</option></select></div>
    </div>
    <div style="margin-bottom:14px">
      <label style="${ls}">Eksik Oyuncular (sakat/cezalı)</label>
      <div id="h_abs" style="margin-bottom:6px"></div>
      <button onclick="addAbs('h_abs')" style="padding:4px 12px;border-radius:8px;border:1px dashed rgba(255,255,255,.15);background:transparent;color:#888;font-size:11px;cursor:pointer">+ Eksik oyuncu ekle</button>
    </div>

    <div style="font-size:10px;color:#666;letter-spacing:1px;margin-bottom:6px;font-weight:600">DEPLASMAN DURUM FAKTÖRLERİ</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:8px">
      <div><label style="${ls}">Motivasyon</label><select id="af_mot" style="${is};cursor:pointer"><option value="motivation_normal" style="background:#1a1a1a">Normal</option><option value="motivation_high" style="background:#1a1a1a">Yüksek (derbi vb.)</option><option value="motivation_must_win" style="background:#1a1a1a">Kazanmak zorunda</option><option value="motivation_low" style="background:#1a1a1a">Düşük (elenen)</option></select></div>
      <div><label style="${ls}">Form</label><select id="af_form" style="${is};cursor:pointer"><option value="form_normal" style="background:#1a1a1a">Normal</option><option value="form_hot" style="background:#1a1a1a">Sıcak (4+ galibiyet)</option><option value="form_cold" style="background:#1a1a1a">Soğuk (4+ mağlubiyet)</option><option value="form_inconsistent" style="background:#1a1a1a">Tutarsız</option></select></div>
      <div><label style="${ls}">Dinlenme</label><select id="af_rest" style="${is};cursor:pointer"><option value="rest_normal" style="background:#1a1a1a">Normal (4-6 gün)</option><option value="rest_short" style="background:#1a1a1a">Kısa (2-3 gün)</option><option value="rest_long" style="background:#1a1a1a">Uzun (7+ gün)</option></select></div>
    </div>
    <div style="margin-bottom:14px">
      <label style="${ls}">Eksik Oyuncular (sakat/cezalı)</label>
      <div id="a_abs" style="margin-bottom:6px"></div>
      <button onclick="addAbs('a_abs')" style="padding:4px 12px;border-radius:8px;border:1px dashed rgba(255,255,255,.15);background:transparent;color:#888;font-size:11px;cursor:pointer">+ Eksik oyuncu ekle</button>
    </div>

    <div style="font-size:10px;color:#666;letter-spacing:1px;margin-bottom:6px;font-weight:600">BAHİS ORANLARI (bahis sitesinden gir)</div>
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:14px">
      <div><label style="${ls}">MS 1</label><input id="od_h" style="${is}" type="number" step="0.05" placeholder="1.85"></div>
      <div><label style="${ls}">MS X</label><input id="od_d" style="${is}" type="number" step="0.05" placeholder="3.50"></div>
      <div><label style="${ls}">MS 2</label><input id="od_a" style="${is}" type="number" step="0.05" placeholder="4.20"></div>
      <div><label style="${ls}">Ü 2.5</label><input id="od_o" style="${is}" type="number" step="0.05" placeholder="1.75"></div>
      <div><label style="${ls}">A 2.5</label><input id="od_u" style="${is}" type="number" step="0.05" placeholder="2.10"></div>
    </div>

    <div style="margin-bottom:14px"><label style="${ls}">BANKROLL (₺)</label><input id="mbr" style="${is};width:150px" type="number" value="1000"></div>

    <button onclick="submitManual()" style="width:100%;padding:13px;background:linear-gradient(135deg,#9c27b0,#ce93d8);color:#fff;border:none;border-radius:12px;font-size:13px;font-weight:800;letter-spacing:1px;cursor:pointer">ANALİZ ET →</button>

    <div style="margin-top:10px;font-size:10px;color:#666;line-height:1.5">
      💡 Skorları "2-0, 1-1, 3-1" formatında girin. Oranları bahis sitesinden olduğu gibi yazın.
      Faktörler otomatik olarak modelin güç parametrelerini ayarlar.
    </div>
  </div>`;
}

function parseScores(str){
  if(!str||!str.trim())return[];
  return str.split(',').map(s=>{
    const p=s.trim().split('-');
    if(p.length!==2)return null;
    const a=parseInt(p[0]),b=parseInt(p[1]);
    return isNaN(a)||isNaN(b)?null:[a,b];
  }).filter(x=>x!==null);
}

let _absCounter=0;
function addAbs(containerId){
  _absCounter++;
  const id='abs_'+_absCounter;
  const d=document.createElement('div');
  d.id=id;d.style.cssText='display:flex;gap:6px;align-items:center;margin-bottom:4px';
  d.innerHTML=`<select class="abs-sel" style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:7px 10px;color:#e0e0e0;font-size:12px;font-family:'JetBrains Mono',monospace;outline:none;cursor:pointer;flex:1"><option value="starter" style="background:#1a1a1a">İlk 11 oyuncu</option><option value="key_player" style="background:#1a1a1a">Yıldız oyuncu</option><option value="top_scorer" style="background:#1a1a1a">Gol kralı / forvet</option><option value="captain" style="background:#1a1a1a">Kaptan / lider</option><option value="goalkeeper" style="background:#1a1a1a">Kaleci</option><option value="bench" style="background:#1a1a1a">Yedek oyuncu</option></select><button onclick="document.getElementById('${id}').remove()" style="background:rgba(255,82,82,.1);border:1px solid rgba(255,82,82,.2);border-radius:6px;color:#ff5252;cursor:pointer;padding:4px 8px;font-size:11px">✕</button>`;
  $(containerId).appendChild(d);
}

function getAbsences(containerId){
  const els=$(containerId).querySelectorAll('.abs-sel');
  return Array.from(els).map(el=>({type:el.value}));
}

async function submitManual(){
  const data={
    home_team:$('mh').value||'Ev Sahibi',
    away_team:$('ma').value||'Deplasman',
    league_type:$('mlt').value,
    neutral:$('mn').value==='1',
    home_last_10:parseScores($('mh10').value),
    away_last_10:parseScores($('ma10').value),
    home_last_5_home:parseScores($('mh5h').value),
    away_last_5_away:parseScores($('ma5a').value),
    home_factors:[$('hf_mot').value,$('hf_form').value,$('hf_rest').value],
    away_factors:[$('af_mot').value,$('af_form').value,$('af_rest').value],
    home_absences:getAbsences('h_abs'),
    away_absences:getAbsences('a_abs'),
    odds:{},
    bankroll:parseFloat($('mbr').value)||1000,
  };
  const oh=parseFloat($('od_h').value);if(oh>1)data.odds.home=oh;
  const od=parseFloat($('od_d').value);if(od>1)data.odds.draw=od;
  const oa=parseFloat($('od_a').value);if(oa>1)data.odds.away=oa;
  const oo=parseFloat($('od_o').value);if(oo>1)data.odds.over25=oo;
  const ou=parseFloat($('od_u').value);if(ou>1)data.odds.under25=ou;

  const mr=$('manual-result');mr.style.display='block';
  mr.innerHTML='<div style="padding:20px;text-align:center"><div class="sp" style="margin:0 auto"></div><span style="font-size:12px;color:#888;margin-top:8px;display:block">Hesaplanıyor...</span></div>';

  try{
    const r=await fetch(API+'/analyze-manual',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||r.status);
    const d=await r.json();
    renderManualResult(d);
  }catch(e){
    mr.innerHTML=`<div class="panel"><b style="color:#ff9800">⚠️</b> ${e.message}</div>`;
  }
}

function renderManualResult(d){
  const mr=$('manual-result');
  const mks=d.markets||[];
  const mainMks=mks.filter(m=>!m.key.startsWith('cs_')&&!m.key.startsWith('iyms_'));
  const iyMks=mks.filter(m=>m.key.startsWith('iyms_'));
  const csMks=mks.filter(m=>m.key.startsWith('cs_'));
  const vbs=d.value_bets||[];
  const conf=d.confidence||0;
  const xg=d.expected_goals||{};

  mr.innerHTML=`<div class="panel" style="border-color:rgba(156,39,176,.2)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div>
        <div style="font-size:11px;color:#ce93d8;letter-spacing:2px;font-weight:600">MANUEL ANALİZ SONUCU</div>
        <h2 style="font-size:17px;color:#eee;margin-top:2px">${d.home_team} vs ${d.away_team}</h2>
      </div>
      <div style="text-align:center"><div class="m" style="font-size:20px;font-weight:800;color:${cc(conf)}">${conf}</div><div style="font-size:8px;color:#888">GÜVEN</div>${cb(conf,'50px')}</div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">
      ${[{n:d.home_team,s:d.home_strength,xg:xg.home,c:'#00e676'},{n:d.away_team,s:d.away_strength,xg:xg.away,c:'#42a5f5'}].map(t=>`
        <div style="background:rgba(255,255,255,.02);border-radius:10px;padding:10px;border:1px solid rgba(255,255,255,.05)">
          <div style="font-size:12px;font-weight:700;color:#e0e0e0;margin-bottom:4px">${t.n}</div>
          <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:3px">
            <div style="text-align:center"><div style="font-size:7px;color:#777">E.A</div><div class="m" style="font-size:11px;font-weight:800;color:${(t.s?.home_atk||1)>1?'#00e676':'#ff5252'}">${t.s?.home_atk||'?'}</div></div>
            <div style="text-align:center"><div style="font-size:7px;color:#777">E.D</div><div class="m" style="font-size:11px;font-weight:800;color:${(t.s?.home_def||1)<1?'#00e676':'#ff5252'}">${t.s?.home_def||'?'}</div></div>
            <div style="text-align:center"><div style="font-size:7px;color:#777">D.A</div><div class="m" style="font-size:11px;font-weight:800;color:${(t.s?.away_atk||1)>1?'#00e676':'#ff5252'}">${t.s?.away_atk||'?'}</div></div>
            <div style="text-align:center"><div style="font-size:7px;color:#777">D.D</div><div class="m" style="font-size:11px;font-weight:800;color:${(t.s?.away_def||1)<1?'#00e676':'#ff5252'}">${t.s?.away_def||'?'}</div></div>
            <div style="text-align:center"><div style="font-size:7px;color:#777">xG</div><div class="m" style="font-size:11px;font-weight:800;color:${t.c}">${t.xg}</div></div>
          </div>
        </div>`).join('')}
    </div>

    ${vbs.length?`<div style="background:linear-gradient(135deg,rgba(0,200,83,.08),rgba(0,200,83,.02));border:1px solid rgba(0,200,83,.15);border-radius:10px;padding:10px 14px;margin-bottom:12px">
      <div style="font-size:10px;color:#00e676;letter-spacing:2px;margin-bottom:6px;font-weight:700">🎯 VALUE BETLER (${vbs.length})</div>
      ${vbs.map(v=>`<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0">
        <span style="color:#e0e0e0;font-weight:600">${v.label} @${v.odds.toFixed(2)}</span>
        <div style="display:flex;gap:4px;align-items:center">${bg(v.value_pct/100)}<span class="m" style="color:#00e676;font-size:11px;font-weight:700">${v.bet}₺</span>
        ${v.reason_flags.map(r=>`<span style="font-size:7px;color:#888;background:rgba(255,255,255,.04);padding:1px 4px;border-radius:3px">${r}</span>`).join('')}</div>
      </div>`).join('')}
    </div>`:`<div style="background:rgba(255,255,255,.02);border-radius:10px;padding:10px;margin-bottom:12px;text-align:center;color:#888;font-size:11px">Value bet bulunamadı. Oranları kontrol edin veya farklı bir maç deneyin.</div>`}

    <div style="font-size:10px;color:#888;letter-spacing:1px;margin-bottom:4px;font-weight:600">📋 TÜM MARKETLER</div>
    <table><thead><tr><th style="text-align:left">MARKET</th><th style="text-align:center">MODEL</th><th style="text-align:center">ORAN</th><th style="text-align:center">ADİL</th><th style="text-align:center">DEĞER</th><th style="text-align:right">BAHİS</th></tr></thead>
    <tbody>${mainMks.map(m=>`<tr style="background:${m.is_value?'rgba(0,200,83,.06)':'rgba(255,255,255,.01)'}">
      <td style="color:${m.is_value?'#e0e0e0':'#888'};font-weight:${m.is_value?600:400}">${m.label}</td>
      <td class="m" style="text-align:center;color:${m.is_value?'#00e676':'#999'};font-weight:700">${m.prob}%</td>
      <td class="m" style="text-align:center;color:#ccc">${m.odds.toFixed(2)} <span class="tag ${m.odds_source==='manual'?'tg':'ty'}" style="font-size:7px">${m.odds_source==='manual'?'EL':'M'}</span></td>
      <td class="m" style="text-align:center;color:#555;font-size:10px">${m.model_fair_odds?.toFixed(2)||'-'}</td>
      <td style="text-align:center">${m.is_value?bg(m.value_pct/100):'<span style="color:#444;font-size:8px">-</span>'}</td>
      <td class="m" style="text-align:right;color:${m.is_value?'#00e676':'#555'};font-weight:700">${m.is_value?m.bet+'₺':'-'}</td>
    </tr>`).join('')}</tbody></table>

    ${csMks.length?`<div style="margin-top:10px;font-size:10px;color:#888;letter-spacing:1px;margin-bottom:4px;font-weight:600">🎯 SKOR TAHMİNİ</div><div style="display:flex;flex-wrap:wrap;gap:3px">${csMks.map(m=>`<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.04);border-radius:8px;padding:5px 8px;text-align:center"><div class="m" style="font-size:11px;font-weight:800;color:#ccc">${m.label.replace('Skor ','')}</div><div style="font-size:7px;color:#888">${m.prob}%</div></div>`).join('')}</div>`:''}

    ${iyMks.length?`<div style="margin-top:10px;font-size:10px;color:#888;letter-spacing:1px;margin-bottom:4px;font-weight:600">🔄 İY/MS</div><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:3px">${iyMks.map(m=>`<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.04);border-radius:8px;padding:5px;text-align:center"><div class="m" style="font-size:10px;font-weight:700;color:#ccc">${m.label.replace('İY/MS ','')}</div><div style="font-size:8px;color:#888">${m.prob}%</div></div>`).join('')}</div>`:''}

    <div style="margin-top:10px;padding:8px;background:rgba(255,215,0,.04);border-radius:8px;border:1px solid rgba(255,215,0,.1)"><div style="font-size:9px;color:#999;line-height:1.5"><b style="color:#ffd600">📐</b> Dixon-Coles Poisson | Joint İY/MS | Adaptif Kelly | Min edge %2 | Cap %5${d.neutral?' | <b style="color:#42a5f5">🌍 Nötr saha</b>':''}<br><span style="color:#555">⚠️ Bu bir analiz aracıdır, bahis önerisi değildir. Oranlar elle girilmiştir.</span></div></div>
  </div>`;
}

function renderStats(d){const e=$('stats');if(!d){e.style.display='none';return}e.style.display='grid';const os=d.odds_source==='The Odds API';e.innerHTML=[{l:'Geçmiş',v:d.hist_matches,c:'#42a5f5'},{l:'Yaklaşan',v:d.upcoming,c:'#ccc'},{l:'Value',v:d.value_bets_count,c:d.value_bets_count>0?'#00e676':'#ff5252'},{l:'Oranlar',v:os?'GERÇEK':'YOK',c:os?'#00e676':'#ff5252'},{l:'Sezon',v:d.season||'?',c:'#888'}].map(s=>`<div style="background:rgba(255,255,255,.02);border-radius:10px;padding:8px;text-align:center;border:1px solid rgba(255,255,255,.04)"><div style="font-size:9px;color:#777;margin-bottom:2px">${s.l}</div><div class="m" style="font-size:14px;font-weight:800;color:${s.c}">${s.v}</div></div>`).join('');
  const t=$('tools');t.style.display='flex';t.innerHTML=`<a href="/export/json" class="btn bi" style="text-decoration:none;color:#42a5f5">📥 JSON</a><a href="/export/csv" class="btn bi" style="text-decoration:none;color:#42a5f5">📥 CSV</a><button class="btn bi" onclick="runBT()" style="color:#ce93d8">🧪 Backtest</button>`}

function renderTopBets(bets){const e=$('topbets');if(!bets||!bets.length){e.style.display='none';return}e.style.display='block';e.style.cssText='display:block;background:linear-gradient(135deg,rgba(0,200,83,.08),rgba(66,165,245,.04));border:1px solid rgba(0,200,83,.15);border-radius:12px;padding:12px 14px;margin-bottom:16px';e.innerHTML=`<div style="font-size:10px;color:#00e676;letter-spacing:2px;margin-bottom:8px;font-weight:700">🎯 VALUE BETLER (${bets.length}) <span style="color:#666;font-weight:400">min %2 edge | Kelly cap %5 | max 2/maç | günlük cap %15</span></div><div style="display:flex;flex-wrap:wrap;gap:5px">${bets.slice(0,10).map(b=>`<div style="background:rgba(0,0,0,.3);border-radius:8px;padding:5px 8px;font-size:10px;display:flex;align-items:center;gap:4px"><span style="color:#aaa">${b.match.substring(0,25)}</span><span class="m" style="color:#00e676;font-weight:700">${b.market} @${b.odds}</span>${bg(b.value_pct/100)}${b.confidence?`<span class="m" style="font-size:8px;color:${cc(b.confidence)}">${b.confidence}</span>`:''}</div>`).join('')}</div>`}

function renderList(an){const e=$('list');if(!an||!an.length){e.innerHTML='<div style="text-align:center;padding:30px;color:#666;font-size:12px">Maç bulunamadı.</div>';return}e.innerHTML=an.map((a,i)=>{const mks=a.markets||[];const top5=mks.filter(m=>["home","draw","away","over25","btts_yes"].includes(m.key));const bestV=mks.find(m=>m.is_value);const dt=a.date?new Date(a.date).toLocaleDateString('tr-TR',{day:'numeric',month:'short',weekday:'short'}):'';const isR=a.odds_source==='real';const conf=a.confidence||0;return`<div class="card ${SEL===i?'csel':''}" onclick="sel(${i})"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><span style="font-size:10px;color:#888">${dt}${a.matchday?' • H'+a.matchday:''}</span><div style="display:flex;gap:4px;align-items:center">${a.neutral?'<span class="tag tn">NÖTR</span>':''}<span class="tag ${isR?'tg':'ty'}">${isR?'GERÇEK':'MODEL'}</span><span class="m" style="font-size:10px;color:${cc(conf)};background:rgba(255,255,255,.04);padding:2px 6px;border-radius:6px">🎯${conf}</span></div></div><div style="display:flex;justify-content:center;align-items:center;gap:10px;margin-bottom:8px"><div style="text-align:right;flex:1"><span style="font-size:14px;font-weight:700;color:#e8e8e8">${a.home_team}</span><div style="font-size:9px;color:#666">E:${a.home_str?.home_atk||'?'}/${a.home_str?.home_def||'?'} D:${a.home_str?.away_atk||'?'}/${a.home_str?.away_def||'?'}</div></div><span style="font-size:11px;color:#444;padding:2px 6px;border:1px solid rgba(255,255,255,.06);border-radius:6px">vs</span><div style="text-align:left;flex:1"><span style="font-size:14px;font-weight:700;color:#e8e8e8">${a.away_team}</span><div style="font-size:9px;color:#666">E:${a.away_str?.home_atk||'?'}/${a.away_str?.home_def||'?'} D:${a.away_str?.away_atk||'?'}/${a.away_str?.away_def||'?'}</div></div></div>${cb(conf)}<div class="mg" style="margin-top:6px">${top5.map(m=>`<div class="mc ${m.is_value?'mv':'mn'}"><div style="font-size:8px;color:#777">${m.label}</div><div class="m" style="font-size:12px;font-weight:700;color:${m.is_value?'#00e676':'#aaa'}">${m.odds.toFixed(2)}</div><div style="font-size:8px;color:${m.is_value?'#00c853':'#555'}">${m.prob}%</div></div>`).join('')}</div>${bestV?`<div style="display:flex;justify-content:space-between;align-items:center;padding-top:6px;border-top:1px solid rgba(255,255,255,.05)"><span style="font-size:10px;color:#999">🎯 <b style="color:#e0e0e0">${bestV.label}</b> @${bestV.odds.toFixed(2)}</span><div style="display:flex;gap:3px;align-items:center">${bg(bestV.value_pct/100)}${(bestV.reason_flags||[]).slice(0,2).map(r=>`<span style="font-size:7px;color:#888;background:rgba(255,255,255,.04);padding:1px 4px;border-radius:3px">${r}</span>`).join('')}</div></div>`:''}</div>`}).join('')}

function renderDetail(a){const e=$('detail');if(!a){e.innerHTML='';return}const mks=a.markets||[];const mainMks=mks.filter(m=>!m.key.startsWith('cs_')&&!m.key.startsWith('iyms_')&&!m.key.startsWith('corner_'));const csMks=mks.filter(m=>m.key.startsWith('cs_'));const iyMks=mks.filter(m=>m.key.startsWith('iyms_'));const crMks=mks.filter(m=>m.key.startsWith('corner_'));const bks=a.bookmakers||[];const conf=a.confidence||0;
e.innerHTML=`<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><div><div style="font-size:11px;color:#00e676;letter-spacing:2px;font-weight:600">DETAYLI ANALİZ</div><h2 style="font-size:17px;color:#eee;margin-top:2px">${a.home_team} vs ${a.away_team}</h2></div><div style="text-align:center"><div class="m" style="font-size:20px;font-weight:800;color:${cc(conf)}">${conf}</div><div style="font-size:8px;color:#888">GÜVEN</div>${cb(conf,'50px')}</div></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">${[{n:a.home_team,s:a.home_str,xg:a.home_xg,c:'#00e676'},{n:a.away_team,s:a.away_str,xg:a.away_xg,c:'#42a5f5'}].map(t=>`<div style="background:rgba(255,255,255,.02);border-radius:10px;padding:10px;border:1px solid rgba(255,255,255,.05)"><div style="font-size:12px;font-weight:700;color:#e0e0e0;margin-bottom:4px">${t.n}</div><div style="display:grid;grid-template-columns:repeat(5,1fr);gap:3px"><div style="text-align:center"><div style="font-size:7px;color:#777">E.A</div><div class="m" style="font-size:11px;font-weight:800;color:${(t.s?.home_atk||1)>1?'#00e676':'#ff5252'}">${t.s?.home_atk||'?'}</div></div><div style="text-align:center"><div style="font-size:7px;color:#777">E.D</div><div class="m" style="font-size:11px;font-weight:800;color:${(t.s?.home_def||1)<1?'#00e676':'#ff5252'}">${t.s?.home_def||'?'}</div></div><div style="text-align:center"><div style="font-size:7px;color:#777">D.A</div><div class="m" style="font-size:11px;font-weight:800;color:${(t.s?.away_atk||1)>1?'#00e676':'#ff5252'}">${t.s?.away_atk||'?'}</div></div><div style="text-align:center"><div style="font-size:7px;color:#777">D.D</div><div class="m" style="font-size:11px;font-weight:800;color:${(t.s?.away_def||1)<1?'#00e676':'#ff5252'}">${t.s?.away_def||'?'}</div></div><div style="text-align:center"><div style="font-size:7px;color:#777">xG</div><div class="m" style="font-size:11px;font-weight:800;color:${t.c}">${t.xg}</div></div></div><div style="font-size:8px;color:#666;margin-top:3px">${t.s?.n||0} maç (E:${t.s?.home_n||0} D:${t.s?.away_n||0})</div></div>`).join('')}</div>
<div style="font-size:10px;color:#888;letter-spacing:1px;margin-bottom:4px;font-weight:600">📋 MARKETLER</div>
<table><thead><tr><th style="text-align:left">MARKET</th><th style="text-align:center">MODEL</th><th style="text-align:center">ORAN</th><th style="text-align:center">ADİL</th><th style="text-align:center">TİP</th><th style="text-align:center">DEĞER</th><th style="text-align:right">BAHİS</th></tr></thead>
<tbody>${mainMks.map(m=>{const mc=m.market_class||'informational';return`<tr style="background:${m.is_value?'rgba(0,200,83,.06)':'rgba(255,255,255,.01)'}"><td style="color:${m.is_value?'#e0e0e0':'#888'};font-weight:${m.is_value?600:400}">${m.label}</td><td class="m" style="text-align:center;color:${m.is_value?'#00e676':'#999'};font-weight:700">${m.prob}%</td><td class="m" style="text-align:center;color:#ccc">${m.odds.toFixed(2)} <span class="tag ${m.odds_source==='real'?'tg':'ty'}" style="font-size:7px">${m.odds_source==='real'?'G':'M'}</span></td><td class="m" style="text-align:center;color:#555;font-size:10px">${m.model_fair_odds?.toFixed(2)||'-'}</td><td style="text-align:center"><span class="tag ${MC_C[mc]||'ty'}" style="font-size:7px">${MC_L[mc]||mc}</span></td><td style="text-align:center">${m.is_value?bg(m.value_pct/100):m.value_eligible?'<span style="color:#555;font-size:8px"><%2</span>':'<span style="color:#444;font-size:8px">-</span>'}</td><td class="m" style="text-align:right;color:${m.is_value?'#00e676':'#555'};font-weight:700">${m.is_value?m.bet+'₺':'-'}</td></tr>`}).join('')}</tbody></table>
${crMks.length?`<div style="margin-top:10px;font-size:10px;color:#888;letter-spacing:1px;margin-bottom:4px;font-weight:600">⛳ KORNER <span class="tag te" style="font-size:7px">DENEYSEL</span></div><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:3px">${crMks.map(m=>`<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.04);border-radius:8px;padding:5px;text-align:center"><div style="font-size:9px;color:#ccc">${m.label.replace('Korner ','')}</div><div class="m" style="font-size:8px;color:#888">${m.prob}%</div></div>`).join('')}</div>`:''}
${csMks.length?`<div style="margin-top:10px;font-size:10px;color:#888;letter-spacing:1px;margin-bottom:4px;font-weight:600">🎯 SKOR</div><div style="display:flex;flex-wrap:wrap;gap:3px">${csMks.map(m=>`<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.04);border-radius:8px;padding:5px 8px;text-align:center"><div class="m" style="font-size:11px;font-weight:800;color:#ccc">${m.label.replace('Skor ','')}</div><div style="font-size:7px;color:#888">${m.prob}%</div></div>`).join('')}</div>`:''}
${iyMks.length?`<div style="margin-top:10px;font-size:10px;color:#888;letter-spacing:1px;margin-bottom:4px;font-weight:600">🔄 İY/MS <span style="color:#555;font-size:8px">(joint model)</span></div><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:3px">${iyMks.map(m=>`<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.04);border-radius:8px;padding:5px;text-align:center"><div class="m" style="font-size:10px;font-weight:700;color:#ccc">${m.label.replace('İY/MS ','')}</div><div style="font-size:8px;color:#888">${m.prob}%</div></div>`).join('')}</div>`:''}
${bks.length?`<div style="margin-top:12px;background:rgba(255,255,255,.02);border-radius:10px;padding:12px;border:1px solid rgba(255,255,255,.06)"><div style="font-size:10px;color:#42a5f5;letter-spacing:2px;margin-bottom:8px;font-weight:700">📊 BAHİS SİTELERİ (${bks.length})</div><table><thead><tr style="color:#666;font-size:8px"><th style="text-align:left">SİTE</th><th>1</th><th>X</th><th>2</th><th>Ü2.5</th><th>A2.5</th><th>MRJ</th></tr></thead><tbody>${bks.map(bk=>{const o=bk.markets;const mg=o.home&&o.draw&&o.away?((1/o.home+1/o.draw+1/o.away-1)*100).toFixed(1):'?';return`<tr><td><span style="color:#ccc;font-weight:600;font-size:11px">${bk.name}</span></td><td class="m" style="text-align:center;color:#ccc">${o.home?.toFixed(2)||'-'}</td><td class="m" style="text-align:center;color:#ccc">${o.draw?.toFixed(2)||'-'}</td><td class="m" style="text-align:center;color:#ccc">${o.away?.toFixed(2)||'-'}</td><td class="m" style="text-align:center;color:#ccc">${o.over25?.toFixed(2)||'-'}</td><td class="m" style="text-align:center;color:#ccc">${o.under25?.toFixed(2)||'-'}</td><td class="m" style="text-align:center;font-weight:600;color:${parseFloat(mg)<5?'#00e676':parseFloat(mg)<8?'#ffd600':'#ff5252'}">%${mg}</td></tr>`}).join('')}</tbody></table></div>`:''}
<div style="margin-top:10px;padding:8px;background:rgba(255,215,0,.04);border-radius:8px;border:1px solid rgba(255,215,0,.1)"><div style="font-size:9px;color:#999;line-height:1.5"><b style="color:#ffd600">v8:</b> Dixon-Coles | Joint İY/MS | Adaptif Kelly (conf×edge×mkt) | Cap %5 | Min edge %2 | Max 2/maç | Günlük %15${a.neutral?' | <b style="color:#42a5f5">🌍 Nötr saha</b>':''}<br><span style="color:#555">⚠️ Analiz aracıdır, bahis önerisi değildir.</span></div></div></div>`}

async function runBT(){const e=$('btresult');e.style.display='block';e.innerHTML='<div style="padding:20px;text-align:center"><div class="sp" style="margin:0 auto"></div><p class="m" style="margin-top:10px;color:#888;font-size:11px">Backtest çalışıyor...</p></div>';try{const r=await fetch(API+'/backtest/'+CUR);const d=await r.json();if(d.error){e.innerHTML=`<div class="panel"><b style="color:#ff9800">⚠️</b> ${d.error}</div>`;return}const mr=d.market_results||{};const cal=d.calibration||[];e.innerHTML=`<div class="panel"><div style="font-size:11px;color:#ce93d8;letter-spacing:2px;font-weight:600;margin-bottom:10px">🧪 BACKTEST SONUÇLARI — ${d.league_name||CUR}</div><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px"><div style="background:rgba(255,255,255,.02);border-radius:8px;padding:8px;text-align:center;border:1px solid rgba(255,255,255,.04)"><div style="font-size:9px;color:#777">Maç</div><div class="m" style="font-size:16px;font-weight:800;color:#42a5f5">${d.matches_tested}</div></div><div style="background:rgba(255,255,255,.02);border-radius:8px;padding:8px;text-align:center;border:1px solid rgba(255,255,255,.04)"><div style="font-size:9px;color:#777">Brier Score</div><div class="m" style="font-size:16px;font-weight:800;color:${d.avg_brier_score<0.22?'#00e676':d.avg_brier_score<0.25?'#ffd600':'#ff5252'}">${d.avg_brier_score}</div></div><div style="background:rgba(255,255,255,.02);border-radius:8px;padding:8px;text-align:center;border:1px solid rgba(255,255,255,.04)"><div style="font-size:9px;color:#777">Kalite</div><div style="font-size:14px;font-weight:800;color:${d.model_quality==='good'?'#00e676':d.model_quality==='fair'?'#ffd600':'#ff5252'}">${d.model_quality}</div></div></div><div style="font-size:10px;color:#888;margin-bottom:6px;font-weight:600">Market Bazlı</div><table><thead><tr><th style="text-align:left">Market</th><th>Hit%</th><th>Ort.Pred%</th><th>Brier</th><th>N</th></tr></thead><tbody>${Object.entries(mr).map(([k,v])=>`<tr><td style="color:#ccc">${k}</td><td class="m" style="text-align:center;color:#ccc">${v.hit_rate}%</td><td class="m" style="text-align:center;color:#999">${v.avg_predicted_prob}%</td><td class="m" style="text-align:center;color:${v.brier_score<0.22?'#00e676':'#ffd600'}">${v.brier_score}</td><td class="m" style="text-align:center;color:#666">${v.n}</td></tr>`).join('')}</tbody></table>${cal.length?`<div style="font-size:10px;color:#888;margin:10px 0 6px;font-weight:600">Calibration</div><table><thead><tr><th>Aralık</th><th>Tahmin</th><th>Gerçek</th><th>Fark</th><th>N</th></tr></thead><tbody>${cal.map(c=>`<tr><td style="color:#ccc">${c.range}</td><td class="m" style="text-align:center;color:#999">${c.predicted}%</td><td class="m" style="text-align:center;color:#ccc">${c.actual}%</td><td class="m" style="text-align:center;color:${c.gap<5?'#00e676':c.gap<10?'#ffd600':'#ff5252'}">${c.gap}%</td><td class="m" style="text-align:center;color:#666">${c.n}</td></tr>`).join('')}</tbody></table>`:''}</div>`}catch(err){e.innerHTML=`<div class="panel"><b style="color:#ff9800">⚠️</b> ${err.message}</div>`}}

function sel(i){SEL=SEL===i?null:i;renderList(DATA?.analyses||[]);renderDetail(SEL!==null?DATA.analyses[SEL]:null)}
async function sw(c){CUR=c;SEL=null;MODE='api';$('btresult').style.display='none';$('manual-panel').style.display='none';$('manual-result').style.display='none';renderTabs();await load()}
async function load(){$('loading').style.display='flex';$('list').innerHTML='';$('detail').innerHTML='';try{const r=await fetch(API+'/analyze/'+CUR+'?bankroll=1000&days=14');if(!r.ok){const t=await r.json().catch(()=>({}));throw new Error(t.detail||r.status)}DATA=await r.json();setStatus(true,`${ALL[CUR]?.n} | ${DATA.hist_matches} maç | ${DATA.upcoming} yaklaşan | ${DATA.odds_source} | sezon ${DATA.season}`);renderStats(DATA);renderTopBets(DATA.top_value_bets||[]);renderList(DATA.analyses||[])}catch(e){setStatus(false,e.message);DATA=null;$('list').innerHTML=`<div style="background:rgba(255,152,0,.06);border:1px solid rgba(255,152,0,.15);border-radius:10px;padding:14px;font-size:12px;color:#ccc;line-height:1.8"><b style="color:#ff9800">⚠️</b> ${e.message}</div>`}$('loading').style.display='none'}
renderTabs();load();
</script></body></html>"""
