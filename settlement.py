"""Bahis sonuçlandırma"""
import logging

logger = logging.getLogger(__name__)

def settle_bet(market_key:str, home_goals:int, away_goals:int,
               ht_home:int=None, ht_away:int=None)->bool:
    total=home_goals+away_goals
    settlements={
        "home":         home_goals>away_goals,
        "draw":         home_goals==away_goals,
        "away":         home_goals<away_goals,
        "over25":       total>=3,
        "under25":      total<3,
        "over15":       total>=2,
        "under15":      total<2,
        "over35":       total>=4,
        "under35":      total<4,
        "btts_yes":     home_goals>0 and away_goals>0,
        "btts_no":      not(home_goals>0 and away_goals>0),
        "dc_1x":        home_goals>=away_goals,
        "dc_x2":        home_goals<=away_goals,
        "dc_12":        home_goals!=away_goals,
    }
    if market_key in settlements:
        return settlements[market_key]
    # İlk yarı marketleri yarı skor gerektirir
    if market_key in("ht_home","ht_draw","ht_away"):
        if ht_home is None or ht_away is None:
            raise ValueError(f"{market_key} sonuçlandırmak için ilk yarı skoru (ht_home, ht_away) gereklidir")
        if market_key=="ht_home": return ht_home>ht_away
        if market_key=="ht_draw": return ht_home==ht_away
        if market_key=="ht_away": return ht_home<ht_away
    raise ValueError(f"Desteklenmeyen market: {market_key}")
