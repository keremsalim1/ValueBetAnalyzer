"""
API-Football v3 entegrasyonu — gerçek xG + sakatlık/ceza verisi
https://v3.football.api-sports.io
.env: APIFOOTBALL_KEY=xxx

Ücretsiz plan: 100 istek/gün
Strateji:
  - Takım istatistikleri (xG dahil) 12 saat cache
  - Sakatlık listesi 1 saat cache
  - Her maç analizi için yalnızca gerekli takımlar çekilir
  - API anahtarı yoksa veya limit dolmuşsa mevcut model devreye girer
"""
import os, math, logging
from datetime import datetime, timedelta
from typing import Optional
import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

AF_KEY = os.getenv("APIFOOTBALL_KEY", "").strip()
AF_BASE = "https://v3.football.api-sports.io"

# Lig ID eşleştirmesi: football-data.org kodu → API-Football league_id
AF_LEAGUE_IDS = {
    "PL":   39,
    "PD":   140,
    "BL1":  78,
    "SA":   135,
    "FL1":  61,
    "DED":  88,
    "PPL":  94,
    "CL":   2,
    "EL":   3,
    "UECL": 848,
    "WC":   1,
}

# ─── CACHE ───────────────────────────────────────────────────────────────────
_cache: dict = {}   # key → (timestamp, data)

def _cached(key: str, ttl: int):
    """Cache hit döndürür, yoksa None."""
    if key in _cache:
        ts, data = _cache[key]
        if (datetime.utcnow() - ts).total_seconds() < ttl:
            return data
    return None

def _set_cache(key: str, data):
    _cache[key] = (datetime.utcnow(), data)

# ─── DÜŞÜK SEVİYE FETCH ──────────────────────────────────────────────────────
async def _af_get(endpoint: str, params: dict) -> Optional[dict]:
    """API-Football'a GET isteği. Hata durumunda None döner (crash yok)."""
    if not AF_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{AF_BASE}/{endpoint}",
                headers={"x-apisports-key": AF_KEY},
                params=params,
            )
        if r.status_code == 429:
            logger.warning("apifootball rate_limit endpoint=%s", endpoint)
            return None   # günlük limit doldu
        if r.status_code != 200:
            logger.warning("apifootball error endpoint=%s status=%d", endpoint, r.status_code)
            return None
        logger.debug("apifootball ok endpoint=%s", endpoint)
        return r.json()
    except Exception as exc:
        logger.warning("apifootball exception endpoint=%s error=%s", endpoint, exc)
        return None

# ─── TAKIM ADI EŞLEŞTİRME ────────────────────────────────────────────────────
def _normalize(s: str) -> str:
    for r in ["fc ", "cf ", "ac ", "sc ", " fc", " cf", " ac", " sc"]:
        s = s.lower().replace(r, " ")
    return s.replace(".", " ").replace("-", " ").replace("  ", " ").strip()

def _name_sim(a: str, b: str) -> float:
    a, b = _normalize(a), _normalize(b)
    if a == b:
        return 1.0
    wa = {w for w in a.split() if len(w) >= 3}
    wb = {w for w in b.split() if len(w) >= 3}
    if not wa or not wb:
        return 0.0
    j = len(wa & wb) / len(wa | wb)
    sub = 0.2 if (a in b or b in a) else 0.0
    return min(1.0, j + sub)

def _best_team_match(target: str, candidates: list) -> Optional[dict]:
    """
    candidates: [{"id": 33, "name": "Manchester United"}, ...]
    En yüksek Jaccard benzerliğini bul.
    """
    best_sim = 0.0
    best = None
    for c in candidates:
        s = _name_sim(target, c["name"])
        if s > best_sim:
            best_sim = s
            best = c
    return best if best_sim >= 0.4 else None

# ─── TAKIM LİSTESİ ───────────────────────────────────────────────────────────
async def get_league_teams(league_code: str, season: int) -> list:
    """
    Bir ligdeki tüm takımları çeker: [{"id": 33, "name": "Manchester United"}, ...]
    Cache: 24 saat (takım listesi nadiren değişir)
    """
    league_id = AF_LEAGUE_IDS.get(league_code)
    if not league_id:
        return []
    ck = f"teams:{league_code}:{season}"
    cached = _cached(ck, 86400)
    if cached is not None:
        return cached

    data = await _af_get("teams", {"league": league_id, "season": season})
    if not data:
        return []
    teams = [
        {"id": t["team"]["id"], "name": t["team"]["name"]}
        for t in data.get("response", [])
    ]
    _set_cache(ck, teams)
    return teams

# ─── TAKIM xG İSTATİSTİKLERİ ─────────────────────────────────────────────────
async def get_team_xg_stats(team_id: int, league_code: str, season: int) -> Optional[dict]:
    """
    Takımın sezon agregat istatistiklerini çeker.
    Döner:
      xg_for_home, xg_for_away     → hücum xG ortalaması (maç başı)
      xg_against_home, xg_against_away → savunma xG ortalaması
      goals_for_home, goals_for_away   → gol bazlı fallback
      games_home, games_away           → oynanan maç sayısı
      xg_available                     → True ise gerçek xG var
    Cache: 12 saat
    """
    league_id = AF_LEAGUE_IDS.get(league_code)
    if not league_id:
        return None
    ck = f"teamstats:{team_id}:{league_code}:{season}"
    cached = _cached(ck, 43200)
    if cached is not None:
        return cached

    data = await _af_get("teams/statistics", {
        "team": team_id, "league": league_id, "season": season
    })
    if not data or not data.get("response"):
        return None

    resp = data["response"]
    fixtures = resp.get("fixtures", {})
    goals   = resp.get("goals", {})
    xg_raw  = resp.get("expected_goals")  # None ise ücretsiz planda yok

    games_home = fixtures.get("played", {}).get("home", 0) or 1
    games_away = fixtures.get("played", {}).get("away", 0) or 1

    # Gol ortalamaları (her zaman var)
    gf_h = float(goals.get("for",  {}).get("average", {}).get("home", 0) or 0)
    gf_a = float(goals.get("for",  {}).get("average", {}).get("away", 0) or 0)
    ga_h = float(goals.get("against", {}).get("average", {}).get("home", 0) or 0)
    ga_a = float(goals.get("against", {}).get("average", {}).get("away", 0) or 0)

    # xG ortalamaları (ücretli planda gelir, ücretsizde None)
    xg_available = False
    xg_for_home = xg_for_away = xg_against_home = xg_against_away = None

    if xg_raw:
        try:
            xg_f_h = float(xg_raw.get("for",     {}).get("home", 0) or 0)
            xg_f_a = float(xg_raw.get("for",     {}).get("away", 0) or 0)
            xg_a_h = float(xg_raw.get("against", {}).get("home", 0) or 0)
            xg_a_a = float(xg_raw.get("against", {}).get("away", 0) or 0)
            if xg_f_h > 0 or xg_f_a > 0:
                # Kümülatif → maç başı ortalamaya çevir
                xg_for_home     = round(xg_f_h / games_home, 3)
                xg_for_away     = round(xg_f_a / games_away, 3)
                xg_against_home = round(xg_a_h / games_home, 3)
                xg_against_away = round(xg_a_a / games_away, 3)
                xg_available    = True
        except Exception:
            pass

    result = {
        "team_id":           team_id,
        "games_home":        games_home,
        "games_away":        games_away,
        "xg_available":      xg_available,
        "xg_for_home":       xg_for_home,
        "xg_for_away":       xg_for_away,
        "xg_against_home":   xg_against_home,
        "xg_against_away":   xg_against_away,
        "goals_for_home":    gf_h,
        "goals_for_away":    gf_a,
        "goals_against_home":ga_h,
        "goals_against_away":ga_a,
    }
    _set_cache(ck, result)
    return result

# ─── YAKIN MAÇLAR (fixture_id almak için) ────────────────────────────────────
async def get_upcoming_fixture_ids(league_code: str, season: int, days: int = 14) -> list:
    """
    Yaklaşan maçları fixture_id ile döner.
    [{"fixture_id": 868077, "home_team": "Manchester United",
      "away_team": "Arsenal", "date": "2024-12-08T15:00:00+00:00"}, ...]
    Cache: 2 saat
    """
    league_id = AF_LEAGUE_IDS.get(league_code)
    if not league_id:
        return []
    ck = f"fixtures_upcoming:{league_code}:{season}"
    cached = _cached(ck, 7200)
    if cached is not None:
        return cached

    data = await _af_get("fixtures", {
        "league": league_id, "season": season, "next": 30
    })
    if not data:
        return []

    cutoff = datetime.utcnow() + timedelta(days=days)
    result = []
    for f in data.get("response", []):
        fix  = f.get("fixture", {})
        date_str = fix.get("date", "")
        try:
            fix_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00").replace("+00:00", ""))
            if fix_dt > cutoff:
                continue
        except Exception:
            pass
        teams = f.get("teams", {})
        result.append({
            "fixture_id": fix.get("id"),
            "home_team":  teams.get("home", {}).get("name", ""),
            "away_team":  teams.get("away", {}).get("name", ""),
            "date":       date_str,
        })
    _set_cache(ck, result)
    return result

# ─── SAKATLIKA / CEZA LİSTESİ ────────────────────────────────────────────────

# Oyuncu pozisyonu → ABSENCE_IMPACT kategorisi
_POS_MAP = {
    "Goalkeeper":  "goalkeeper",
    "Defender":    "starter",
    "Midfielder":  "starter",
    "Attacker":    "starter",
    "Forward":     "starter",
}

async def get_fixture_injuries(fixture_id: int) -> list:
    """
    Belirli bir maç için sakatlık/ceza listesi.
    [{"player": "Haaland", "team": "Manchester City",
      "position": "Attacker", "type": "Injury", "reason": "Hamstring",
      "absence_type": "starter"}, ...]
    Cache: 1 saat
    """
    if not fixture_id:
        return []
    ck = f"injuries:{fixture_id}"
    cached = _cached(ck, 3600)
    if cached is not None:
        return cached

    data = await _af_get("injuries", {"fixture": fixture_id})
    if not data:
        return []

    result = []
    for item in data.get("response", []):
        player  = item.get("player", {})
        team    = item.get("team", {})
        pos     = player.get("type", "Midfielder")   # "type" = pozisyon
        absence = _POS_MAP.get(pos, "starter")
        result.append({
            "player":       player.get("name", ""),
            "team":         team.get("name", ""),
            "team_id":      team.get("id"),
            "position":     pos,
            "type":         item.get("type", "Injury"),   # "Injury" | "Suspension"
            "reason":       item.get("reason", ""),
            "absence_type": absence,
        })
    _set_cache(ck, result)
    return result

# ─── ANA FONKSİYONLAR (backend'in kullanacağı) ───────────────────────────────

async def enrich_match(
    home_name: str,
    away_name: str,
    league_code: str,
    season: int,
    fixture_id: Optional[int] = None,
) -> dict:
    """
    Bir maç için gerçek xG + sakatlık verisini birleştirip döner.

    xG kaynak önceliği:
      1. real_rapidapi (xg_provider — ExpectedScore API)
      2. real (API-Football Pro+ xG)
      3. af_goals (API-Football ücretsiz gol ort.)
      4. model (model xG)

    Dönen dict:
      home_xg_stats    → AF takım istatistikleri (veya None)
      away_xg_stats    → AF takım istatistikleri (veya None)
      home_injuries    → sakatlık listesi
      away_injuries    → sakatlık listesi
      home_team_id     → eşleşen AF takım ID
      away_team_id     → eşleşen AF takım ID
      xg_available     → AF Pro+ xG mevcut mu
      af_available     → API-Football bağlantısı başarılı mı
      rapidapi_available → ExpectedScore xG mevcut mu
      rapidapi_hxg     → ev takımı xg_for ortalaması (rapidapi)
      rapidapi_axg     → deplasman takımı xg_for ortalaması (rapidapi)
    """
    base = {
        "af_available":     False,
        "xg_available":     False,
        "rapidapi_available": False,
        "rapidapi_hxg":     None,
        "rapidapi_axg":     None,
        "home_xg_stats":    None,
        "away_xg_stats":    None,
        "home_injuries":    [],
        "away_injuries":    [],
        "home_team_id":     None,
        "away_team_id":     None,
    }

    # ─── 1. ExpectedScore (RapidAPI) xG — öncelikli kaynak ──────────────────
    try:
        from xg_provider import get_team_xg
        h_rapi, a_rapi = await get_team_xg(home_name, league_code, season), \
                          await get_team_xg(away_name, league_code, season)
        if h_rapi and a_rapi:
            base["rapidapi_available"] = True
            base["rapidapi_hxg"] = h_rapi["xg_for"]
            base["rapidapi_axg"] = a_rapi["xg_for"]
            logger.debug("xg_provider hit home=%s away=%s hxg=%.2f axg=%.2f",
                         home_name, away_name, h_rapi["xg_for"], a_rapi["xg_for"])
    except Exception as exc:
        logger.warning("enrich_match rapidapi_error home=%s error=%s", home_name, exc)

    # ─── 2. API-Football xG + sakatlık ──────────────────────────────────────
    if not AF_KEY:
        return base

    teams = await get_league_teams(league_code, season)
    if not teams:
        return base

    base["af_available"] = True

    h_match = _best_team_match(home_name, teams)
    a_match = _best_team_match(away_name, teams)

    h_stats = a_stats = None
    if h_match:
        h_stats = await get_team_xg_stats(h_match["id"], league_code, season)
    if a_match:
        a_stats = await get_team_xg_stats(a_match["id"], league_code, season)

    injuries = []
    if fixture_id:
        injuries = await get_fixture_injuries(fixture_id)

    h_id = h_match["id"] if h_match else None
    a_id = a_match["id"] if a_match else None

    home_inj = [i for i in injuries if i.get("team_id") == h_id]
    away_inj = [i for i in injuries if i.get("team_id") == a_id]

    xg_ok = bool(h_stats and h_stats.get("xg_available") and
                  a_stats and a_stats.get("xg_available"))

    base.update({
        "xg_available":  xg_ok,
        "home_team_id":  h_id,
        "away_team_id":  a_id,
        "home_xg_stats": h_stats,
        "away_xg_stats": a_stats,
        "home_injuries": home_inj,
        "away_injuries": away_inj,
    })
    return base


def blend_xg(model_hxg: float, model_axg: float, enrichment: dict,
             home_is_home: bool = True) -> tuple:
    """
    Model xG ile gerçek xG'yi kaynak önceliğine göre karıştır.

    Öncelik zinciri:
      1. real_rapidapi → 0.65 × rapidapi_xg + 0.35 × model_xg
      2. real (AF Pro) → 0.60 × af_xg       + 0.40 × model_xg
      3. af_goals      → 0.40 × gol_ort.    + 0.60 × model_xg
      4. model         → model_xg (değişmez)

    home_is_home: ev sahibi gerçekten ev sahibi mi (neutral sahada False)
    """
    from config import XG_BLEND_RAPIDAPI

    # ─── 1. real_rapidapi (ExpectedScore API) ────────────────────────────────
    if enrichment.get("rapidapi_available"):
        rapi_hxg = enrichment.get("rapidapi_hxg") or 0.0
        rapi_axg = enrichment.get("rapidapi_axg") or 0.0
        if rapi_hxg > 0 and rapi_axg > 0:
            w = XG_BLEND_RAPIDAPI
            final_h = round(w * rapi_hxg + (1 - w) * model_hxg, 3)
            final_a = round(w * rapi_axg + (1 - w) * model_axg, 3)
            return max(0.10, final_h), max(0.10, final_a)

    # ─── 2. AF Pro+ xG ───────────────────────────────────────────────────────
    h_stats = enrichment.get("home_xg_stats")
    a_stats = enrichment.get("away_xg_stats")
    xg_ok   = enrichment.get("xg_available", False)

    if not h_stats or not a_stats:
        return model_hxg, model_axg

    if xg_ok and home_is_home:
        # Ev takımı için home split, deplasman için away split
        real_hxg = h_stats.get("xg_for_home") or 0
        real_axg = a_stats.get("xg_for_away") or 0
        # Savunma kalitesi: rakip xG against
        real_ha  = a_stats.get("xg_against_away") or 0
        real_ad  = h_stats.get("xg_against_home") or 0
        blend_h  = (real_hxg + real_ha) / 2
        blend_a  = (real_axg + real_ad) / 2
        if blend_h > 0 and blend_a > 0:
            final_h = round(0.60 * blend_h + 0.40 * model_hxg, 3)
            final_a = round(0.60 * blend_a + 0.40 * model_axg, 3)
            return max(0.10, final_h), max(0.10, final_a)

    # ─── 3. AF gol istatistikleri (ücretsiz fallback) ─────────────────────────
    if home_is_home:
        gf_h = h_stats.get("goals_for_home", 0)
        gf_a = a_stats.get("goals_for_away", 0)
        if gf_h > 0 and gf_a > 0:
            final_h = round(0.40 * gf_h + 0.60 * model_hxg, 3)
            final_a = round(0.40 * gf_a + 0.60 * model_axg, 3)
            return max(0.10, final_h), max(0.10, final_a)

    # ─── 4. Model xG (değişmez) ───────────────────────────────────────────────
    return model_hxg, model_axg


def injuries_to_adjustments(injuries: list) -> tuple:
    """
    Sakatlık/ceza listesinden atk/def ayarlaması üret.
    manual_analyzer.py'deki ABSENCE_IMPACT ile aynı mantık.
    Döner: (atk_adj, def_adj)
    """
    ABSENCE_IMPACT = {
        "bench":      {"atk": -0.02, "def": -0.01},
        "starter":    {"atk": -0.06, "def": -0.04},
        "key_player": {"atk": -0.12, "def": -0.07},
        "top_scorer": {"atk": -0.18, "def": -0.03},
        "captain":    {"atk": -0.08, "def": -0.10},
        "goalkeeper": {"atk":  0.00, "def": -0.15},
    }
    atk = def_ = 0.0
    for inj in injuries:
        ab_type = inj.get("absence_type", "starter")
        impact  = ABSENCE_IMPACT.get(ab_type, ABSENCE_IMPACT["starter"])
        atk  += impact["atk"]
        def_ += impact["def"]
    # Makul sınırlar (tek takımın %40'ından fazlasını silme)
    return max(-0.40, atk), max(-0.40, def_)


async def find_fixture_id(
    home_name: str, away_name: str, match_date: str,
    league_code: str, season: int
) -> Optional[int]:
    """
    football-data.org maçını API-Football fixture ID'siyle eşleştir.
    """
    fixtures = await get_upcoming_fixture_ids(league_code, season)
    best_score = 0.0
    best_id    = None
    for fx in fixtures:
        h_sim = _name_sim(home_name, fx["home_team"])
        a_sim = _name_sim(away_name, fx["away_team"])
        score = (h_sim + a_sim) / 2
        # Tarih yakınlığı bonusu
        if match_date and fx.get("date"):
            try:
                md = datetime.fromisoformat(match_date.replace("Z", ""))
                fd = datetime.fromisoformat(fx["date"].replace("Z", "").split("+")[0])
                diff_h = abs((md - fd).total_seconds()) / 3600
                if diff_h < 3:    score += 0.25
                elif diff_h < 24: score += 0.10
            except Exception:
                pass
        if score > best_score and score >= 0.6:
            best_score = score
            best_id    = fx["fixture_id"]
    return best_id
