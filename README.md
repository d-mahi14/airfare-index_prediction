# Real-Time Indian Domestic Airfare Price Index (APIx)

> An independent, high-frequency airfare data collection and price index system for Indian domestic aviation.

## Project Status — Milestone 1 ✅

| Component | Status |
|-----------|--------|
| Project structure | ✅ Complete |
| Python environment | ✅ Python 3.12 venv |
| PostgreSQL (Docker) | ✅ Configured |
| Database schema | ✅ 7 tables, Alembic migrations |
| AirfareObservation model | ✅ Pydantic v2 with full validation |
| MockCollector | ✅ Synthetic BOM-DEL observations |
| Fare parser | ✅ Indian currency string parsing |
| Validation pipeline | ✅ 9 validation rules |
| Storage pipeline | ✅ Duplicate detection, audit trail |
| CLI collection script | ✅ scripts/run_collection.py |
| MoSPI reference data | ✅ data/reference/mospi_airfare.csv |
| Tests | ✅ 109 passing |

---

## Quick Start

### 1. Prerequisites

- Python 3.11+ (3.12 installed)
- Docker Desktop (for PostgreSQL)
- Node.js 22+ (for frontend — Phase 15)

### 2. Clone and set up environment

```powershell
# Clone the repo
cd airfare-sih

# Create virtual environment
py -3.12 -m venv venv

# Activate
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r backend\requirements.txt
```

### 3. Configure environment

```powershell
# Copy and edit .env
Copy-Item .env.example .env
# Edit .env with your credentials (defaults work for Docker)
```

### 4. Start PostgreSQL

```powershell
docker-compose up -d
```

### 5. Run database migrations

```powershell
alembic -c alembic.ini upgrade head
```

### 6. Run a collection job

```powershell
# Dry run (validate only, no DB write)
python scripts\run_collection.py --dry-run

# Full run (saves to PostgreSQL)
python scripts\run_collection.py --origin BOM --destination DEL --lead-days 7

# Reproducible run with fixed seed
python scripts\run_collection.py --seed 42
```

### 7. Run tests

```powershell
python -m pytest -v
```

---

## Architecture

```
Airline/OTA Sources (permitted)
        ↓
Playwright/Scrapy Collectors  ← Phase 9
        ↓
MockCollector (Milestone 1)   ← Current
        ↓
Raw JSON saved to data/raw/
        ↓
AirfareObservationCreate (Pydantic validation)
        ↓
ObservationValidator (domain rules)
        ↓
StoragePipeline
        ↓
PostgreSQL (Docker)
        ↓
Index Engine (Phase 11-12)    ← Upcoming
        ↓
FastAPI (Phase 14)            ← Upcoming
        ↓
React Dashboard (Phase 15)    ← Upcoming
```

---

## Data Sources

### MoSPI CPI Airfare (Reference Only)
- File: `data/reference/mospi_airfare.csv`
- Source: MoSPI e-Sankhyiki portal
- Content: Monthly CPI sub-index for domestic airfare (2025-01 to 2026-08)
- Base year: 2024 = 100
- **NOT raw fare data** — used only for benchmark comparison
- CPI weight: 0.01784347 (share of airfare in Urban CPI basket)

### Online Airfare Observations (Primary)
- Collected independently from permitted airline/OTA sources
- See `scraper/collectors/` for collector implementations
- Milestone 1: MockCollector (synthetic, seeded data)
- Future: Real Playwright-based collectors (pending ethical review)

---

## Database Schema

See `backend/app/models/` for full ORM definitions.

| Table | Purpose |
|-------|---------|
| `sources` | Data collection sources |
| `routes` | Origin-destination route pairs |
| `airlines` | Airline operators |
| `collection_runs` | Per-run audit trail |
| `airfare_observations` | Individual fare quotes |
| `index_values` | Computed daily APIx values |
| `route_weights` | PSD route weights (Phase 11) |

---

## Route Configuration

Routes are defined in `scraper/config/routes.yaml`.

Currently active:
- BOM-DEL (Mumbai → Delhi) ✅
- DEL-BOM (Delhi → Mumbai) ✅
- BOM-BLR (Mumbai → Bengaluru) ✅
- DEL-BLR (Delhi → Bengaluru) ✅

---

## Index Methodology (Phase 11-12)

The APIx will be computed as:

```
Route Index = (Current representative route fare / Base-period fare) × 100

APIx = Σ(route_weight × route_index)
```

Route weights will be provided from the PSD specification.

---

## Ethical Scraping Policy

This project follows strict ethical data collection principles:

1. ✅ Robots.txt checked before any collector implementation
2. ✅ ToS reviewed for each source
3. ✅ Rate limits respected (configurable delay in .env)
4. ✅ No CAPTCHA bypassing
5. ✅ No bot protection evasion
6. ✅ No authentication bypass
7. ✅ No private/user-specific data collection
8. ✅ Synthetic/mock data used for pipeline development

---

## Testing

```powershell
# Run all tests
python -m pytest -v

# Run with coverage
python -m pytest --cov=backend --cov=scraper -v

# Run specific test file
python -m pytest backend\tests\test_lead_time.py -v
```

### Test Coverage (Milestone 1)

| Module | Tests |
|--------|-------|
| Lead-time calculation | 12 |
| Pydantic schemas | 20 |
| Fare parser | 38 |
| Validation pipeline | 15 |
| Storage pipeline | 12 |
| MockCollector | 13 |
| **Total** | **109** |

---

## Known Limitations (Milestone 1)

1. **Synthetic data only** — MockCollector, not real scraped data
2. **No real index computed** — Index construction is Phase 11-12
3. **FastAPI stub only** — Full API is Phase 14
4. **No frontend** — React dashboard is Phase 15
5. **DGCA validation pending** — Phase 17, data to be downloaded
6. **Route weights TBD** — PSD specification not yet provided

---

## Implementation Phases

- [x] Phase 0: Repository audit
- [x] Phase 1: Project/environment setup
- [x] Phase 2: Database schema
- [x] Phase 3: Airfare observation model
- [x] Phase 4: One collector (MockCollector)
- [x] Phase 5: Raw data storage
- [x] Phase 6: Cleaning + validation + tests
- [ ] Phase 7: Multiple routes
- [ ] Phase 8: Lead-time collection
- [ ] Phase 9: Multiple permitted sources (real collectors)
- [ ] Phase 10: PostgreSQL integration verified
- [ ] Phase 11: Route-level index
- [ ] Phase 12: Weighted overall APIx
- [ ] Phase 13: Daily scheduled index
- [ ] Phase 14: FastAPI backend
- [ ] Phase 15: React dashboard
- [ ] Phase 16: MoSPI comparison
- [ ] Phase 17: DGCA 30-day backtesting
- [ ] Phase 18: Automated testing (expansion)
- [ ] Phase 19: Documentation
- [ ] Phase 20: Optional Jan 2027 forecasting
