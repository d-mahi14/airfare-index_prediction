# Open Questions & Investigation Backlog

**Last Updated:** 2026-09-19  
**Repository:** `airfare-index_prediction` (APIx)

---

## Active Questions & Design Considerations

| ID | Category | Question / Topic | Status | Notes / Next Steps |
|---|---|---|---|---|
| Q-01 | Collection / Compliance | Which permitted OTA / airline endpoints provide robots.txt-compliant access for Phase 9 live scrapers? | Open | Conduct automated robots.txt and ToS audit before building any live Playwright collectors. |
| Q-02 | Weighting Methodology | Exact granularity of DGCA city-pair quarterly traffic reports (seat capacity vs. passenger volume). | Open | Ingest DGCA passenger statistics to compute base route weights for Phase 11-12. |
| Q-03 | Imputation & Outliers | Outlier detection threshold and imputation methodology when specific lead-time flight observations are missing or blocked. | Open | Define trimmed mean / median or carrier-weighted interpolation for missing cells. |
| Q-04 | Advance Booking Curve | Exact lead-time weights distribution across T+1, T+7, T+15, T+30, and T+45 windows. | Open | Calibrate weights based on DGCA domestic booking distribution patterns. |
