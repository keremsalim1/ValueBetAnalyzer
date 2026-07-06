# Value Bet Analyzer v8.4

A modular football (soccer) value-betting analysis system. It combines a Dixon-Coles Poisson scoring model, Glicko-2 team ratings, adaptive Kelly staking, a backtest-driven trust gate, closing-line-value (CLV) tracking, and paper trading into a single FastAPI application with an embedded web UI.

> ⚠️ **Disclaimer:** This project is a statistical analysis and educational tool. It is **not** financial or betting advice. Betting carries a real risk of financial loss, and all responsibility lies with the user. Past model performance does not guarantee future results.

---

## Table of Contents

- [What It Does](#what-it-does)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Quick Start (Docker)](#quick-start-docker)
- [Manual Setup](#manual-setup)
- [API Keys](#api-keys)
- [Model Pipeline](#model-pipeline)
- [HTTP Endpoints](#http-endpoints)
- [Markets](#markets)
- [Backtesting](#backtesting)
- [Risk Management](#risk-management)
- [Runtime Data Files](#runtime-data-files)
- [Configuration](#configuration)
- [Testing](#testing)
- [Supported Leagues](#supported-leagues)

---

## What It Does

The system pulls historical match results and upcoming fixtures, estimates each team's attacking and defensive strength, converts those into expected goals, and runs them through a Dixon-Coles-corrected Poisson model to produce probabilities for a range of markets (1X2, over/under 2.5, both-teams-to-score, double chance, half-time results, and more).

It then fetches **real bookmaker odds** from The Odds API, matches fixtures via fuzzy name + kickoff-time matching, and flags **value bets** — selections where the model probability multiplied by the offered odds exceeds 1 by a configurable edge threshold. Every recommendation passes through sanity checks, a confidence gate, correlation filtering, and adaptive Kelly staking with strict risk caps.

Before any market is trusted for live recommendations, it must prove itself in a **walk-forward backtest** (positive ROI, sufficient sample size, acceptable calibration). Until then it stays informational only.

## Key Features

- **Probability model** — Dixon-Coles low-score correction with a data-derived `rho` parameter, plus a joint half-time/full-time model and an experimental corners model.
- **Team strength** — Time-weighted (exponential decay), home/away split, Bayesian shrinkage, and outlier capping, blended with **Glicko-2** ratings (rating, rating deviation, volatility, recent-form trend).
- **Contextual features** — Rest days / fatigue, form-trend regression, head-to-head history, and league-table position gap, each applied as a multiplier on expected goals.
- **Real data integrations:**
  - [football-data.org](https://www.football-data.org/) — historical matches + fixtures (required)
  - [The Odds API](https://the-odds-api.com/) — real, multi-bookmaker odds (required)
  - [API-Football](https://api-sports.io/) — real xG + injury/suspension data (optional)
  - [ExpectedScore via RapidAPI](https://rapidapi.com/Wolf1984/api/football-xg-statistics) — season xG (optional)
  - [OddsPapi](https://oddspapi.io/) — real Pinnacle opening/closing lines for high-reliability CLV (optional)
- **Multi-bookmaker analysis** — Best-odds selection, margin comparison across books, and steam-move detection.
- **Risk management** — Adaptive Kelly (2.5% hard cap), daily 8% / weekly 20% risk caps, max 1 correlated bet, edge-anomaly rejection.
- **Validation & tracking** — Walk-forward backtest (ROI, yield, Brier score, log-loss, RPS, calibration curve, Monte-Carlo & sensitivity analysis), trust gate, CLV report, and paper trading.
- **Structured logging** — Every module emits single-line JSON logs (no `print` statements).

## Architecture

Modular design: 19 Python modules plus one React source file, served on port **2000**.

| Module | Responsibility |
|--------|----------------|
| `backend.py` | FastAPI endpoints + embedded frontend HTML + CLV background task |
| `config.py` | Constants, league definitions, auto season detection, market classes, JSON logging setup |
| `strength_model.py` | Time-weighted, home/away-split, shrinkage-capped team strength |
| `probability_model.py` | Dixon-Coles Poisson (data-derived rho) + joint HT/FT + corners |
| `elo_rating.py` | Glicko-2 rating system (pure math, no external library) |
| `risk_manager.py` | Adaptive Kelly, drawdown, daily/weekly caps, correlation filter |
| `odds_matcher.py` | Jaccard + time matching, totals-line validation, margin filter, multi-bookmaker best odds / steam moves |
| `market_builder.py` | Market construction, classification, value calculation, sanity checks |
| `manual_analyzer.py` | API-free manual data-entry analysis |
| `backtest.py` | Walk-forward backtest, adaptive Kelly staking, ROI, Brier, calibration, bankroll simulation |
| `data_fetch.py` | football-data.org + The Odds API clients, caching, previous-season fallback |
| `settlement.py` | Bet settlement across 13 markets |
| `trust_gate.py` | Live-recommendation trust gate driven by backtest performance |
| `performance_memory.py` | Historical performance memory feeding confidence |
| `line_tracker.py` | Closing-line tracking (hourly background task) |
| `sanity_checks.py` | xG / edge anomaly detection and rejection |
| `disabled_markets_store.py` | Disabled-market persistence |
| `paper_trading.py` | Paper (dry-run) live testing |
| `apifootball.py` | API-Football v3: real xG + injury data; 4-layer xG blend |
| `xg_provider.py` | ExpectedScore xG (RapidAPI) |
| `pinnacle_tracker.py` | OddsPapi v4: Pinnacle fixture ID + opening/closing lines |
| `value-bet-live.jsx` | React frontend source (Recharts dashboards) |

## Quick Start (Docker)

```bash
# 1. Configure API keys
cp .env.example .env
# open .env and fill in your keys

# 2. First run only: create empty data files for docker-compose volume mounts
mkdir -p data
echo '[]' > paper_bets.json
for f in trust_data.json performance_data.json line_snapshots.json value_bets_latest.json \
         data/daily_bets.json data/filter_stats.json data/oddspapi_daily.json; do
  echo '{}' > "$f"
done

# 3. Build and run
docker-compose up --build
# open http://localhost:2000
```

On Windows (PowerShell), replace step 2 with:

```powershell
New-Item -ItemType Directory -Force data | Out-Null
Set-Content paper_bets.json '[]'
"trust_data.json","performance_data.json","line_snapshots.json","value_bets_latest.json","data/daily_bets.json","data/filter_stats.json","data/oddspapi_daily.json" | ForEach-Object { Set-Content $_ '{}' }
```

> The empty-file step is required **only for Docker**, because `docker-compose.yml` mounts these files individually; if they don't exist, Docker would create directories in their place. In a manual setup the app creates them automatically on first run. Data files persist across container restarts.

## Manual Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
uvicorn backend:app --reload --port 2000
# open http://localhost:2000
```

### Recommended First-Run Workflow

1. Create `.env` and enter your API keys.
2. Start the server (Docker or manual).
3. Open `http://localhost:2000`.
4. Hit `GET /debug/PL` to verify connectivity (`fd_ok`, `odds_ok`, `af_ok`).
5. Click **Backtest** for each league to populate trust + performance data.
6. Test with paper trading (`POST /paper-bets/add`).
7. Review daily with `GET /daily-review`.
8. Once results are consistently positive, set `REAL_BETTING_MODE=True` in `config.py`.

## API Keys

| Variable | Source | Required | Purpose |
|----------|--------|----------|---------|
| `FOOTBALL_DATA_API_KEY` | [football-data.org](https://www.football-data.org/) | **Yes** | Historical matches + fixtures |
| `ODDS_API_KEY` | [the-odds-api.com](https://the-odds-api.com/) | **Yes** | Real bookmaker odds |
| `APIFOOTBALL_KEY` | [api-sports.io](https://api-sports.io/) | No | Real xG + injuries/suspensions |
| `RAPIDAPI_XG_KEY` | [RapidAPI — football-xg-statistics](https://rapidapi.com/Wolf1984/api/football-xg-statistics) | No | ExpectedScore xG |
| `ODDSPAPI_KEY` | [oddspapi.io](https://oddspapi.io/) | No | Real Pinnacle opening/closing lines |

> 🔒 **Security:** Your `.env` holds real keys and is excluded via `.gitignore` — **never commit it.** Only the placeholder `.env.example` belongs in the repository. If you suspect a key was ever exposed, rotate it with the provider.

## Model Pipeline

1. Fetch historical matches from football-data.org (up to 500); if the current season has fewer than 30 matches, the previous season is appended.
2. Compute **Glicko-2 ratings** chronologically across all matches → `{rating, rd, vol, trend_last5}` per team.
3. Compute **team strengths**: exponential decay (half-life 15), home/away split, Bayesian shrinkage, outlier cap `[0.4, 2.5]`. When `n ≥ 5` and `rd < 250`, blend in ELO: `final = 0.7 × base + 0.3 × elo_normalized`.
4. **Expected goals**: `home_xg = home_atk × away_def × league_home_avg`.
5. Apply **contextual features** (rest/fatigue, form trend, head-to-head, table position) as xG multipliers.
6. **Blend real xG** when available (priority: ExpectedScore → API-Football → model).
7. **Dixon-Coles Poisson** matrix with a `rho` estimated from historical data; large rating gaps shrink `rho` toward zero (purer Poisson for mismatches).
8. Build an 8×8 normalized score matrix + joint HT/FT + corners.
9. Fetch **real odds** (The Odds API `h2h,totals`), match via Jaccard + time, filter margins ≤ 8%, require confidence ≥ 60.
10. **Sanity checks**: reject on extreme xG, extreme edge, or high-edge/low-confidence combinations.
11. **Value** = `prob × odds − 1` (tradable markets only, confidence ≥ 55, edge ≥ 5%).
12. **Trust gate**: only markets with backtest-proven positive ROI + acceptable calibration reach live recommendations.
13. **Adaptive Kelly** staking with edge/confidence/market multipliers, smoothing, and a 2.5% hard cap.
14. **Risk limits**: max 1 bet per match, daily 8% cap, weekly 20% cap, edge > 20% rejected.

## HTTP Endpoints

| Method & Path | Description |
|---------------|-------------|
| `GET /` | Embedded HTML UI |
| `GET /analyze/{lc}` | Full analysis (`?bankroll=1000&days=14`) |
| `GET /value-bets` | Value bets across all leagues |
| `GET /backtest/{lc}` | Walk-forward backtest (`?monte_carlo=true&sensitivity=true`) |
| `POST /analyze-manual` | Manual data-entry analysis (no API required) |
| `GET /export/json` · `GET /export/csv` | Export results |
| `GET /disabled-markets` · `POST /disabled-markets/reset` | Market state |
| `GET /trust-status` | Per-league/market trust status |
| `GET /clv-report` · `DELETE /clv-report` | Closing-line-value report |
| `POST /paper-bets/add` · `POST /paper-bets/settle` · `GET /paper-bets` · `GET /paper-stats` · `DELETE /paper-bets` | Paper trading |
| `GET /daily-review` | Daily summary report |
| `GET /debug/{lc}` | Connectivity test (football-data + odds + API-Football) |
| `DELETE /cache` | Clear cache |
| `GET /api` · `GET /leagues` | Version info + league list |

## Markets

**Active (tradable):** `home`, `draw`, `away`, `over25`, `under25`. These **core markets can never be disabled**, even if backtest ROI goes negative.

**Expansion (disabled until proven):** `btts_yes`, `btts_no`, `dc_1x`, `dc_x2`, `dc_12`. Each backtest evaluates these in a separate bet slot; a market **auto-enables** when it reaches ROI > 0 with ≥ 20 bets, and the change is persisted.

## Backtesting

The walk-forward backtest reports: ROI, yield, max drawdown, longest losing streak, bankroll history, per-market ROI/hit-rate, a calibration table (1X2 + over/under 2.5), Brier score, log-loss, RPS, and a `live_ready` verdict with reasons. `rho` is estimated **only from the warmup window** to avoid look-ahead bias.

Optional query parameters:

- `?monte_carlo=true` — shuffles the realized bets 1,000× to simulate bankroll paths (`p5/p95/median final`, ruin probability).
- `?sensitivity=true` — reruns across `MIN_EDGE ∈ {0.03, 0.05, 0.07, 0.10}`.

Both default to `false` and must be requested explicitly.

## Risk Management

| Control | Default |
|---------|---------|
| Minimum edge | 5% |
| Kelly hard cap | 2.5% |
| Minimum confidence | 55 |
| Max correlated bets | 1 |
| Daily risk cap | 8% |
| Weekly risk cap | 20% |
| Odds band filter | 1.70 – 2.50 |
| Max bets per day | 3 |

## Runtime Data Files

The following files are generated by the application and are **excluded from the repository** (see `.gitignore`):
`trust_data.json`, `performance_data.json`, `line_snapshots.json`, `paper_bets.json`, `value_bets_latest.json`, `disabled_markets.json`, and everything under `data/`.

## Configuration

Core constants live in `config.py` (edge thresholds, Kelly cap, risk caps, xG blend weights, league definitions, market classes). Notably:

- `REAL_BETTING_MODE=False` — when `True`, enables the trust gate + CLV + coverage lock (live recommendations are withheld unless markets are proven).
- Logging defaults to `INFO`; set `LOG_LEVEL=DEBUG` in `.env` for verbose output.

## Testing

```bash
pip install pytest
pytest tests/
```

The suite (257 tests) covers odds matching, the probability model, risk manager, backtest metrics, settlement, and sanity checks.

## Supported Leagues

Premier League (PL), La Liga (PD), Bundesliga (BL1), Serie A (SA), Ligue 1 (FL1), Eredivisie (DED), Primeira Liga (PPL), Champions League (CL), Europa League (EL), Conference League (UECL), and World Cup (WC).
