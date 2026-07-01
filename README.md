# OreLens — Junior Mining Dilution & Drill Intelligence

Turns regulatory filings and newswire text into daily-updating metrics: an
ABCDF near-term dilution risk grade, warrant overhang maps, and three
AI-driven scanners for drill programs, high-grade breakouts, and
value-momentum setups across TSX / TSX-V / CSE / ASX juniors.

## Architecture

```
backend/  FastAPI + SQLAlchemy + PostgreSQL (TimescaleDB)
  app/services/drill_parser.py   Drill Result Engine — regex/NLP intercept extraction,
                                 gram-meter benchmarks, hit-ratio parsing, percentile ranks
  app/services/grading.py        ABCDF dilution model (pure functions, fully unit-tested)
  app/services/ingest.py         FMP market data · SEDAR+/EDGAR filings · newswire RSS ·
                                 LLM extraction of cash/burn/warrant tables from PDFs
  app/services/scanners.py       The three scanner queries
  app/jobs/nightly.py            Cron orchestrator: prices → filings → wires → grades
frontend/ Next.js 14 + TypeScript + Tailwind
  app/page.tsx                   Tabbed scanner dashboard (sort, commodity + tier filters)
  app/ticker/[symbol]/page.tsx   Chart w/ 50-200 SMA · dilution gauge · overhang map ·
                                 capital structure · drill timeline + auto-comparison text
```

## Quick start (runs on seed data, no API keys needed)

```bash
# 1. Database + services
docker compose up -d db

# 2. Backend
cd backend
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg2://orelens:orelens@localhost:5432/orelens
python -m app.seed                 # demo universe: prices, warrants, drill results, grades
uvicorn app.main:app --reload      # http://localhost:8000/docs

# 3. Frontend
cd ../frontend
npm install && npm run dev         # http://localhost:3000
```

For heavy price history, enable the hypertable once:
```sql
SELECT create_hypertable('daily_prices', 'day', migrate_data => true);
```

## Live data — environment variables

| Var | Purpose |
|---|---|
| `FMP_API_KEY` | Financial Modeling Prep — daily close/volume/shares outstanding (`.TO`, `.V`, `.CN`, `.AX` suffixes handled) |
| `ANTHROPIC_API_KEY` | LLM extraction of cash, burn rate, and the warrant/option table from MD&A + interim FS PDFs |
| `DATABASE_URL` | Postgres connection string |

### Data source notes
- **SEDAR+** has no official public API. `jobs/nightly.sync_filings` is the
  integration point: wire per-issuer SEDAR+ feeds or a commercial mirror
  (e.g. a filings data vendor) there, pipe PDFs through
  `ingest.pdf_to_text` → `ingest.extract_capital_structure`.
- **EDGAR** works out of the box for dual-listed names via
  `ingest.fetch_edgar_recent` (set a real contact in the User-Agent — SEC
  requires it).
- **Newswires**: GlobeNewswire's mining-subject RSS is wired; PRNewswire and
  Accesswire endpoints are in `ingest.WIRE_FEEDS` — swap in your licensed
  feed URLs for full-body text (RSS summaries alone miss intercepts buried
  deep in releases).

## Nightly sync (23:00 EST weeknights)

Two redundant mechanisms, pick one:
1. **In-process**: APScheduler cron inside the API (already running).
2. **External**: `.github/workflows/nightly.yml` hits `POST /api/jobs/nightly`
   (set `BACKEND_URL` secret). Also usable from any crontab:
   `0 23 * * 1-5 curl -X POST https://api.yourdomain.com/api/jobs/nightly`

## The ABCDF model

```
Cash Runway            = cash / monthly burn
Upcoming Drill Cost    = planned holes × avg depth × cost per meter
Adjusted Runway        = (cash − drill cost) / monthly burn
ITM Warrant Cash       = Σ qty × strike, for live tranches with strike < price
A  adj. runway > 12mo OR ITM cash ≥ 12mo burn + drilling; overhang < 15% float
B  6–12mo   C  3–6mo   D  < 3mo   F  < 1mo, or ≥25% of float unlocking this week
```

Run the model's test suite: `cd backend && pytest` (15 tests cover the
grading matrix edge cases and the intercept parser syntaxes).

## Deployment

`.github/workflows/deploy.yml` runs tests, then deploys the backend to a
DigitalOcean droplet over SSH (swap the step for AWS ECS if preferred) and
the frontend to Vercel. Required secrets: `DO_HOST`, `DO_USER`, `DO_SSH_KEY`,
`VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`, `BACKEND_URL`.

## Disclaimers

Seed data is illustrative, not live market data. Nothing produced by the
grading model or scanners is investment advice; grades are mechanical outputs
of the stated formulas and depend entirely on filing-extraction accuracy —
always verify against the source filings before acting.
