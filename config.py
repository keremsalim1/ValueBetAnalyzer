"""Sabitler ve lig tanımları"""
import os
import json as _json
import logging
from datetime import datetime
from dotenv import load_dotenv


# ─── LOGGING SETUP ────────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Her log satırını tek satır JSON olarak yazar."""
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts":     self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":  record.levelname,
            "module": record.name,
            "msg":    record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return _json.dumps(obj, ensure_ascii=False)

def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:          # zaten kurulmuşsa tekrar ekleme
        return
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)

setup_logging()

# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()

VERSION="8.4"

FD_KEY=os.getenv("FOOTBALL_DATA_API_KEY","").strip()
ODDS_KEY=os.getenv("ODDS_API_KEY","").strip()
APIFOOTBALL_KEY=os.getenv("APIFOOTBALL_KEY","").strip()   # api-sports.io — gerçek xG + sakatlık
RAPIDAPI_XG_KEY=os.getenv("RAPIDAPI_XG_KEY","").strip() or None  # ExpectedScore xG via RapidAPI
ODDSPAPI_KEY=os.getenv("ODDSPAPI_KEY","").strip() or None  # oddspapi.io → gerçek Pinnacle line
FD_BASE="https://api.football-data.org/v4"
ODDS_BASE="https://api.the-odds-api.com/v4"

# OddsPapi sabitleri
ODDSPAPI_DAILY_LIMIT=25
ODDSPAPI_TOURNAMENT_MAP={
    "PL":17,"PD":8,"BL1":35,"SA":23,"FL1":34,"DED":320,"PPL":238,"CL":7,"EL":679
}

# Otomatik sezon: Ağustos'tan itibaren yeni sezon
def current_season()->int:
    now=datetime.now()
    return now.year if now.month>=8 else now.year-1

SEASON=current_season()

# Model parametreleri
MIN_EDGE=0.05
KELLY_HARD_CAP=0.025
SHRINK_N=10
STRENGTH_CAP=(0.4,2.5)
DECAY_HALF_LIFE=15
CACHE_TTL=600

# xG blend parametreleri
XG_BLEND_RAPIDAPI=0.65   # real_rapidapi: 0.65 × rapidapi + 0.35 × model
XG_MIN_MATCHES=5         # bu altında real xG kullanma
XG_JACCARD_MIN=0.6       # takım isim eşleşme eşiği

# Risk limitleri
DAILY_RISK_CAP=0.08
WEEKLY_RISK_CAP=0.20
MIN_CONFIDENCE=55
MAX_CORRELATED_BETS=1

# Canlı mod kilidi
REAL_BETTING_MODE=False

# Filtre parametreleri
MIN_ODDS=1.70
MAX_ODDS=2.50
REQUIRE_STEAM_ALIGNMENT=False
MAX_BETS_PER_DAY=3
BACKTEST_MIN_BETS=50
CLV_POSITIVE_RATE_MIN=0.55

# Lig tanımları
LEAGUES={
    "PL": {"name":"Premier League","flag":"🏴","fd":"PL","odds":"soccer_epl","type":"league","avg_h":1.55,"avg_a":1.20,"avg_corner":10.5},
    "PD": {"name":"La Liga","flag":"🇪🇸","fd":"PD","odds":"soccer_spain_la_liga","type":"league","avg_h":1.45,"avg_a":1.10,"avg_corner":9.8},
    "BL1":{"name":"Bundesliga","flag":"🇩🇪","fd":"BL1","odds":"soccer_germany_bundesliga","type":"league","avg_h":1.65,"avg_a":1.35,"avg_corner":10.2},
    "SA": {"name":"Serie A","flag":"🇮🇹","fd":"SA","odds":"soccer_italy_serie_a","type":"league","avg_h":1.40,"avg_a":1.15,"avg_corner":10.0},
    "FL1":{"name":"Ligue 1","flag":"🇫🇷","fd":"FL1","odds":"soccer_france_ligue_one","type":"league","avg_h":1.40,"avg_a":1.05,"avg_corner":9.5},
    "DED":{"name":"Eredivisie","flag":"🇳🇱","fd":"DED","odds":"soccer_netherlands_eredivisie","type":"league","avg_h":1.80,"avg_a":1.45,"avg_corner":10.3},
    "PPL":{"name":"Primeira Liga","flag":"🇵🇹","fd":"PPL","odds":"soccer_portugal_primeira_liga","type":"league","avg_h":1.45,"avg_a":1.05,"avg_corner":9.6},
    "CL": {"name":"Şampiyonlar Ligi","flag":"⭐","fd":"CL","odds":"soccer_uefa_champs_league","type":"cup","avg_h":1.35,"avg_a":1.05,"avg_corner":9.8,"neutral":False},
    "EL": {"name":"UEFA Avrupa Ligi","flag":"🟠","fd":"EL","odds":"soccer_uefa_europa_league","type":"cup","avg_h":1.40,"avg_a":1.10,"avg_corner":9.5,"neutral":False},
    "UECL":{"name":"Konferans Ligi","flag":"🔵","fd":"UECL","odds":"soccer_uefa_europa_conference_league","type":"cup","avg_h":1.50,"avg_a":1.15,"avg_corner":9.2,"neutral":False},
    "WC": {"name":"Dünya Kupası 2026","flag":"🌍","fd":"WC","odds":"soccer_fifa_world_cup","type":"cup","avg_h":1.20,"avg_a":1.00,"avg_corner":9.0,"neutral":True},
}

# Market sınıfları
CORE_MARKETS={"home","draw","away","over25","under25"}   # asla disable edilemez
TRADABLE_MARKETS=set(CORE_MARKETS)
INFORMATIONAL_MARKETS=set()
_BASE_DISABLED={"over15","over35","btts_yes","btts_no","dc_1x","dc_x2","dc_12","ht_home","ht_draw","ht_away"}

# Expansion markets: varsayılan olarak kapalı, backtest ROI > 0 ve n_bets >= 20 ise
# otomatik olarak TRADABLE_MARKETS'a geçer (disabled_by_backtest'in tersi).
EXPANSION_MARKETS={"btts_yes","btts_no","dc_1x","dc_x2","dc_12"}

# Backtest auto-enable eşikleri (expansion marketler için)
EXPANSION_MIN_BETS=20
EXPANSION_MIN_ROI=0.0   # > 0 olmalı

from disabled_markets_store import load_disabled_markets
DISABLED_MARKETS=_BASE_DISABLED | load_disabled_markets()
# Core marketler ASLA disable edilemez; sadece expansion/diğer marketler çıkarılabilir
DISABLED_MARKETS -= CORE_MARKETS
TRADABLE_MARKETS -= (DISABLED_MARKETS - CORE_MARKETS)

def get_market_class(key:str)->str:
    if key in DISABLED_MARKETS:return "disabled"
    if key in TRADABLE_MARKETS:return "tradable"
    if key.startswith("corner_"):return "disabled"
    if key.startswith("iyms_"):return "disabled"
    if key.startswith("cs_"):return "disabled"
    return "disabled"
