"""Pinnacle opening/closing line via OddsPapi v4"""
import json, os, logging, httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from config import ODDSPAPI_KEY, ODDSPAPI_TOURNAMENT_MAP, ODDSPAPI_DAILY_LIMIT
from odds_matcher import normalize_name, name_match

logger = logging.getLogger(__name__)

ODDSPAPI_BASE = "https://api.oddspapi.io/v4"
_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_DAILY_PATH = os.path.join(_DATA_DIR, "oddspapi_daily.json")

# In-memory cache: key → (unix_ts_expires, data)
_fixture_cache: dict = {}
_opening_cache: dict = {}
_closing_cache: dict = {}

CACHE_FIXTURE_TTL = 86400    # 24h
CACHE_OPENING_TTL = 1800     # 30 min
CACHE_CLOSING_TTL = 604800   # 7 days

# Market id → outcome id → market_key
_MARKET_MAP = {
    "home":    (101, 101),
    "draw":    (101, 102),
    "away":    (101, 103),
    "over25":  (104, 104),
    "under25": (104, 105),
}
# Reverse: (market_id, outcome_id) → market_key
_REV_MAP = {v: k for k, v in _MARKET_MAP.items()}


# ─── RATE LIMITER ───────────────────────────────────────────────────────────────

def _ensure_data_dir():
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except Exception as e:
        logger.error("oddspapi data dir error: %s", e)


def _load_daily() -> dict:
    _ensure_data_dir()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(_DAILY_PATH, "r") as f:
            d = json.load(f)
        if d.get("date") != today:
            return {"date": today, "count": 0}
        return d
    except Exception:
        return {"date": today, "count": 0}


def _save_daily(d: dict):
    _ensure_data_dir()
    try:
        with open(_DAILY_PATH, "w") as f:
            json.dump(d, f)
    except Exception as e:
        logger.error("oddspapi_daily save error: %s", e)


def _check_and_increment() -> bool:
    """True if request is allowed (and increments counter). False if limit exceeded."""
    d = _load_daily()
    if d["count"] >= ODDSPAPI_DAILY_LIMIT:
        logger.warning(
            "oddspapi daily limit reached count=%d limit=%d",
            d["count"], ODDSPAPI_DAILY_LIMIT,
        )
        return False
    d["count"] += 1
    _save_daily(d)
    return True


def get_requests_today() -> int:
    return _load_daily().get("count", 0)


# ─── CACHE HELPERS ──────────────────────────────────────────────────────────────

def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _cache_get(store: dict, key: str):
    entry = store.get(key)
    if entry and entry[0] > _now_ts():
        return entry[1]
    return None


def _cache_set(store: dict, key: str, data, ttl: int):
    store[key] = (_now_ts() + ttl, data)


# ─── 1. FIXTURE LOOKUP ──────────────────────────────────────────────────────────

async def get_fixture_id(home: str, away: str, commence_time: str) -> Optional[str]:
    """
    Jaccard eşleştirme ile OddsPapi fixture ID döner.
    commence_time: ISO8601 string (±3h aralığında arama yapılır).
    """
    if not ODDSPAPI_KEY:
        return None

    cache_key = f"{normalize_name(home)}|{normalize_name(away)}"
    cached = _cache_get(_fixture_cache, cache_key)
    if cached:
        return cached

    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.now(timezone.utc)

    from_ts = (dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_ts   = (dt + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not _check_and_increment():
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{ODDSPAPI_BASE}/fixtures",
                params={
                    "sportId": 10,
                    "from": from_ts,
                    "to": to_ts,
                    "hasOdds": "true",
                    "apiKey": ODDSPAPI_KEY,
                },
            )
        if r.status_code != 200:
            logger.debug("oddspapi fixtures failed status=%d", r.status_code)
            return None

        fixtures = r.json()
        if isinstance(fixtures, dict):
            fixtures = fixtures.get("data", fixtures.get("fixtures", []))

        h_norm = normalize_name(home)
        a_norm = normalize_name(away)
        best_score = 0.0
        best_id = None

        for fx in (fixtures or []):
            p1 = normalize_name(fx.get("participant1Name") or fx.get("homeTeam") or "")
            p2 = normalize_name(fx.get("participant2Name") or fx.get("awayTeam") or "")
            score = (name_match(h_norm, p1) + name_match(a_norm, p2)) / 2
            if score > best_score:
                best_score = score
                best_id = str(fx.get("fixtureId") or fx.get("id") or "")

        if best_score >= 0.55 and best_id:
            logger.info(
                "oddspapi fixture_match home=%s away=%s score=%.2f id=%s",
                home, away, best_score, best_id,
            )
            _cache_set(_fixture_cache, cache_key, best_id, CACHE_FIXTURE_TTL)
            return best_id

        logger.debug("oddspapi no_fixture_match home=%s away=%s best_score=%.2f", home, away, best_score)

    except Exception as e:
        logger.debug("oddspapi get_fixture_id error: %s", e)

    return None


# ─── PARSE HELPERS ──────────────────────────────────────────────────────────────

def _parse_live_odds(payload: dict) -> Optional[dict]:
    """
    bookmakerOdds.pinnacle.markets[mktId].outcomes[outcId].players["0"].price
    """
    try:
        pinnacle = (
            payload.get("data", payload)
                   .get("bookmakerOdds", {})
                   .get("pinnacle", {})
        )
        markets_raw = pinnacle.get("markets", {})
        result = {}
        for mkt_key, (mkt_id, out_id) in _MARKET_MAP.items():
            mkt_str = str(mkt_id)
            out_str = str(out_id)
            price = (
                markets_raw
                .get(mkt_str, {})
                .get("outcomes", {})
                .get(out_str, {})
                .get("players", {})
                .get("0", {})
                .get("price")
            )
            if price and float(price) > 1.0:
                result[mkt_key] = round(float(price), 3)
        return result if result else None
    except Exception as e:
        logger.debug("oddspapi parse_live_odds error: %s", e)
        return None


def _parse_historical_odds(payload: dict) -> Optional[dict]:
    """
    players["0"] bir listedir; her elemanın createdAt'ı var.
    En yeni createdAt = closing fiyat.
    """
    try:
        pinnacle = (
            payload.get("data", payload)
                   .get("bookmakerOdds", {})
                   .get("pinnacle", {})
        )
        markets_raw = pinnacle.get("markets", {})
        result = {}
        for mkt_key, (mkt_id, out_id) in _MARKET_MAP.items():
            mkt_str = str(mkt_id)
            out_str = str(out_id)
            records = (
                markets_raw
                .get(mkt_str, {})
                .get("outcomes", {})
                .get(out_str, {})
                .get("players", {})
                .get("0")
            )
            if not records:
                continue
            # List → pick the latest by createdAt
            if isinstance(records, list) and records:
                records_sorted = sorted(
                    records,
                    key=lambda x: x.get("createdAt", ""),
                    reverse=True,
                )
                price = records_sorted[0].get("price")
            elif isinstance(records, dict):
                price = records.get("price")
            else:
                continue
            if price and float(price) > 1.0:
                result[mkt_key] = round(float(price), 3)
        return result if result else None
    except Exception as e:
        logger.debug("oddspapi parse_historical_odds error: %s", e)
        return None


# ─── 2. OPENING ODDS ────────────────────────────────────────────────────────────

async def get_pinnacle_opening(fixture_id: str) -> Optional[dict]:
    """GET /v4/odds?fixtureId=...&bookmakers=pinnacle"""
    if not ODDSPAPI_KEY or not fixture_id:
        return None

    cached = _cache_get(_opening_cache, fixture_id)
    if cached:
        return cached

    if not _check_and_increment():
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{ODDSPAPI_BASE}/odds",
                params={
                    "fixtureId": fixture_id,
                    "bookmakers": "pinnacle",
                    "apiKey": ODDSPAPI_KEY,
                },
            )
        if r.status_code != 200:
            logger.debug("oddspapi opening failed status=%d fixture=%s", r.status_code, fixture_id)
            return None

        odds = _parse_live_odds(r.json())
        if odds is None:
            logger.debug("oddspapi opening parse_failed fixture=%s", fixture_id)
            return None

        # Tüm 5 market mevcut değilse None
        required = {"home", "draw", "away", "over25", "under25"}
        if not required.issubset(odds.keys()):
            logger.debug(
                "oddspapi opening incomplete markets=%s fixture=%s",
                list(odds.keys()), fixture_id,
            )
            return None

        result = {
            **odds,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "pinnacle_live",
        }
        _cache_set(_opening_cache, fixture_id, result, CACHE_OPENING_TTL)
        logger.info("oddspapi opening fixture=%s markets=%s", fixture_id, list(odds.keys()))
        return result

    except Exception as e:
        logger.debug("oddspapi get_pinnacle_opening error fixture=%s err=%s", fixture_id, e)
        return None


# ─── 3. CLOSING ODDS ────────────────────────────────────────────────────────────

async def get_pinnacle_closing(fixture_id: str) -> Optional[dict]:
    """GET /v4/historical-odds?fixtureId=...&bookmakers=pinnacle"""
    if not ODDSPAPI_KEY or not fixture_id:
        return None

    cached = _cache_get(_closing_cache, fixture_id)
    if cached:
        return cached

    if not _check_and_increment():
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{ODDSPAPI_BASE}/historical-odds",
                params={
                    "fixtureId": fixture_id,
                    "bookmakers": "pinnacle",
                    "apiKey": ODDSPAPI_KEY,
                },
            )
        if r.status_code != 200:
            logger.debug("oddspapi closing failed status=%d fixture=%s", r.status_code, fixture_id)
            return None

        odds = _parse_historical_odds(r.json())
        if odds is None:
            logger.debug("oddspapi closing parse_failed fixture=%s", fixture_id)
            return None

        result = {
            **odds,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "pinnacle_historical",
        }
        _cache_set(_closing_cache, fixture_id, result, CACHE_CLOSING_TTL)
        logger.info("oddspapi closing fixture=%s markets=%s", fixture_id, list(odds.keys()))
        return result

    except Exception as e:
        logger.debug("oddspapi get_pinnacle_closing error fixture=%s err=%s", fixture_id, e)
        return None
