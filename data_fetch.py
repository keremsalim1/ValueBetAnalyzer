"""Veri çekme katmanı"""
import json
import logging
import time
from datetime import datetime
from typing import Dict, Optional
import httpx
from fastapi import HTTPException
from config import FD_KEY, ODDS_KEY, FD_BASE, ODDS_BASE, CACHE_TTL, SEASON

logger = logging.getLogger(__name__)
_cache:Dict[str,tuple]={}

async def fd_fetch(ep:str, params:dict=None)->dict:
    ck=f"fd:{ep}:{json.dumps(params or{},sort_keys=True)}"
    if ck in _cache:
        t,d=_cache[ck]
        if(datetime.now()-t).total_seconds()<CACHE_TTL:
            logger.debug("cache_hit endpoint=%s", ep)
            return d
    logger.debug("cache_miss endpoint=%s", ep)
    if not FD_KEY:raise HTTPException(500,"FOOTBALL_DATA_API_KEY eksik (.env)")
    t0=time.perf_counter()
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.get(f"{FD_BASE}{ep}",headers={"X-Auth-Token":FD_KEY},params=params)
    elapsed=round((time.perf_counter()-t0)*1000)
    if r.status_code==429:raise HTTPException(429,"Rate limit: 10 istek/dk")
    if r.status_code==403:raise HTTPException(403,"Bu lig ücretsiz planda erişilemez")
    if r.status_code!=200:raise HTTPException(r.status_code,f"football-data.org: {r.text[:200]}")
    logger.info("fd_fetch endpoint=%s status=%d elapsed_ms=%d", ep, r.status_code, elapsed)
    d=r.json();_cache[ck]=(datetime.now(),d);return d

async def odds_fetch(sport_key:str, markets:str="h2h,totals")->list:
    if not sport_key or not ODDS_KEY:return[]
    ck=f"odds:{sport_key}:{markets}"
    if ck in _cache:
        t,d=_cache[ck]
        if(datetime.now()-t).total_seconds()<CACHE_TTL:
            logger.debug("cache_hit sport=%s markets=%s", sport_key, markets)
            return d
    logger.debug("cache_miss sport=%s markets=%s", sport_key, markets)
    t0=time.perf_counter()
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.get(f"{ODDS_BASE}/sports/{sport_key}/odds",
            params={"apiKey":ODDS_KEY,"regions":"eu","markets":markets,"oddsFormat":"decimal"})
    elapsed=round((time.perf_counter()-t0)*1000)
    if r.status_code!=200:
        logger.warning("odds_fetch failed sport=%s status=%d", sport_key, r.status_code)
        return[]
    logger.info("odds_fetch sport=%s events=%d elapsed_ms=%d", sport_key, len(r.json()), elapsed)
    d=r.json();_cache[ck]=(datetime.now(),d);return d

def clear_cache():
    _cache.clear()

async def _fetch_season_matches(league_fd:str, season:int, limit:int)->list:
    """Belirli bir sezon için tamamlanmış maçları çek."""
    try:
        fd=await fd_fetch(f"/competitions/{league_fd}/matches",{"status":"FINISHED","limit":limit,"season":season})
    except HTTPException:
        return []
    hist=[]
    for m in fd.get("matches",[]):
        ft=m.get("score",{}).get("fullTime",{})
        h=ft.get("home");a=ft.get("away")
        if h is not None and a is not None:
            hist.append({"ht":m["homeTeam"]["name"],"at":m["awayTeam"]["name"],"hs":h,"as":a,"date":m.get("utcDate","")})
    return hist

async def get_historical_matches(league_fd:str, limit:int=500)->list:
    """
    Mevcut sezon maçlarını çek. 30'dan az maç varsa (sezon başı)
    önceki sezonu da ekle — zaman ağırlıklı decay eski maçları doğal olarak küçültür.
    """
    hist=await _fetch_season_matches(league_fd,SEASON,limit)
    if len(hist)<30:
        logger.info("historical_matches league=%s season=%d count=%d — önceki sezon ekleniyor", league_fd, SEASON, len(hist))
        prev=await _fetch_season_matches(league_fd,SEASON-1,limit)
        hist=prev+hist  # eskiden yeniye sıralı kalır, decay doğru çalışır
    logger.info("historical_matches league=%s total_matches=%d", league_fd, len(hist))
    return hist

async def get_upcoming_matches(league_fd:str, days:int=14)->list:
    from datetime import timedelta
    now_iso=datetime.utcnow().isoformat()+"Z"
    cut_iso=(datetime.utcnow()+timedelta(days=days)).isoformat()+"Z"
    fd=await fd_fetch(f"/competitions/{league_fd}/matches",{"status":"SCHEDULED","limit":200,"season":SEASON})
    return[m for m in fd.get("matches",[]) if now_iso<=m.get("utcDate","")<=cut_iso]
