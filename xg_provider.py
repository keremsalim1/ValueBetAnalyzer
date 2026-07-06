"""
ExpectedScore xG API entegrasyonu (RapidAPI üzerinden)
https://rapidapi.com/Wolf1984/api/football-xg-statistics
pip install xgclient

.env: RAPIDAPI_XG_KEY=xxx  (opsiyonel)

Strateji:
  - get_season_xg(): tüm sezon fixture'larından takım başına xg_for/xg_against ortalaması
  - get_team_xg(): tek takım için Jaccard eşleşmeli lookup
  - Cache: 12 saat
  - Anahtar yoksa veya hata varsa {} / None döner, sessiz fallback
"""
import logging
from datetime import datetime
from typing import Optional

from config import RAPIDAPI_XG_KEY, XG_MIN_MATCHES, XG_JACCARD_MIN
from odds_matcher import normalize_name, name_match  # Jaccard — odds_matcher'dan

logger = logging.getLogger(__name__)

# ─── LİG HARİTASI ────────────────────────────────────────────────────────────
LEAGUE_MAP = {
    "PL":  {"country": "England",     "name": "Premier League"},
    "PD":  {"country": "Spain",       "name": "La Liga"},
    "BL1": {"country": "Germany",     "name": "Bundesliga"},
    "SA":  {"country": "Italy",       "name": "Serie A"},
    "FL1": {"country": "France",      "name": "Ligue 1"},
    "DED": {"country": "Netherlands", "name": "Eredivisie"},
    "PPL": {"country": "Portugal",    "name": "Primeira Liga"},
}

# ─── CACHE ───────────────────────────────────────────────────────────────────
_cache: dict = {}

def _cached(key: str, ttl: int):
    if key in _cache:
        ts, data = _cache[key]
        if (datetime.utcnow() - ts).total_seconds() < ttl:
            return data
    return None

def _set_cache(key: str, data):
    _cache[key] = (datetime.utcnow(), data)


# ─── YARDIMCİ: obje veya dict'ten değer al ───────────────────────────────────
def _get(obj, key, default=None):
    """xgclient hem dict hem nesne dönebilir — ikisini de destekle."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ─── ANA FONKSİYONLAR ────────────────────────────────────────────────────────

async def get_season_xg(league_code: str, season_year: int) -> dict:
    """
    Belirtilen lig ve sezon için tüm takımların xG ortalamalarını döner.

    Döner:
      {
        "Manchester City": {"xg_for": 2.14, "xg_against": 0.82, "n_matches": 30},
        ...
      }
    xg_for / xg_against: maç başı ortalama (home + away birleşik)
    Hata veya anahtar yoksa: {} döner.
    """
    if not RAPIDAPI_XG_KEY:
        return {}

    ck = f"rapidapi_season_xg:{league_code}:{season_year}"
    cached = _cached(ck, 43200)  # 12 saat
    if cached is not None:
        return cached

    league_info = LEAGUE_MAP.get(league_code)
    if not league_info:
        logger.debug("xg_provider unsupported_league league=%s", league_code)
        return {}

    try:
        from xgclient.client import ExpectedGoalsClient
        client = ExpectedGoalsClient(RAPIDAPI_XG_KEY)

        # 1. Ülke ID'si bul
        countries = client.countries()
        country_id = None
        target_country = league_info["country"]
        for c in countries:
            c_name = _get(c, "name", "")
            # tam eşleşme önce, ardından Jaccard
            if normalize_name(c_name) == normalize_name(target_country):
                country_id = _get(c, "id")
                break
            if name_match(normalize_name(c_name), normalize_name(target_country)) >= 0.85:
                country_id = _get(c, "id")
                break

        if country_id is None:
            logger.warning("xg_provider country_not_found league=%s target=%s",
                           league_code, target_country)
            return {}

        # 2. Turnuva (lig) bul — Jaccard eşleşmesi
        tournaments = client.tournaments(country_id)
        target_league = league_info["name"]
        best_sim = 0.0
        league_id = None
        for t in tournaments:
            t_name = _get(t, "name", "")
            s = name_match(normalize_name(t_name), normalize_name(target_league))
            if s > best_sim:
                best_sim = s
                league_id = _get(t, "id")

        if league_id is None or best_sim < 0.5:
            logger.warning("xg_provider league_not_matched league=%s best_sim=%.2f",
                           league_code, best_sim)
            return {}

        # 3. Sezon bul
        seasons = client.seasons(league_id)
        season_id = None
        for s in seasons:
            s_year = _get(s, "year")
            s_name = str(_get(s, "name", ""))
            if str(s_year) == str(season_year) or str(season_year) in s_name:
                season_id = _get(s, "id")
                break

        if season_id is None:
            logger.warning("xg_provider season_not_found league=%s year=%d",
                           league_code, season_year)
            return {}

        # 4. Tüm fixture'ları çek
        fixtures = client.fixtures(season_id)

        # 5. Takım başına kümülatif xG biriktir
        teams: dict = {}
        for fx in fixtures:
            home_obj = _get(fx, "homeTeam", {})
            away_obj = _get(fx, "awayTeam", {})
            hname = _get(home_obj, "name", "")
            aname = _get(away_obj, "name", "")
            hxg_raw = _get(home_obj, "xg")
            axg_raw = _get(away_obj, "xg")

            if hxg_raw is None or axg_raw is None or not hname or not aname:
                continue

            try:
                hxg_val = float(hxg_raw)
                axg_val = float(axg_raw)
            except (TypeError, ValueError):
                continue

            if hname not in teams:
                teams[hname] = {"xg_for": 0.0, "xg_against": 0.0, "n": 0}
            if aname not in teams:
                teams[aname] = {"xg_for": 0.0, "xg_against": 0.0, "n": 0}

            teams[hname]["xg_for"]     += hxg_val
            teams[hname]["xg_against"] += axg_val
            teams[hname]["n"]          += 1

            teams[aname]["xg_for"]     += axg_val
            teams[aname]["xg_against"] += hxg_val
            teams[aname]["n"]          += 1

        # 6. Kümülatif → maç başı ortalama
        result = {}
        for name, d in teams.items():
            n = d["n"]
            if n > 0:
                result[name] = {
                    "xg_for":     round(d["xg_for"] / n, 3),
                    "xg_against": round(d["xg_against"] / n, 3),
                    "n_matches":  n,
                }

        logger.info("xg_provider season_loaded league=%s year=%d teams=%d",
                    league_code, season_year, len(result))
        _set_cache(ck, result)
        return result

    except ImportError:
        logger.warning("xg_provider xgclient_not_installed — pip install xgclient")
        return {}
    except Exception as exc:
        logger.warning("xg_provider error league=%s year=%d error=%s",
                       league_code, season_year, exc)
        return {}


async def get_team_xg(team_name: str, league_code: str, season_year: int) -> Optional[dict]:
    """
    Tek bir takım için xG verisi döner.

    Döner:
      {"xg_for": 1.42, "xg_against": 0.98, "n_matches": 28, "source": "real_rapidapi"}
    veya None (veri yetersiz / eşleşme yok / anahtar yok).

    Eşleşme: Jaccard >= XG_JACCARD_MIN (config'den)
    Minimum maç: XG_MIN_MATCHES (config'den)
    """
    try:
        season_data = await get_season_xg(league_code, season_year)
        if not season_data:
            return None

        best_sim = 0.0
        best_name = None
        norm_target = normalize_name(team_name)
        for name in season_data:
            s = name_match(norm_target, normalize_name(name))
            if s > best_sim:
                best_sim = s
                best_name = name

        if best_name is None or best_sim < XG_JACCARD_MIN:
            logger.debug("xg_provider team_not_matched team=%s best_sim=%.2f threshold=%.2f",
                         team_name, best_sim, XG_JACCARD_MIN)
            return None

        data = season_data[best_name]
        if data["n_matches"] < XG_MIN_MATCHES:
            logger.debug("xg_provider insufficient_data team=%s matched=%s n=%d min=%d",
                         team_name, best_name, data["n_matches"], XG_MIN_MATCHES)
            return None

        return {
            "xg_for":     data["xg_for"],
            "xg_against": data["xg_against"],
            "n_matches":  data["n_matches"],
            "source":     "real_rapidapi",
        }

    except Exception as exc:
        logger.warning("xg_provider get_team_xg error team=%s error=%s", team_name, exc)
        return None
