# Real-Time Indian Domestic Airfare Price Index (APIx)

> An independent, high-frequency airfare data collection and price index system for Indian domestic aviation.

## Project Status — Milestone 1 Hardened ✅

| Component | Status |
|-----------|--------|
| Project structure | ✅ Complete |
| Python environment | ✅ Python 3.12 / 3.13 venv |
| PostgreSQL | ✅ PostgreSQL 16 configured & tested |
| Database schema | ✅ 8 tables, Alembic migrations (001, 002) |
| Hardened constraints | ✅ CHECK constraints, unique dedup keys, timezone precision |
| AirfareObservation model | ✅ Full fee breakdown, departure bands, booking metadata |
| MockCollector | ✅ Synthetic BOM-DEL observations with fee breakdown & timing |
| Fare parser | ✅ Indian currency string parsing |
| Validation pipeline | ✅ Multi-rule validation with fee breakdown tolerance |
| Storage pipeline | ✅ DB-enforced dedup, audit trail, collection run stats |
| CLI collection script | ✅ scripts/run_collection.py |
| MoSPI reference data | ✅ data/reference/mospi_airfare.csv |
| Weighting specification | ✅ DGCA city-pair traffic passenger weighting |
| Tests | ✅ 122 passing (PostgreSQL-backed) |

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- PostgreSQL 16 (or Docker Desktop)
- Node.js 22+ (for frontend dashboard)

### 2. Clone and set up environment

```powershell
# Create virtual environment
python -m venv venv

# Activate
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r backend\requirements.txt
```

### 3. Configure environment

```powershell
# Copy and edit .env
Copy-Item .env.example .env
# Edit .env with your credentials (defaults work for standard PostgreSQL)
```

### 4. Run database migrations

```powershell
alembic -c alembic.ini upgrade head
```

### 5. Run a collection job

```powershell
# Dry run (validate only, no DB write)
python scripts\run_collection.py --dry-run

# Full run (saves to PostgreSQL)
python scripts\run_collection.py --origin BOM --destination DEL --lead-days 7

# Reproducible run with fixed seed
python scripts\run_collection.py --seed 42
```

### 6. Run tests

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
AirfareObservationCreate (Pydantic validation + fee sum check)
        ↓
ObservationValidator (domain rules + bounds)
        ↓
StoragePipeline (DB deduplication + audit log)
        ↓
PostgreSQL (8 hardened tables)
        ↓
Index Engine (DGCA-weighted)  ← Phase 11-12
        ↓
FastAPI (REST API)            ← Phase 14
        ↓
React Dashboard (Vite)        ← Phase 15
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
- Milestone 1: MockCollector (synthetic, seeded data with complete fee breakdowns)
- Future: Real Playwright-based collectors (pending ethical review)

---

## Database Schema

See `backend/app/models/` for full ORM definitions.

| Table | Purpose |
|-------|---------|
| `sources` | Data collection sources |
| `routes` | Origin-destination route pairs |
| `airlines` | Airline operators |
| `collection_runs` | Per-run audit trail (status, blocks, CAPTCHAs) |
| `airfare_observations` | Individual fare quotes with fee breakdown, departure band, synthetic & lead flags |
| `index_values` | Computed daily/weekly APIx values (overall and variant indices) |
| `route_weights` | DGCA city-pair passenger traffic weights with validity periods |
| `lead_time_weights` | Advance booking curve weights (T+1, T+7, T+15, T+30, T+45) |

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

The APIx is computed using DGCA passenger traffic city-pair weights:

```
Route Index = (Current representative route fare / Base-period fare) × 100

APIx = Σ(route_weight × route_index)
```

Route weights are derived directly from published DGCA city-pair passenger traffic statistics.

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
# Run all tests against PostgreSQL
python -m pytest -v

# Run with coverage
python -m pytest --cov=backend --cov=scraper -v

# Run specific constraint or migration tests
python -m pytest backend\tests\test_constraints.py -v
python -m pytest backend\tests\test_migration.py -v
```

### Test Coverage (Milestone 1 Hardened)

| Module | Tests | Description |
|--------|-------|-------------|
| Lead-time calculation | 12 | Asia/Kolkata date diffs & edge cases |
| Pydantic schemas | 22 | Type validation, fee breakdown sum checks, band derivations |
| Fare parser | 38 | Indian currency formats, symbols, normalizations |
| Validation pipeline | 14 | Hard failure rules, bounds, plausibility |
| Storage pipeline | 12 | Dedup handling, collection run lifecycle |
| MockCollector | 13 | Deterministic seeded observations, fee breakdown |
| Database constraints | 9 | PostgreSQL CHECK constraints, 5-tuple dedup key, unique periods |
| Alembic migrations | 2 | 001 → 002 upgrade, downgrade, data migration |
| **Total** | **122** | **100% passing** |

---

## Known Limitations (Milestone 1)

1. **Synthetic data only** — MockCollector, not real scraped data
2. **No real index computed** — Index construction is Phase 11-12
3. **FastAPI stub only** — Full API endpoints in Phase 14
4. **React dashboard initial build** — Integrated live in Phase 15
5. **DGCA validation pending** — Phase 17, 30-day backtesting data

---

## Implementation Phases

- [x] Phase 0: Repository audit
- [x] Phase 1: Project/environment setup
- [x] Phase 2: Database schema & hardening (Alembic 001, 002)
- [x] Phase 3: Airfare observation model with fee breakdown & flight metadata
- [x] Phase 4: MockCollector with fee breakdown & schedules
- [x] Phase 5: Raw data storage
- [x] Phase 6: Cleaning + validation + PostgreSQL automated tests
- [ ] Phase 7: Multiple routes
- [ ] Phase 8: Lead-time collection
- [ ] Phase 9: Multiple permitted sources (real collectors)
- [ ] Phase 10: PostgreSQL integration verified
- [ ] Phase 11: Route-level index
- [ ] Phase 12: Weighted overall APIx (DGCA city-pair weights)
- [ ] Phase 13: Daily scheduled index
- [ ] Phase 14: FastAPI backend
- [ ] Phase 15: React dashboard
- [ ] Phase 16: MoSPI comparison
- [ ] Phase 17: DGCA 30-day backtesting
- [ ] Phase 18: Automated testing (expansion)
- [ ] Phase 19: Documentation
- [ ] Phase 20: Optional Jan 2027 forecasting
