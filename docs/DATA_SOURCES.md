# Data Sources

This document describes the external data sources used by the Airfare Index Prediction project for validation, backtesting, and production.

## Kaggle Dataset: Airfare ML: Predicting Flight Fares

- **URL:** [https://www.kaggle.com/datasets/yashdharme36/airfare-ml-predicting-flight-fares](https://www.kaggle.com/datasets/yashdharme36/airfare-ml-predicting-flight-fares)
- **License:** CC0: Public Domain
- **Description:** A dataset of 452,088 flight records across the Indian domestic market, originally collected for machine learning projects.

### Known Facts and Constraints

- **Rows & Columns:** 452,088 rows, no missing values.
- **Columns:** `Date_of_journey`, `Journey_day`, `Airline`, `Flight_code`, `Class`, `Source`, `Departure`, `Total_stops`, `Arrival`, `Destination`, `Duration_in_hours`, `Days_left`, `Fare`.
- **Fare Makeup:** The `Fare` column represents the total fare. There is no tax or fee breakup provided (base_fare, taxes, udf_psf, convenience_fee, other_fees are considered NULL or part of total).
- **Temporal Constraint:** The difference `Date_of_journey - Days_left` resolves to a single constant date (`2023-01-15`) for all rows. This means the dataset is a ONE-DAY snapshot of prices for many future travel dates and lead times. It is **not** a multi-day collection history, and therefore cannot be used to build a valid daily index time series. It is used exclusively to validate our methodology's mechanics (loading, weighting, stratification, carrier price structures, lead-time elasticity) and not to track day-over-day market prices.
