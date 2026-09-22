# Architecture Decisions Record (ADR) — Milestone 1 Hardening

**Date:** 2026-09-19  
**Status:** Approved & Implemented  
**Scope:** Milestone 1 Foundation Hardening

---

## 1. Fee Breakdown Architecture
- **Decision:** Split the generic `fees` column in `airfare_observations` into four granular components:
  1. `taxes` (GST / Government levies)
  2. `udf_psf` (User Development Fee & Passenger Service Fee)
  3. `convenience_fee` (Platform booking / gateway convenience fees)
  4. `other_fees` (Airline surcharges / miscellaneous fees)
- **Migration Strategy:** Non-destructive Alembic migration (002). Existing values in `fees` were automatically migrated to `other_fees` prior to dropping the legacy column.
- **Validation Rule:** Pydantic schema and pipeline validator enforce that `total_fare == base_fare + taxes + udf_psf + convenience_fee + other_fees` within a `0.05` INR tolerance.

---

## 2. Deduplication & Timezone Strategy
- **Decision:** Enforce a hard database-level unique constraint on:
  ```sql
  UNIQUE (source_id, flight_number, travel_date, fare_class, collection_date)
  ```
- **Timezone Resolution:** Indian domestic airfare pricing operates on Indian Standard Time (`Asia/Kolkata` / `UTC+05:30`). While `collection_timestamp` is stored in UTC with timezone for absolute audit logging, `collection_date` is explicitly indexed as the calendar date in `Asia/Kolkata`.
- **Lead Days Calculation:** `lead_days = travel_date - collection_date` (evaluated in `Asia/Kolkata`).

---

## 3. Database-Level CHECK Constraints
- **Decision:** Guard data integrity directly in PostgreSQL:
  - `total_fare > 0` and `base_fare > 0`
  - `base_fare <= total_fare`
  - `lead_days >= 0`
  - `dep_band IN ('early', 'morning', 'afternoon', 'evening', 'night')`
  - `target_lead_window IN (1, 7, 15, 30, 45)`

---

## 4. Weighting Specification (DGCA Passenger Traffic)
- **Decision:** Route weights in `route_weights` and advance booking curve weights in `lead_time_weights` are derived from official **DGCA (Directorate General of Civil Aviation) city-pair passenger traffic statistics**, replacing legacy PSD placeholder references.
- **Validity Periods:** Both `route_weights` and `lead_time_weights` support `valid_from` and `valid_to` date ranges to allow weights to adjust quarterly or annually as DGCA releases new traffic numbers.

---

## 5. Collection Run Audit Trail & Anti-Bot Tracking
- **Decision:** Added `status` (`running`, `completed`, `failed`, `partial`), `blocked_count` (HTTP 403 blocks), and `captcha_count` (bot challenge detection) to `collection_runs`.
- **Route Decoupling:** Made `route_id` nullable on `collection_runs` so a single collection run can encompass multiple routes or full scraping cycles.

---

## 6. PostgreSQL Test Engine Integration
- **Decision:** Migrated database testing from SQLite in-memory to PostgreSQL (`airfare_test_db`).
- **Validation Coverage:** Added automated tests verifying Alembic migration `upgrade` and `downgrade` reversibility, data preservation, and database-level constraint enforcement.

---

## 7. Index Construction & PSD Alignment Analysis
- **Decision:** Formal evaluation of Passenger Share Distribution (PSD) vs. DGCA passenger-weighted Jevons aggregation model.
- **Current Alignment Status:** Fully Satisfies the specification defined in `docs/METHODOLOGY.md` (matched-model Jevons at elementary level, lead-time booking curve weighting, and DGCA city-pair Passenger Share Distribution weighting at route level).
- **Potential Variant Trade-Offs & Future Enhancements:**
  1. *Matched-Model Jevons (Current)* vs. *Törnqvist / Laspeyres Weighted Formula*: Jevons is unweighted geometric mean of price relatives at elementary stratum level, satisfying transitivity and time-reversal axioms without requiring real-time intra-day passenger transaction volume weights.
  2. *Lead-Time Fixed Booking Curve* vs. *Dynamic Dynamic Lead-Time PSD Weights*: Current lead-time weights use static 5-window advance purchase distributions ($w_l = 0.20$). If quarterly DGCA advance booking distribution data becomes available, `lead_time_weights` table supports dynamic validity ranges (`valid_from` / `valid_to`).
  3. *Chain-Linking Policy*: Annual chain-linking formula ($I_t^{\text{chained}} = I_{T_{\text{link}}}^{\text{chained}} \cdot \frac{I_t^{(k)}}{I_{T_{\text{link}}}^{(k)}}$) prevents level jumps when DGCA route traffic weights shift.

