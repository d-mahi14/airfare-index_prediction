# Reference Data: DGCA City-Pair Passenger Traffic

This directory contains baseline reference datasets used for computing weights in the APIx (Real-Time Indian Domestic Airfare Price Index).

---

## 1. `dgca_city_pair_traffic.csv`

### Purpose
Provides annual domestic passenger volume across India's primary city-pair airline corridors. These passenger numbers are normalized to compute route weights ($w_r = \frac{\text{Passengers}_r}{\sum \text{Passengers}}$) such that:

$$\sum_{r} w_r = 1.000000$$

### Source Data Information
* **Publishing Authority**: Directorate General of Civil Aviation (DGCA), Government of India.
* **Report Series**: *Handbook on Indian Civil Aviation Statistics* / *Monthly Domestic Traffic by City-Pair (Form A)*.
* **URL**: [https://www.dgca.gov.in](https://www.dgca.gov.in)

### Current Placeholder Status
The current numbers in `dgca_city_pair_traffic.csv` are benchmark estimates with `placeholder: true`.

### Instructions to Update with Official DGCA Data:
1. Download the latest annual or quarterly city-pair traffic table from the official DGCA statistics portal.
2. Update the `annual_passengers` column with exact passenger counts reported by DGCA.
3. If new routes enter the top 20 corridors, add their rows with appropriate IATA codes (`origin`, `destination`, `route_code`).
4. Change the `placeholder` column to `false`.
5. Run the route weight synchronizer to update the database:
   ```powershell
   python -c "from backend.app.utils.weights import sync_route_weights_to_db; sync_route_weights_to_db()"
   ```
