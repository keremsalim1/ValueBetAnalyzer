# CLAUDE.md — Value Bet Analyzer v8.4

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update tasks/lessons.md with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management
1. Plan First: Write plan to tasks/todo.md with checkable items
2. Verify Plan: Check in before starting implementation
3. Track Progress: Mark items complete as you go
4. Explain Changes: High-level summary at each step
5. Document Results: Add review section to tasks/todo.md
6. Capture Lessons: Update tasks/lessons.md after corrections

## Core Principles
- Simplicity First: Make every change as simple as possible. Impact minimal code.
- No Laziness: Find root causes. No temporary fixes. Senior developer standards.
- Minimal Impact: Only touch what's necessary. No side effects with new bugs.

## Yapı
Modüler: 19 Python dosyası + 1 JSX. Port 2000.

```
backend.py              ← FastAPI endpoint'ler + gömülü frontend HTML + CLV background task
config.py               ← sabitler, lig tanımları, otomatik sezon, market sınıfları, logging setup (JSON formatter)
strength_model.py       ← zaman ağırlıklı, ev/dep split, shrinkage, cap
probability_model.py    ← Dixon-Coles Poisson (veri bazlı rho) + joint İY/MS + korner
risk_manager.py         ← adaptif Kelly, drawdown, günlük + haftalık limit, korelasyon
odds_matcher.py         ← Jaccard+zaman eşleştirme, totals line doğrulama, margin filtre; multi-bookmaker: get_best_odds_detail, get_margin_comparison, get_odds_movement (steam move)
market_builder.py       ← market oluştur, sınıfla, value hesapla, sanity check
manual_analyzer.py      ← API'siz manuel veri girişi ile analiz
backtest.py             ← walk-forward, adaptif Kelly staking, ROI, Brier, kalibrasyon (1X2+O/U), bankroll sim
data_fetch.py           ← football-data.org + The Odds API, cache, önceki sezon fallback
settlement.py           ← bahis sonuçlandırma (13 market: 1X2, btts, dc, over/under, ht)
trust_gate.py           ← canlı öneri güven kapısı (backtest performansına bağlı)
performance_memory.py   ← geçmiş performans hafızası → confidence'a etki
line_tracker.py         ← closing line tracking (background task ile saatlik güncelleme)
sanity_checks.py        ← xG/edge anomali tespiti ve reject
disabled_markets_store.py ← disabled market persistence (JSON dosya)
paper_trading.py        ← kağıt üstü canlı test (ht market desteğiyle)
elo_rating.py           ← Glicko-2 rating sistemi (math only, harici kütüphane yok)
apifootball.py          ← API-Football v3: gerçek xG + sakatlık/ceza verisi; blend_xg() 4 katmanlı öncelik
xg_provider.py          ← ExpectedScore xG (RapidAPI): get_season_xg + get_team_xg, 12s cache, Jaccard eşleştirme
pinnacle_tracker.py     ← OddsPapi v4: get_fixture_id + get_pinnacle_opening + get_pinnacle_closing; 25 istek/gün limit (data/oddspapi_daily.json)
value-bet-live.jsx      ← React frontend (v8.3): Analysis|Backtest|Dashboard tab yapısı; BankrollChart, CalibrationDiagram, MarketHeatmap, EloTable, CLVTrend (Recharts)
```

## .env
```
FOOTBALL_DATA_API_KEY=xxx   (zorunlu - football-data.org)
ODDS_API_KEY=xxx            (zorunlu - the-odds-api.com)
APIFOOTBALL_KEY=xxx         (opsiyonel - api-sports.io → gerçek xG + sakatlık)
RAPIDAPI_XG_KEY=xxx         (opsiyonel - rapidapi.com/Wolf1984/api/football-xg-statistics → ExpectedScore xG)
ODDSPAPI_KEY=xxx            (opsiyonel - oddspapi.io → gerçek Pinnacle opening/closing)
```

## Sabitler (config.py)
```python
MIN_EDGE=0.05, KELLY_HARD_CAP=0.025, MIN_CONFIDENCE=55
MAX_CORRELATED_BETS=1, DAILY_RISK_CAP=0.08, WEEKLY_RISK_CAP=0.20
SHRINK_N=10, STRENGTH_CAP=(0.4,2.5), DECAY_HALF_LIFE=15
REAL_BETTING_MODE=False  # True yapılırsa trust gate + CLV + coverage kontrolü aktif
EXPANSION_MIN_BETS=20, EXPANSION_MIN_ROI=0.0  # Expansion market auto-enable eşikleri
XG_BLEND_RAPIDAPI=0.65   # real_rapidapi blend ağırlığı
XG_MIN_MATCHES=5         # yetersiz veri eşiği (bu altında rapidapi xG kullanılmaz)
XG_JACCARD_MIN=0.6       # takım isim eşleşme minimum Jaccard skoru
# Filtre sabitleri
MIN_ODDS=1.70, MAX_ODDS=2.50          # odds band filtresi
REQUIRE_STEAM_ALIGNMENT=False         # True → ters steam hareketi olanlar reddedilir
MAX_BETS_PER_DAY=3                    # günlük max value bet (data/daily_bets.json)
BACKTEST_MIN_BETS=50                  # bu altında trust_gate "insufficient_data" uyarısı
CLV_POSITIVE_RATE_MIN=0.55            # bu altında trust_gate "clv_warning" uyarısı
# OddsPapi sabitleri
ODDSPAPI_KEY=...                      # opsiyonel — yoksa tüm pinnacle fonksiyonları None döner
ODDSPAPI_DAILY_LIMIT=25               # günlük max istek (data/oddspapi_daily.json)
ODDSPAPI_TOURNAMENT_MAP={PL:17,...}   # lig → tournament ID
```

## Aktif Marketler (sadece tradable)
`home, draw, away, over25, under25` — diğer tüm marketler disabled.

### CORE_MARKETS koruması (config.py)
```python
CORE_MARKETS = {"home", "draw", "away", "over25", "under25"}  # asla disable edilemez
TRADABLE_MARKETS = set(CORE_MARKETS)
DISABLED_MARKETS -= CORE_MARKETS                   # startup'ta core'lar temizlenir
TRADABLE_MARKETS -= (DISABLED_MARKETS - CORE_MARKETS)  # core'lar çıkarılamaz
```
- Backtest auto-disable: `mkt not in CORE_MARKETS` guard'ı var — core marketler ROI<0 olsa bile kapatılamaz
- `save_disabled_markets()` çağrısından önce `config.DISABLED_MARKETS -= CORE_MARKETS` güvenlik katmanı uygulanır

## Expansion Marketler (backtest kanıtlayana kadar kapalı)
`btts_yes, btts_no, dc_1x, dc_x2, dc_12`
- Varsayılan olarak `DISABLED_MARKETS` içinde (DEFAULT_DISABLED)
- Backtest her çalıştığında bu marketler **ayrı bet slotunda** değerlendirilir (tradable marketlerden bağımsız 1 bet/maç)
- **Auto-enable kuralı**: `ROI > 0` ve `n_bets >= 20` → `DISABLED_MARKETS`'tan çıkar, `TRADABLE_MARKETS`'a ekle + persist et
- **Auto-disable**: Tradable markette olduğu gibi ROI < 0 ve bets >= 5 → kapatılmaz (expansion marketler için bu kural uygulanmaz)
- The Odds API market key eşleşmesi: `btts` → btts_yes/btts_no, `double_chance` → dc_1x/dc_x2/dc_12
- `/analyze` response'da `expansion_markets` alanı: her expansion market için bets/roi/hit_rate/status/ready_for_live/needs_bets
- **Expansion market oranları canlı analizde çekilmez** — sadece backtest sırasında (backtest zaten odds_fetch çağırmaz, walk-forward kullanır)

## Ligler
PL, PD, BL1, SA, FL1, DED, PPL, CL, EL, UECL, WC

## Endpoint'ler
```
GET  /                       → Gömülü HTML arayüz
GET  /analyze/{lc}           → Tam analiz (?bankroll=1000&days=14)
GET  /value-bets             → Tüm ligler value betler
GET  /backtest/{lc}          → Walk-forward backtest (ROI, Brier, calibration, live_ready)
POST /analyze-manual         → Manuel veri girişli analiz (API gerektirmez)
GET  /export/json            → JSON indir
GET  /export/csv             → CSV indir
GET  /disabled-markets       → Disabled/tradable market listesi
POST /disabled-markets/reset → Fabrika ayarlarına dön
GET  /trust-status           → Tüm lig/market trust durumu
GET  /clv-report             → Closing line value raporu
DELETE /clv-report           → CLV snapshot sıfırla
POST /paper-bets/add         → Paper bet ekle
POST /paper-bets/settle      → Paper bet sonuçlandır {id, home_goals, away_goals, ht_home?, ht_away?}
GET  /paper-bets             → Tüm paper betler
GET  /paper-stats            → Paper trading istatistikleri
DELETE /paper-bets           → Paper betleri sıfırla
GET  /daily-review           → Günlük özet rapor
GET  /debug/{lc}             → Bağlantı testi (football-data + odds + api-football)
DELETE /cache                → Cache temizle
GET  /api                    → Versiyon bilgisi + aktif özellikler
GET  /leagues                → Lig listesi
```

## Model Pipeline
1. football-data.org'dan geçmiş maçlar çekilir (500 maç); mevcut sezonda <30 maç varsa önceki sezon da eklenir
2. **Glicko-2 derecelendirme**: tüm geçmiş maçlar kronolojik sırayla işlenir → her takım için `{rating, rd, vol, trend_last5}` (elo_rating.py)
3. Takım güçleri: exponential decay (yarı ömür 15), ev/dep split, Bayesian shrinkage, outlier cap [0.4,2.5]
   - **ELO blend** (n≥5 ve RD<250 ise): `final_strength = 0.7 × mevcut + 0.3 × elo_normalized`
   - `elo_normalized = clamp((rating-1500)/400 + 1.0, 0.5, 2.0)` → atk için doğrudan, def için ters (2.0 - elo_norm)
4. Expected goals (model): `hxg = home_atk × away_def × lig_ev_ort`
5. **Contextual features** (strength_model.py) — xG'ye çarpan olarak uygulanır:
   - `rest_days`: son maçtan bu yana gün sayısı → fatigue (<3g: ×0.95) / fresh (>7g: ×1.03)
   - `form_trend`: son 5 maç gol farkı lineer regresyon eğimi → `atk × clamp(1+slope×0.1, 0.90, 1.10)`
   - `h2h_factor`: son 5 karşılaşma ev galibiyet oranı → win>0.6: ×1.05, win<0.3: ×0.95
   - `position_gap`: puan tablosu sıra farkı → gap>10: conf+3, gap<3: conf-2
4. **API-Football**: gerçek xG (ücretli) veya gol istatistikleri (ücretsiz) ile model xG blend'lenir
   - xG mevcutsa: 60% gerçek xG + 40% model xG
   - Sadece gol istatistiği mevcutsa: 40% gerçek gol ort. + 60% model xG
   - API-Football yoksa: model xG aynen kullanılır
5. **Sakatlık/ceza**: API-Football fixture_id ile çekilir, pozisyona göre atk/def ayarlaması uygulanır
6. Dixon-Coles Poisson matrisi: rho parametresi geçmiş maç verisinden tahmin edilir (veri < 30 ise -0.05)
   - **Rating farkı rho ayarı**: `rho_adj = rho × max(0, 1 - |rating_diff| / 400)` — büyük fark → rho→0 (sürpriz daha az, saf Poisson)
7. Poisson 8×8 matris (normalize) + joint İY/MS + korner hesabı
7b. **xG blend önceliği** (blend_xg — apifootball.py):
   - `real_rapidapi`: `0.65 × rapidapi_xg + 0.35 × model_xg` (xg_provider → ExpectedScore API)
   - `real` (AF Pro+): `0.60 × af_xg + 0.40 × model_xg`
   - `af_goals`: `0.40 × gol_ort. + 0.60 × model_xg`
   - `model`: model xG değişmez
8. The Odds API'den gerçek oranlar (`"h2h,totals"` — sadece core 5 market), Jaccard+zaman eşleştirme, margin ≤%8 filtre, confidence ≥60
9. Sanity check: xG>3.5 veya edge>%20 veya low_conf+high_edge → reject
10. Value = prob × odds - 1 (sadece tradable + gerçek oran + confidence≥55 + edge≥%5)
11. Trust gate: backtest'te pozitif ROI + yeterli bet + kabul edilebilir Brier → güvenilir marketler
12. Adaptif Kelly: `raw × edge_mult × conf_mult × mkt_mult`, smoothing `**0.75`, hard cap %2.5
13. Risk: max 1 bet/maç, günlük %8 cap, **haftalık %20 cap**, edge>%20 iptal

### Yanıt alanları (/analyze/{lc} → her maç için):
```json
"xg_source":          "real_rapidapi" | "real" | "af_goals" | "model",
"af_available":       true | false,
"best_odds_detail":   {market: {"best_odds": 2.15, "bookmaker": "Pinnacle", "all_odds": [...]}},
"margin":             [{"bookmaker": "Pinnacle", "margin": 0.032, "margin_pct": 3.2, "lowest_margin": true}, ...],
"odds_movement":      {market: {"direction": "down", "steam": "down", "bk_count": 4, "up": 0, "down": 4, "details": [...]}},
"steam_move":         true | false,
"steam_markets":      ["home", "over25"],
"home_injuries":      [{"player","position","type","reason"}, ...],
"away_injuries":      [{"player","position","type","reason"}, ...],
"injury_adjustment":  {"home_atk":-0.06,"home_def":0,"away_atk":0,"away_def":-0.04},
"dixon_coles_rho":    -0.08   ← veriden tahmin edilen rho
```

## Settlement Desteklenen Marketler
`home, draw, away, over25, under25, over15, under15, over35, under35,
btts_yes, btts_no, dc_1x, dc_x2, dc_12`
İlk yarı marketleri (ht_home, ht_draw, ht_away): `ht_home` ve `ht_away` skoru gerektirir.

## Manuel Analiz (POST /analyze-manual)
Kullanıcı formdan girer: takım adları, son 10 maç skorları, son 5 ev/deplasman, bahis oranları,
faktörler (motivasyon/form/dinlenme dropdown'ları), eksik oyuncular (dinamik liste).

## Backtest Çıktısı
ROI, yield, max_drawdown, longest_losing_streak, bankroll_history,
market_performance (market bazlı ROI/hit_rate), calibration tablosu **(1X2 + over25/under25)**,
live_ready (bool + reasons), strong/weak markets, odds_mode (real/simulated),
bets_log, disabled_by_backtest (tradable ROI<0 → otomatik disable + persist; **CORE_MARKETS asla disable edilemez**),
enabled_by_backtest (expansion ROI>0 + n_bets>=20 → otomatik tradable'a geç + persist).
**Expansion market staking**: tradable betlerden bağımsız 1 bet/maç slotu — toplam bankroll'u paylaşır.
**Staking**: adaptif Kelly (veri büyüklüğüne bağlı confidence, KELLY_HARD_CAP=%2.5).

### Opsiyonel Analiz (query param)
```
GET /backtest/{lc}?monte_carlo=true&sensitivity=true
```
- **`?monte_carlo=true`** → `"monte_carlo"` anahtarı response'a eklenir:
  ```json
  {"p5_final": 820.5, "p95_final": 1540.2, "median_final": 1120.0,
   "ruin_prob": 3.2, "n_sim": 1000, "n_bets": 87}
  ```
  Mevcut `bets_log` betleri 1000 kez shuffle ederek bankroll path simüle eder.
  `ruin_prob`: bankroll'un başlangıcın %10'unun altına düşme olasılığı (%).

- **`?sensitivity=true`** → `"sensitivity"` anahtarı response'a eklenir:
  ```json
  [{"min_edge": 0.03, "roi": 4.2, "yield": 1.8, "n_bets": 142},
   {"min_edge": 0.05, "roi": 8.1, "yield": 3.4, "n_bets": 87},
   {"min_edge": 0.07, "roi": 11.5, "yield": 5.2, "n_bets": 43},
   {"min_edge": 0.10, "roi": 6.3, "yield": 4.1, "n_bets": 18}]
  ```
  MIN_EDGE değerleri [0.03, 0.05, 0.07, 0.10] ile ayrı ayrı çalışır. 1 bet/maç kuralı korunur.

Her iki parametre de varsayılan olarak `false` — ağır hesaplar için açıkça talep edilmeli.

## CLV Tracking
- Açılış oranı: ilk `/analyze` çağrısında `save_opening_snapshot()` ile kaydedilir
  - `event_id`, `sport_key`, `commence_time` da kaydedilir (gerçek closing için)
- Background task (saatlik) odds_fetch çağrısı: **`"h2h,totals"`** — sadece core market snapshot'ları günceller
- Kapanış oranı — iki katmanlı:
  1. **Gerçek closing** (The Odds API historical endpoint, ücretli plan):
     - Background task her döngüde `try_update_closing()` ile event_id'li maçlar için dener
     - Endpoint: `GET /v4/historical/sports/{sport_key}/odds?eventIds={id}&date={ts}`
     - Plan desteklemiyorsa (402/422) sessizce pseudo-closing'e düşer
  2. **Pseudo closing** (fallback): son 3 background snapshot'ın market bazlı ortalaması
     - `save_pre_match_snapshot()` her çağrıda rolling liste tutar (MAX_SNAPSHOTS=3)
- **CLV formülü**: `CLV = (opening_odds / closing_odds - 1) × 100`
  - Pozitif → açılışta daha iyi oran alındı (değerli)
  - Negatif → kapanış daha iyi (değer kaçırıldı)
- `GET /clv-report` response şeması:
  ```json
  {
    "report": [{"match","market","opening_odds","closing_odds","closing_source",
                "clv_pct","clv_direction","clv_diff",...}],
    "avg_clv_percent": 3.2,
    "positive_rate": 61.5,
    "total_entries": 26,
    "by_market": {
      "home": {"n": 10, "avg_clv_pct": 4.1, "positive_rate": 70.0},
      "over25": {"n": 8, "avg_clv_pct": 2.8, "positive_rate": 62.5}
    }
  }
  ```
- `closing_source`: `"historical_api"` (gerçek) veya `"pseudo"` (3-snapshot ortalama)

## REAL_BETTING_MODE
False → normal çalışır. True → trusted market yoksa veya backtest coverage <100 veya
CLV %60+ negatif ise `top_value_bets=[]` döner, `live_lock_reasons` açıklar.

## Çalıştırma

### Docker (önerilen)
```bash
cp .env.example .env   # anahtarları gir
docker-compose up --build
# http://localhost:2000
```

### Manuel
```bash
pip install -r requirements.txt
uvicorn backend:app --reload --port 2000
```

## Docker Dosyaları
```
Dockerfile          ← python:3.11-slim, port 2000, uvicorn
docker-compose.yml  ← .env mount, port mapping, JSON veri dosyası volume'ları
.env.example        ← 3 API key placeholder
requirements.txt    ← fastapi, uvicorn, httpx, python-dotenv, pytest
```

## İlk Kullanım Sırası
1. `.env` dosyasını oluştur (API anahtarlarını yaz)
2. `uvicorn backend:app --reload --port 2000`
3. Tarayıcıda `http://localhost:2000` aç
4. `GET /debug/PL` ile bağlantıları doğrula (fd_ok, odds_ok, af_ok)
5. Her lig için 🧪 Backtest butonuna tıkla (trust data + performance data dolacak)
6. Paper trading ile test et (`POST /paper-bets/add`)
7. `GET /daily-review` ile günlük kontrol
8. Sonuçlar pozitifse `REAL_BETTING_MODE=True` yap

## Logging
Tüm modüller Python `logging` modülünü kullanır, `print()` yoktur.

```python
# config.py'da setup_logging() ile başlatılır (idempotent)
# Her modülde: logger = logging.getLogger(__name__)
# Çıktı: tek satır JSON  {"ts":..., "level":..., "module":..., "msg":...}
```

Önemli log noktaları:
- `data_fetch`    — `fd_fetch`/`odds_fetch` için `elapsed_ms`, cache hit/miss, toplam maç sayısı
- `market_builder` — `analyzed`, `value`, `rejected` sayıları + `confidence`
- `odds_matcher`  — eşleşme/eşleşmeme, düşük confidence, margin filtre
- `backtest`      — `start/done` (total_bets, ROI, yield, brier, log_loss, rps, live_ready)
- `sanity_checks` — reject/caution: market, hxg, axg, edge, flags
- `apifootball`   — rate limit (429), hata, başarılı istek

Log seviyesi `INFO` (varsayılan). Debug için: `setup_logging(logging.DEBUG)` veya
`LOG_LEVEL=DEBUG` env değişkeni.

## Glicko-2 Rating Sistemi (elo_rating.py)
```
Başlangıç: rating=1500, RD=350, vol=0.06
TAU=0.5 (volatilite sabiti), CONV=173.7178 (ölçek)
İllinois algoritması ile volatilite güncelleme (max 100 iterasyon)
RD sınırları: [30, 350]
```
- `get_team_ratings(matches)` → `{team: {rating, rd, vol, trend_last5, n}}`
  - `trend_last5`: son 5 maçtaki ortalama rating değişimi
- `elo_normalized(rating)` → [0.5, 2.0] güç faktörü
- ELO blend sadece `n≥5` ve `rd<250` iken aktif (yüksek belirsizlikte devre dışı)
- Backtest'te ELO blend yok (walk-forward yapısıyla look-ahead bias olur)

### /analyze/{lc} response'a eklenen contextual feature alanları:
```json
"features": {
  "home_rest":  {"days": 5, "label": "normal",  "multiplier": 1.0},
  "away_rest":  {"days": 2, "label": "fatigue",  "multiplier": 0.95},
  "home_form":  {"slope": 0.4, "multiplier": 1.04, "diffs": [1,2,0,1,3]},
  "away_form":  {"slope": -0.6, "multiplier": 0.94, "diffs": [0,-1,1,-2,0]},
  "h2h":        {"win_rate": 0.6, "total": 5, "home_wins": 3, "multiplier": 1.0},
  "position":   {"home_pos": 3, "away_pos": 14, "gap": 11, "conf_adj": 3}
}
```
`label`: "fatigue" | "normal" | "fresh" | "unknown"

### /analyze/{lc} response'a eklenen ELO alanları:
```json
"home_elo": {"rating": 1623.4, "rd": 95.2, "trend_last5": 12.3},
"away_elo": {"rating": 1487.1, "rd": 140.8, "trend_last5": -5.1},
"elo_diff": 136.3
```

## API-Football Entegrasyonu (apifootball.py)
```
APIFOOTBALL_KEY .env'de yoksa → tüm AF fonksiyonları sessizce atlanır, model devreye girer
Ücretsiz plan: 100 istek/gün
Cache: takım listesi 24s, xG stats 12s, sakatlık 1s, fixture listesi 2s
```

## ExpectedScore xG Entegrasyonu (xg_provider.py)
```
RAPIDAPI_XG_KEY .env'de yoksa → get_team_xg() sessizce None döner, AF→model zincirine düşer
pip install xgclient  (https://github.com/oRastor/xgclient)
Cache: sezon xG verisi 12 saat
Desteklenen ligler: PL, PD, BL1, SA, FL1, DED, PPL
```
- `get_season_xg(league_code, season_year)` → `{team: {xg_for, xg_against, n_matches}}`
  - countries() → tournaments() → seasons() → fixtures() zinciri
  - Her fixture'dan homeTeam.xg / awayTeam.xg okunur, takım başına kümülatif biriktir → maç başı ortlama
- `get_team_xg(team_name, league_code, season_year)` → `{xg_for, xg_against, n_matches, source}` veya `None`
  - Jaccard eşleşme skoru < `XG_JACCARD_MIN` (0.6) → None
  - `n_matches` < `XG_MIN_MATCHES` (5) → None
- Jaccard implementasyonu: `odds_matcher.normalize_name` + `odds_matcher.name_match` (import ile)

## Bilinen Sınırlamalar
- Gerçek xG: **RAPIDAPI_XG_KEY** varsa ExpectedScore API önceliklidir (PL/PD/BL1/SA/FL1/DED/PPL); diğer ligler (CL/EL/UECL/WC) için API-Football veya model devreye girer
- API-Football **ücretsiz** planda xG alanı gelmeyebilir (Pro+ gerekebilir); gol istatistikleriyle zayıf blending devreye girer
- Closing line — 3 katmanlı öncelik:
  1. **pinnacle_historical** (OddsPapi v4, ODDSPAPI_KEY varsa): `clv_reliability="high"` — 25 istek/gün limiti
  2. **historical_api** (The Odds API ücretli plan): `clv_reliability="medium"`
  3. **pseudo** (son 3 snapshot ortalaması, fallback): `clv_reliability="low"`
- Kadro/sakatlık: fixture bazlı sakatlık verisi API-Football'dan gelir; ancak maç öncesi kadro netleşmemişse eksik olabilir
- Gerçek xG shot verisi (şut bazlı xG modeli) yok — API-Football Pro+ ile eklenebilir
