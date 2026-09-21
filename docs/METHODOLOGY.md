# APIx Methodology Specification: Real-Time Indian Domestic Airfare Price Index

## 1. Executive Summary

The **APIx (Airfare Price Index)** is an independent, high-frequency, passenger-weighted price index measuring temporal changes in Indian domestic economy airfares. Unlike official monthly consumer price indices (e.g. MoSPI CPI sub-index 07.3.3.1.2.01) which report historical aggregate expenditure indices, APIx provides daily, weekly, and monthly airfare price index series constructed directly from verified observed market quotes across defined advance-purchase horizons.

---

## 2. Multi-Stage Aggregation Hierarchy

APIx is constructed through a three-tier aggregation framework:

```
Tier 1: Elementary Stratum Indices (Route x Lead Window)
        Jevons Geometric Mean of Matched Offers
                         ↓
Tier 2: Route-Level Indices
        Advance Booking Curve Weighted Aggregation across Lead Windows (T+1 .. T+45)
                         ↓
Tier 3: National Composite APIx
        DGCA City-Pair Passenger Traffic Weighted Aggregation with Chain-Linking
```

---

## 3. Mathematical Formulations

### 3.1 Elementary Index: Matched-Model Jevons Index

At the elementary level, quotes are grouped into strata defined by the 3-tuple:
$$\text{Stratum } s = (\text{Carrier}, \text{Departure Band}, \text{Fare Class})$$
where:
- **Carrier**: Airline operating code (e.g., `6E`, `AI`, `QP`, `SG`).
- **Departure Band**: Time-of-day period (`early_morning`, `morning`, `afternoon`, `evening`, `night`).
- **Fare Class**: Booking cabin (`economy`, `premium_economy`, `business`).

For a given route $r$ and target lead window $l$ at period $t$, let $S_{\text{matched}} = S_{r,l,t} \cap S_{r,l,0}$ denote the set of strata observed in both the current period $t$ and baseline period $0$.

For each matched stratum $s \in S_{\text{matched}}$:
1. Compute the geometric mean price in the current period:
   $$\bar{p}_{s, t} = \left( \prod_{i=1}^{k_s} p_{s, t, i} \right)^{1/k_s}$$
2. Compute the geometric mean price in the base period:
   $$\bar{p}_{s, 0} = \left( \prod_{j=1}^{m_s} p_{s, 0, j} \right)^{1/m_s}$$
3. Compute the stratum price relative:
   $$R_s = \frac{\bar{p}_{s, t}}{\bar{p}_{s, 0}}$$

The elementary Jevons index for cell $(r, l)$ is:
$$I_{r, l, t} = \left( \prod_{s \in S_{\text{matched}}} R_s \right)^{1 / |S_{\text{matched}}|} \times \text{Base Value}$$

#### Unmatched Stratum Fallback
If changes in airline flight schedules result in $|S_{\text{matched}}| = 0$ (i.e. no exact stratum matches between periods), the engine applies an unmatched cell fallback by comparing the geometric mean of all current stratum prices to the geometric mean of all baseline stratum prices:
$$I_{r, l, t}^{\text{fallback}} = \frac{\left( \prod_{s \in S_t} \bar{p}_{s, t} \right)^{1 / |S_t|}}{\left( \prod_{s \in S_0} \bar{p}_{s, 0} \right)^{1 / |S_0|}} \times \text{Base Value}$$
This ensures price index continuity while logging a fallback metadata flag.

---

### 3.2 Lead-Time Horizon Aggregation

Airfare volatility is heavily governed by the booking horizon. APIx aggregates five standard advance-purchase windows:
$$L = \{T+1, T+7, T+15, T+30, T+45\}$$

Each lead window $l \in L$ is assigned a booking curve weight $w_l$ from `lead_time_weights.yaml` (default $w_l = 0.20$ in baseline equal-weight specification).

When a lead window is unavailable, the remaining active lead windows are dynamically reweighted:
$$w_l^* = \frac{w_l}{\sum_{l' \in L_{\text{present}}} w_{l'}}, \quad \text{where } \sum_{l \in L_{\text{present}}} w_l^* = 1.000000$$

The route-level index $I_{r, t}$ is:
$$I_{r, t} = \sum_{l \in L_{\text{present}}} w_l^* \cdot I_{r, l, t}$$

---

### 3.3 National Route Aggregation & Chain-Linking

Route indices are aggregated into the national composite index using annual passenger traffic weights derived from official DGCA city-pair statistics:
$$w_r = \frac{\text{Annual Passengers}_r}{\sum_{r' \in R} \text{Annual Passengers}_{r'}}$$

For present active routes $R_{\text{present}}$:
$$w_r^* = \frac{w_r}{\sum_{r' \in R_{\text{present}}} w_{r'}}$$

The composite APIx value is:
$$I_t = \sum_{r \in R_{\text{present}}} w_r^* \cdot I_{r, t}$$

#### Annual Chain-Linking
When DGCA traffic weights are updated at link period $T_{\text{link}}$:
$$I_t^{\text{chained}} = I_{T_{\text{link}}}^{\text{chained}} \times \frac{I_t^{(k)}}{I_{T_{\text{link}}}^{(k)}}$$
where $I_t^{(k)}$ is the index computed with new weight schedule $k$. This prevents artificial discontinuities or index level jumps when route network traffic shares shift.

---

## 4. Fare Decomposition Variants

To analyze the macroeconomic drivers of airfare inflation, APIx computes three distinct price variants:

| Variant | Price Definition ($p$) | Analytical Purpose |
| :--- | :--- | :--- |
| `total_fare` | Base + Taxes + UDF/PSF + Convenience Fee | **Primary APIx series**: Actual out-of-pocket passenger expenditure. |
| `base_fare_only` | Base Fare | **Airline revenue yield**: Measures airline dynamic pricing free of statutory pass-throughs. |
| `taxes_and_fees` | GST + UDF + PSF + Convenience Fee | **Regulatory & infrastructure burden**: Measures statutory tax and airport development fees. |

---

## 5. Cell Coverage Metric

For each computation period, the data coverage ratio is calculated as:
$$\text{Coverage} = \frac{\text{Number of Valid (Route } \times \text{ Lead) Cells}}{\text{Total Expected Cells in Basket}} = \frac{N_{\text{valid}}}{|R| \times |L|}$$
A complete basket across 4 routes and 5 lead windows has 20 cells. If 18 cells contain valid observations, coverage is $90.0\%$.

---

## 6. Synthetic Data Integrity Policy

1. **Non-Synthetic Default**: Official index series are computed exclusively from non-synthetic observations (`is_synthetic=False`).
2. **Refusal on Synthetic Feeding**: If synthetic rows are supplied to `compute_apix` without `--allow-synthetic`, execution halts with a `ValueError`.
3. **Explicit Stamping**: When `--allow-synthetic` is enabled (for testing and pipeline validation), the variant is automatically stamped with `_synthetic` (e.g. `overall_synthetic`, `base_fare_only_synthetic`). Synthetic index values can never be written under official production variant names.

---

## 7. Axiomatic Index Properties Satisfied

The APIx Jevons formulation mathematically satisfies standard microeconomic index number axioms:
1. **Identity**: If prices in period $t$ equal base period $0$, $I_t = 100.0$.
2. **Proportionality / Homogeneity**: If all current prices are scaled by constant factor $k > 0$, $I_t \to k \cdot I_t$.
3. **Commensurability / Scale Invariance**: Index values are independent of currency units.
4. **Permutation Invariance**: Shuffling the order of observations produces identical index values.
5. **Time Reversal**: For elementary matched strata, $I_{0, t} = 1 / I_{t, 0}$.
