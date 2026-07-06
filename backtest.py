"""Backtest v8.6 - Monte Carlo bankroll sim + sensitivity analizi eklendi"""
import math,random,logging
from strength_model import team_strength
from probability_model import match_probs,estimate_rho
from config import MIN_EDGE, MIN_CONFIDENCE, TRADABLE_MARKETS, KELLY_HARD_CAP, EXPANSION_MARKETS, EXPANSION_MIN_BETS, EXPANSION_MIN_ROI
from settlement import settle_bet
import config

logger = logging.getLogger(__name__)

SIMULATED_MARGIN_BASE=0.93
SIMULATED_MARGIN_NOISE=0.03

# ─── YENİ METRİK FONKSİYONLARI ───────────────────────────────────────────────

def compute_log_loss(records: list) -> float:
    """
    Binary log loss: her tahmin için gerçekleşen sonucun log olasılığı.
    records: [{"prob": float, "outcome": int(1=kazandı, 0=kaybetti)}, ...]

    Formül: -(1/N) * Σ [y*log(p) + (1-y)*log(1-p)]
    Kırpma (eps=1e-15): log(0)'dan kaçınmak için.
    Düşük = iyi (0.0 mükemmel, üst sınır ~log(2)≈0.693 rastgele tahmin için).
    """
    if not records:
        return None
    eps = 1e-15
    total = 0.0
    for r in records:
        p   = max(eps, min(1 - eps, r["prob"]))
        oc  = r["outcome"]
        total += -(oc * math.log(p) + (1 - oc) * math.log(1 - p))
    return round(total / len(records), 4)


def compute_rps(matches_1x2: list) -> float:
    """
    Ranked Probability Score — 1X2 için standart metrik.
    Brier Score'dan üstün: sıralı kategorilerdeki uzaklığı cezalandırır
    (1 tahmin edip 2 gelmesi, X tahmin edip 2 gelmesinden daha kötü).

    matches_1x2: [{"home": float, "draw": float, "away": float,
                   "result": "home"|"draw"|"away"}, ...]

    Formül (K=3 sınıf):
      RPS = (1/(K-1)) * Σ_{k=1}^{K-1} (F_k - G_k)^2
      F_k = kümülatif tahmin CDF'si
      G_k = kümülatif gerçek CDF'si (step function)

    Sınırlar: 0.0 (mükemmel) → 1.0 (en kötü).
    Tipik futbol modeli: ~0.20
    """
    if not matches_1x2:
        return None
    total = 0.0
    for m in matches_1x2:
        p_h = m["home"]; p_d = m["draw"]; p_a = m["away"]
        res = m["result"]
        # Kümülatif tahmin: F1=p_home, F2=p_home+p_draw
        f1 = p_h
        f2 = p_h + p_d
        # Kümülatif gerçek (step function)
        if res == "home":
            g1, g2 = 1.0, 1.0
        elif res == "draw":
            g1, g2 = 0.0, 1.0
        else:  # away
            g1, g2 = 0.0, 0.0
        total += 0.5 * ((f1 - g1) ** 2 + (f2 - g2) ** 2)
    return round(total / len(matches_1x2), 4)


def compute_calibration_curve(records: list) -> list:
    """
    10 eşit genişlikli bin'de kalibrasyon eğrisi.
    records: [{"prob": float, "outcome": int}, ...]

    Her bin için:
      bin       → "0-10%" … "90-100%"
      predicted → ortalama tahmin edilen olasılık (%)
      actual    → gerçek isabet oranı (%)
      n         → tahmin sayısı
      gap       → |predicted - actual| (pp)
      over/under → model aşırı mı yoksa düşük mü tahmin ediyor

    Tüm 10 bin döner (boş bin için n=0, değerler null).
    """
    bins = [{"bin": f"{i*10}-{(i+1)*10}%",
             "pred_sum": 0.0, "actual_sum": 0,
             "n": 0} for i in range(10)]

    for r in records:
        p  = r["prob"]
        oc = r["outcome"]
        idx = min(9, int(p * 10))   # [0,1) → 0..9
        bins[idx]["pred_sum"]    += p
        bins[idx]["actual_sum"]  += oc
        bins[idx]["n"]           += 1

    result = []
    for b in bins:
        n = b["n"]
        if n == 0:
            result.append({"bin": b["bin"], "predicted": None,
                           "actual": None, "n": 0, "gap": None,
                           "direction": None})
            continue
        pred   = round(b["pred_sum"] / n * 100, 1)
        actual = round(b["actual_sum"] / n * 100, 1)
        gap    = round(abs(pred - actual), 1)
        direction = "overfit" if pred > actual else ("underfit" if pred < actual else "calibrated")
        result.append({"bin": b["bin"], "predicted": pred,
                       "actual": actual, "n": n,
                       "gap": gap, "direction": direction})
    return result

def monte_carlo_sim(bets_log: list, initial_bankroll: float, n_sim: int = 1000) -> dict:
    """
    1000 kez bets_log'u shuffle ederek bankroll path simüle eder.
    Her bet'in kazanç çarpanı (return multiplier) korunur; sadece sıra değişir.
    Ruin: bankroll, başlangıcın %10'unun altına düşmesi.

    Döner: p5_final, p95_final, median_final, ruin_prob
    """
    if not bets_log:
        return {"p5_final": round(initial_bankroll, 2),
                "p95_final": round(initial_bankroll, 2),
                "median_final": round(initial_bankroll, 2),
                "ruin_prob": 0.0, "n_sim": n_sim, "n_bets": 0}

    # Bet başına kesirsel çarpan: bankroll *= mult
    multipliers = []
    for b in bets_log:
        br_before = b["bankroll"] - b["pnl"]
        if br_before <= 0:
            continue
        frac = b["stake"] / br_before
        ret  = b["pnl"] / b["stake"]   # (odds-1) kazandıysa, -1 kaybettiyse
        mult = max(0.0, 1.0 + frac * ret)
        multipliers.append(mult)

    if not multipliers:
        return {"p5_final": round(initial_bankroll, 2),
                "p95_final": round(initial_bankroll, 2),
                "median_final": round(initial_bankroll, 2),
                "ruin_prob": 0.0, "n_sim": n_sim, "n_bets": 0}

    ruin_threshold = initial_bankroll * 0.10
    finals = []
    ruin_count = 0

    mults_copy = multipliers[:]
    for _ in range(n_sim):
        random.shuffle(mults_copy)
        br = initial_bankroll
        ruined = False
        for m in mults_copy:
            br *= m
            if br <= ruin_threshold:
                ruined = True
                br = 0.0
                break
        if ruined:
            ruin_count += 1
        finals.append(round(br, 2))

    finals.sort()
    p5_idx     = max(0, int(n_sim * 0.05) - 1)
    p95_idx    = min(n_sim - 1, int(n_sim * 0.95))
    median_idx = n_sim // 2

    return {
        "p5_final":     finals[p5_idx],
        "p95_final":    finals[p95_idx],
        "median_final": finals[median_idx],
        "ruin_prob":    round(ruin_count / n_sim * 100, 1),
        "n_sim":        n_sim,
        "n_bets":       len(multipliers),
    }


def sensitivity_analysis(potential_bets: list, initial_bankroll: float,
                          edge_thresholds: list = None) -> list:
    """
    MIN_EDGE'i [0.03, 0.05, 0.07, 0.10] ile test eder.
    potential_bets: backtest loop'undan toplanan tüm fırsat listesi
      Her eleman: [{"prob","odds","edge","won","data_n"}, ...] (bir maç için sıralı liste)
    1 bet/maç kuralı korunur: eşiği geçen ilk market seçilir (orijinal sıra).
    Stake: sabit bankroll * Kelly (karşılaştırılabilirlik için running bankroll kullanılmaz).
    """
    if edge_thresholds is None:
        edge_thresholds = [0.03, 0.05, 0.07, 0.10]

    results = []
    for min_edge in edge_thresholds:
        total_staked = 0.0
        total_profit = 0.0
        n_bets = 0

        for match_candidates in potential_bets:
            for cand in match_candidates:
                if cand["edge"] < min_edge or cand["edge"] > 0.40:
                    continue
                kf = _backtest_kelly(cand["prob"], cand["odds"], initial_bankroll, cand["data_n"])
                stake = initial_bankroll * kf
                if stake <= 0:
                    break
                pnl = stake * (cand["odds"] - 1) if cand["won"] else -stake
                total_staked += stake
                total_profit += pnl
                n_bets += 1
                break  # 1 bet/maç

        if n_bets == 0:
            results.append({"min_edge": min_edge, "roi": None, "n_bets": 0})
        else:
            roi   = round(total_profit / initial_bankroll * 100, 2)
            yield_ = round(total_profit / total_staked * 100, 2) if total_staked > 0 else 0
            results.append({"min_edge": min_edge, "roi": roi, "yield": yield_, "n_bets": n_bets})

    return results


def _backtest_kelly(prob:float,odds:float,bankroll:float,data_n:int)->float:
    """
    Backtest için basitleştirilmiş adaptif Kelly.
    Confidence, mevcut eğitim verisi büyüklüğüne göre ölçeklenir.
    """
    b=odds-1
    if b<=0 or prob<=0:return 0.0
    edge=prob*odds-1
    if edge<MIN_EDGE or edge>0.40:return 0.0
    raw_f=max(0.0,(b*prob-(1-prob))/b)
    # Veri miktarına bağlı confidence: 100 maç = %70 güven, 300+ maç = %90
    conf_mult=min(0.9,0.40+0.50*min(1.0,data_n/300))
    if edge>0.15:edge_mult=0.12
    elif edge>0.10:edge_mult=0.18
    else:edge_mult=0.20
    adj=raw_f*edge_mult*conf_mult
    adj=adj**0.75
    return min(adj,KELLY_HARD_CAP)

def run_backtest(all_matches:list,avg_h:float,avg_a:float,
                 warmup:int=50,avg_corner:float=10.0,initial_bankroll:float=1000,
                 auto_disable:bool=True,historical_odds:dict=None,
                 run_monte_carlo:bool=False,run_sensitivity:bool=False)->dict:

    if len(all_matches)<warmup+10:
        logger.warning("backtest insufficient_matches available=%d needed=%d", len(all_matches), warmup+10)
        return{"error":"Yeterli maç yok","matches_needed":warmup+10,"matches_available":len(all_matches)}

    logger.info("backtest start total_matches=%d warmup=%d", len(all_matches), warmup)

    market_stats={k:{"correct":0,"total":0,"prob_sum":0,"brier_sum":0,"bets_won":0,"bets_total":0,"staked":0,"profit":0}
        for k in["home","draw","away","over25","under25","btts_yes","btts_no","dc_1x","dc_x2","dc_12"]}

    cal_buckets={f"{i*10}-{(i+1)*10}":{"predicted":0,"actual":0,"count":0} for i in range(10)}
    total_predictions=0;total_brier=0

    # ── yeni metrik toplayıcılar ──────────────────────────────────────────────
    _ll_records: list  = []   # log_loss için: {"prob", "outcome"}
    _rps_records: list = []   # RPS için:      {"home","draw","away","result"}
    _cal_records: list = []   # calibration_curve için: {"prob", "outcome"}
    # ─────────────────────────────────────────────────────────────────────────

    bankroll=initial_bankroll
    bankroll_history=[bankroll]
    peak=bankroll;max_dd=0.0
    cur_streak=0;max_streak=0
    total_staked=0.0;total_profit=0.0
    bets_log=[]
    real_odds_count=0;total_bet_count=0
    if historical_odds is None:historical_odds={}
    potential_bets=[]  # sensitivity analizi için: [[{prob,odds,edge,won,data_n},...],...]

    # Sadece warmup penceresinden rho tahmin et (look-ahead bias engellenir)
    rho=estimate_rho(all_matches[:warmup])

    for idx in range(warmup,len(all_matches)):
        train=all_matches[:idx];test=all_matches[idx]
        hname=test["ht"];aname=test["at"]
        ah=test["hs"];aa=test["as"]
        if ah is None or aa is None:continue

        hs=team_strength(hname,train,avg_h,avg_a)
        as_=team_strength(aname,train,avg_h,avg_a)
        hxg=max(hs["home_atk"]*as_["away_def"]*avg_h,0.1)
        axg=max(as_["away_atk"]*hs["home_def"]*avg_a,0.1)
        probs=match_probs(hxg,axg,avg_corner,avg_h+avg_a,rho=rho)

        if ah>aa:ar="home"
        elif ah==aa:ar="draw"
        else:ar="away"
        tg=ah+aa;ao25=1 if tg>=3 else 0;abtts=1 if ah>0 and aa>0 else 0

        # ── RPS kaydı (1X2 her maç için bir kez) ────────────────────────────
        _rps_records.append({"home":probs["home_win"],"draw":probs["draw"],
                              "away":probs["away_win"],"result":ar})

        bets=[
            ("home","home_win",settle_bet("home",ah,aa)),
            ("draw","draw",settle_bet("draw",ah,aa)),
            ("away","away_win",settle_bet("away",ah,aa)),
            ("over25","over25",settle_bet("over25",ah,aa)),
            ("under25","under25",settle_bet("under25",ah,aa)),
            ("btts_yes","btts_yes",abtts==1),("btts_no","btts_no",abtts==0),
            ("dc_1x","dc_1x",settle_bet("dc_1x",ah,aa)),
            ("dc_x2","dc_x2",settle_bet("dc_x2",ah,aa)),
            ("dc_12","dc_12",settle_bet("dc_12",ah,aa)),
        ]

        # Tradable ve expansion marketler için ayrı bahis slotları:
        # Tradable (home/draw/away/over25/under25) → 1 bet/maç
        # Expansion (btts/dc) → kendi 1 bet/maç slotları (bağımsız değerlendirme)
        match_bet_taken=False
        match_bet_taken_exp=False
        match_candidates=[]  # sensitivity adayları (sadece tradable)

        for mkt,pk,won in bets:
            prob=probs.get(pk,0)
            if prob<=0:continue
            oc=1 if won else 0
            s=market_stats[mkt]
            s["total"]+=1;s["correct"]+=oc;s["prob_sum"]+=prob;s["brier_sum"]+=(prob-oc)**2

            if mkt in("home","draw","away","over25","under25"):
                bi=min(9,int(prob*10));bk=f"{bi*10}-{(bi+1)*10}"
                cal_buckets[bk]["predicted"]+=prob;cal_buckets[bk]["actual"]+=oc;cal_buckets[bk]["count"]+=1
                total_brier+=(prob-oc)**2;total_predictions+=1
                _ll_records.append({"prob":prob,"outcome":oc})
                _cal_records.append({"prob":prob,"outcome":oc})

            is_exp=mkt in EXPANSION_MARKETS
            is_trad=mkt in TRADABLE_MARKETS

            if not is_trad and not is_exp:continue

            # Sensitivity: sadece tradable marketler için
            if run_sensitivity and is_trad:
                match_key_s=f"{hname} vs {aname}"
                h_mkt_odds=historical_odds.get(match_key_s,{}).get(mkt,0)
                so_s=h_mkt_odds if h_mkt_odds and h_mkt_odds>1.0 else (round(1/prob*SIMULATED_MARGIN_BASE,2) if prob>0.01 else 50.0)
                match_candidates.append({"prob":prob,"odds":so_s,"edge":prob*so_s-1,"won":won,"data_n":idx})

            # Bet slot kontrolü (tradable ve expansion ayrı)
            if is_exp and match_bet_taken_exp:continue
            if is_trad and match_bet_taken:continue

            match_key=f"{hname} vs {aname}"
            hist_mkt_odds=historical_odds.get(match_key,{}).get(mkt,0)
            if hist_mkt_odds and hist_mkt_odds>1.0:
                so=hist_mkt_odds;odds_src="real"
            else:
                so=round(1/prob*SIMULATED_MARGIN_BASE,2) if prob>0.01 else 50.0;odds_src="simulated"
            edge=prob*so-1
            if edge>=MIN_EDGE and bankroll>0:
                kf=_backtest_kelly(prob,so,bankroll,idx)
                stake=max(1,round(bankroll*kf)) if kf>0 else 0
                if stake==0:continue
                s["bets_total"]+=1;s["staked"]+=stake;total_staked+=stake
                if is_exp:match_bet_taken_exp=True
                else:match_bet_taken=True
                total_bet_count+=1
                if odds_src=="real":real_odds_count+=1
                if won:
                    pnl=stake*(so-1);s["bets_won"]+=1;cur_streak=0
                else:
                    pnl=-stake;cur_streak+=1;max_streak=max(max_streak,cur_streak)
                s["profit"]+=pnl;total_profit+=pnl
                bankroll=max(0,bankroll+pnl)
                bets_log.append({"match":match_key,"market":mkt,"odds":so,"odds_source":odds_src,
                    "prob":round(prob,4),"edge":round(edge,4),"stake":stake,
                    "won":won,"pnl":round(pnl,2),"bankroll":round(bankroll,2),
                    "market_type":"expansion" if is_exp else "tradable"})

        if run_sensitivity and match_candidates:
            potential_bets.append(match_candidates)
        bankroll_history.append(round(bankroll,2))
        if bankroll>peak:peak=bankroll
        if peak>0:
            dd=(peak-bankroll)/peak
            max_dd=max(max_dd,dd)

    # Market bazlı performans
    results={}
    market_performance=[]
    disabled_by_backtest=[]
    enabled_by_backtest=[]

    for mkt,s in market_stats.items():
        n=s["total"]
        if n==0:continue
        r={"hit_rate":round(s["correct"]/n*100,1),"avg_predicted_prob":round(s["prob_sum"]/n*100,1),
           "brier_score":round(s["brier_sum"]/n,4),"n":n}
        bt=s["bets_total"]
        mkt_roi=0
        if bt>0:
            r["bets_placed"]=bt;r["bets_won"]=s["bets_won"]
            r["bet_hit_rate"]=round(s["bets_won"]/bt*100,1)
            r["staked"]=round(s["staked"],2);r["profit"]=round(s["profit"],2)
            mkt_roi=round(s["profit"]/s["staked"]*100,1) if s["staked"]>0 else 0
            r["market_roi"]=mkt_roi
            r["market_yield"]=round(s["profit"]/bt,2) if bt>0 else 0
        results[mkt]=r

        is_exp=mkt in EXPANSION_MARKETS
        mp={"market":mkt,"bets":bt,"roi":mkt_roi,"hit_rate":r["hit_rate"],
            "profit":round(s["profit"],2),
            "status":"expansion_candidate" if is_exp else "active"}

        if bt>=5 and mkt_roi<0 and not is_exp and mkt not in config.CORE_MARKETS:
            # Tradable market kötü performans → kapat (core marketler korunur)
            mp["status"]="disabled"
            disabled_by_backtest.append(mkt)
        elif is_exp and bt>=EXPANSION_MIN_BETS and mkt_roi>EXPANSION_MIN_ROI:
            # Expansion market iyi performans → tradable'a geç
            mp["status"]="enabled"
            enabled_by_backtest.append(mkt)

        market_performance.append(mp)

    # ROI < 0 tradable marketleri otomatik kapat (core marketler korunur)
    if auto_disable and disabled_by_backtest:
        from disabled_markets_store import save_disabled_markets
        for mkt in disabled_by_backtest:
            if mkt in config.CORE_MARKETS:
                continue
            config.DISABLED_MARKETS.add(mkt)
            config.TRADABLE_MARKETS.discard(mkt)
        config.DISABLED_MARKETS -= config.CORE_MARKETS  # güvenlik katmanı
        save_disabled_markets(config.DISABLED_MARKETS)
        logger.info("backtest auto_disabled markets=%s", disabled_by_backtest)

    # ROI > 0 expansion marketleri otomatik etkinleştir
    if auto_disable and enabled_by_backtest:
        from disabled_markets_store import save_disabled_markets
        for mkt in enabled_by_backtest:
            config.DISABLED_MARKETS.discard(mkt)
            config.TRADABLE_MARKETS.add(mkt)
        save_disabled_markets(config.DISABLED_MARKETS)
        logger.info("backtest auto_enabled markets=%s", enabled_by_backtest)

    calibration=[]
    for bk,b in cal_buckets.items():
        if b["count"]>=5:
            calibration.append({"range":bk+"%","predicted":round(b["predicted"]/b["count"]*100,1),
                "actual":round(b["actual"]/b["count"]*100,1),"n":b["count"],
                "gap":round(abs(b["predicted"]/b["count"]-b["actual"]/b["count"])*100,1)})

    avg_brier=round(total_brier/total_predictions,4) if total_predictions>0 else None
    roi=round(total_profit/initial_bankroll*100,2) if initial_bankroll>0 else 0
    yld=round(total_profit/total_staked*100,2) if total_staked>0 else 0

    bh=bankroll_history
    if len(bh)>100:
        step=len(bh)//100;bh=bh[::step]+[bh[-1]]

    real_cov=round(real_odds_count/total_bet_count*100,1) if total_bet_count>0 else 0
    odds_mode="real" if real_cov>50 else "simulated"

    # Live readiness
    live_reasons=[]
    strong_markets=[]
    weak_markets=[]

    if total_bet_count<20:live_reasons.append("insufficient_bets")
    if roi<=0:live_reasons.append("negative_roi")
    if max_dd>30:live_reasons.append("excessive_drawdown")
    if avg_brier and avg_brier>0.25:live_reasons.append("poor_brier_score")

    avg_cal_gap=sum(c.get("gap",0) for c in calibration)/max(len(calibration),1) if calibration else 99
    if avg_cal_gap>10:live_reasons.append("poor_calibration")

    for mp in market_performance:
        mkt=mp["market"]
        if mp["bets"]>=5 and mp["roi"]>0:strong_markets.append(mkt)
        elif mp["bets"]>=5 and mp["roi"]<0:weak_markets.append(mkt)

    live_ready=len(live_reasons)==0

    # ── yeni metrikler ────────────────────────────────────────────────────────
    log_loss_val      = compute_log_loss(_ll_records)
    rps_val           = compute_rps(_rps_records)
    calibration_curve = compute_calibration_curve(_cal_records)

    mc_result   = monte_carlo_sim(bets_log, initial_bankroll) if run_monte_carlo else None
    sens_result = sensitivity_analysis(potential_bets, initial_bankroll) if run_sensitivity else None
    # ─────────────────────────────────────────────────────────────────────────

    logger.info(
        "backtest done total_bets=%d roi=%.2f yield=%.2f brier=%s log_loss=%s rps=%s live_ready=%s",
        total_bet_count, roi, yld, avg_brier, log_loss_val, rps_val, live_ready,
    )

    return{
        "matches_tested":total_predictions//3,"warmup_matches":warmup,"total_predictions":total_predictions,
        "avg_brier_score":avg_brier,
        "initial_bankroll":initial_bankroll,"final_bankroll":round(bankroll,2),
        "total_staked":round(total_staked,2),"total_profit":round(total_profit,2),
        "roi":roi,"yield":yld,
        "max_drawdown":round(max_dd*100,2),"longest_losing_streak":max_streak,
        "odds_mode":odds_mode,
        "real_odds_coverage_pct":real_cov,
        "live_ready":live_ready,
        "live_ready_reasons":live_reasons,
        "strong_markets":strong_markets,
        "weak_markets":weak_markets,
        "bankroll_history":bh,
        "bets_log":bets_log[-100:],
        "market_results":results,
        "market_performance":sorted(market_performance,key=lambda x:x["roi"],reverse=True),
        "disabled_by_backtest":disabled_by_backtest,
        "enabled_by_backtest":enabled_by_backtest,
        "calibration":calibration,
        "log_loss":log_loss_val,
        "rps":rps_val,
        "calibration_curve":calibration_curve,
        "model_quality":"good" if avg_brier and avg_brier<0.22 else "fair" if avg_brier and avg_brier<0.25 else "needs_improvement",
        **({"monte_carlo": mc_result} if mc_result is not None else {}),
        **({"sensitivity": sens_result} if sens_result is not None else {}),
    }
