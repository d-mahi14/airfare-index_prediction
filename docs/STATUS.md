# Project Status & Milestone 1 Foundation Audit

**Audit Date:** 2026-09-19  
**Scope:** Milestone 1 Architecture, Database Schema, Constraints, Test Infrastructure

---

## 1. Schema Column Audit

### Table: `airfare_observations`
| Column Name | Type | Nullable | Default | Keys / Constraints |
|---|---|---|---|---|
| `id` | `UUID` (PostgreSQL) / UUID str | No | `uuid.uuid4` | PRIMARY KEY |
| `collection_run_id` | `UUID` | Yes | `NULL` | FK -> `collection_runs.id` (ON DELETE SET NULL), Index |
| `collection_timestamp` | `TIMESTAMP WITH TIME ZONE` | No | `NOW()` / UTC now | Index |
| `source_id` | `INTEGER` | No | - | FK -> `sources.id` (ON DELETE RESTRICT), Index |
| `route_id` | `INTEGER` | No | - | FK -> `routes.id` (ON DELETE RESTRICT), Index |
| `airline_id` | `INTEGER` | Yes | `NULL` | FK -> `airlines.id` (ON DELETE RESTRICT), Index |
| `flight_number` | `VARCHAR(20)` | Yes | `NULL` | - |
| `travel_date` | `DATE` | No | - | Index |
| `lead_days` | `SMALLINT` | No | - | Check (`lead_days >= 0`) |
| `fare_class` | `VARCHAR(50)` | No | `'Economy'` | - |
| `base_fare` | `NUMERIC(10, 2)` | Yes | `NULL` | Check (`base_fare IS NULL OR base_fare <= total_fare`) |
| `taxes` | `NUMERIC(10, 2)` | Yes | `0` | - |
| `fees` | `NUMERIC(10, 2)` | Yes | `0` | - |
| `total_fare` | `NUMERIC(10, 2)` | No | - | Check (`total_fare >= 0`) |
| `currency` | `VARCHAR(3)` | No | `'INR'` | - |
| `availability` | `VARCHAR(20)` | Yes | `'available'` | - |
| `status` | `VARCHAR(20)` | No | `'raw'` | Index (`raw`, `valid`, `rejected`, `duplicate`) |
| `rejection_reason` | `TEXT` | Yes | `NULL` | - |
| `raw_reference` | `TEXT` | Yes | `NULL` | - |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | No | `NOW()` / UTC now | - |

---

### Table: `index_values`
| Column Name | Type | Nullable | Default | Keys / Constraints |
|---|---|---|---|---|
| `id` | `INTEGER` | No | Autoincrement | PRIMARY KEY |
| `index_date` | `DATE` | No | - | Index |
| `apix_value` | `NUMERIC(10, 4)` | No | - | - |
| `methodology_version` | `VARCHAR(20)` | No | `'v1.0'` | - |
| `observation_count` | `INTEGER` | Yes | `NULL` | - |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | No | `NOW()` / UTC now | - |
| **Unique Constraints** | `uq_index_date_version` ON `(index_date, methodology_version)` |

---

### Table: `route_weights`
| Column Name | Type | Nullable | Default | Keys / Constraints |
|---|---|---|---|---|
| `id` | `INTEGER` | No | Autoincrement | PRIMARY KEY |
| `route_id` | `INTEGER` | No | - | FK -> `routes.id` (ON DELETE CASCADE), Index |
| `weight` | `NUMERIC(8, 6)` | No | - | - |
| `effective_date` | `DATE` | No | - | - |
| `is_active` | `BOOLEAN` | No | `TRUE` | - |
| `source` | `TEXT` | Yes | `NULL` | - |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | No | `NOW()` / UTC now | - |
| **Unique Constraints** | `uq_route_weight_date` ON `(route_id, effective_date)` |

---

### Table: `collection_runs`
| Column Name | Type | Nullable | Default | Keys / Constraints |
|---|---|---|---|---|
| `id` | `UUID` | No | `uuid.uuid4` | PRIMARY KEY |
| `source_id` | `INTEGER` | No | - | FK -> `sources.id` (ON DELETE RESTRICT), Index |
| `route_id` | `INTEGER` | No | - | FK -> `routes.id` (ON DELETE RESTRICT), Index |
| `start_time` | `TIMESTAMP WITH TIME ZONE` | No | `NOW()` / UTC now | - |
| `end_time` | `TIMESTAMP WITH TIME ZONE` | Yes | `NULL` | - |
| `records_found` | `INTEGER` | Yes | `0` | - |
| `records_saved` | `INTEGER` | Yes | `0` | - |
| `records_rejected` | `INTEGER` | Yes | `0` | - |
| `error_message` | `TEXT` | Yes | `NULL` | - |

---

## 2. Test Suite Database Engine
- **Current test runner engine:** **SQLite in-memory** (`sqlite:///:memory:` configured in `backend/tests/conftest.py`).
- **Production / Dev engine:** **PostgreSQL 16** via psycopg2 / SQLAlchemy.
- **Observation:** Tests currently run on SQLite with in-memory metadata creation, skipping PostgreSQL-specific features like native UUID operators, timezone functions, and database-level expression indexes.

---

## 3. Deduplication & Unique Constraints Audit
- **`airfare_observations`**: **NO database-level unique or deduplication constraint exists.**
  - Dedup was previously handled solely via application-level query in `scraper/pipelines/storage.py` (`_is_duplicate` matching on `source_id`, `route_id`, `airline_id`, `travel_date`, `fare_class`, `flight_number`, `date(collection_timestamp)`).
  - Missing DB-level unique constraint on `(source_id, flight_number, travel_date, fare_class, collection_date)`.
- **`collection_runs`**: **NO unique constraint.** Runs are identified only by primary key `id`.
- **`index_values`**: Unique constraint `uq_index_date_version` on `(index_date, methodology_version)`.
- **`route_weights`**: Unique constraint `uq_route_weight_date` on `(route_id, effective_date)`.
- **`routes`**: Unique on `route_code` and `uq_route_origin_destination` on `(origin, destination)`.
- **`sources`**: Unique on `name`.
- **`airlines`**: Unique on `name`.
