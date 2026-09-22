# Kaggle Historical Data Validation Report

> [!IMPORTANT]
> **Constraint Notice:** This dataset resolves to a single constant collection date (`2023-01-15`) for all observations. 
> Therefore, **no daily index was or could be validated from this file**. This report 
> evaluates ONLY the method's mechanics (loading, stratification, carrier price structures, and lead-time elasticity patterns).
> Furthermore, this validates mechanics against 2023 data, not current market prices.

## 1. Lead-Time Elasticity Curves (1-50 days)

The following table shows the average total fare by lead days, providing finer-grained visibility beyond the standard 5 buckets.

| Lead Days | Avg Fare (INR) | Observation Count |
| :--- | :--- | :--- |
| 1 | 17438.21 | 1497 |
| 2 | 16666.33 | 1491 |
| 3 | 16130.49 | 1524 |
| 4 | 15334.43 | 1498 |
| 5 | 16463.72 | 1497 |
| 6 | 16347.69 | 1473 |
| 7 | 16661.65 | 1462 |
| 8 | 14865.47 | 1497 |
| 9 | 14673.41 | 1498 |
| 10 | 16194.36 | 1563 |
| 11 | 15000.52 | 1531 |
| 12 | 14562.2 | 1576 |
| 13 | 14864.05 | 1545 |
| 14 | 17287.81 | 1521 |
| 15 | 14428.95 | 1548 |
| 20 | 13948.19 | 1551 |
| 25 | 13195.74 | 1565 |
| 30 | 12856.48 | 1603 |
| 35 | 13634.82 | 1488 |
| 40 | 12921.97 | 1589 |
| 45 | 12713.09 | 1594 |
| 50 | 13050.68 | 1590 |


## 2. Carrier Price Structure

Average fares across the airlines in the dataset:

| Airline | Count | Avg Fare | Median Fare | Std Dev |
| :--- | :--- | :--- | :--- | :--- |
| Air India | 13816 | 23657.98 | 17973.5 | 16976.1 |
| Vistara | 20511 | 20818.55 | 12675.0 | 17380.32 |
| StarAir | 62 | 9792.77 | 4688.0 | 8647.75 |
| Indigo | 28519 | 8128.98 | 7500.0 | 3457.45 |
| GO FIRST | 4195 | 7679.39 | 6532.0 | 3736.9 |
| SpiceJet | 3247 | 7678.17 | 7205.0 | 2963.24 |
| AirAsia | 4538 | 7106.63 | 6407.0 | 3020.96 |
| AllianceAir | 393 | 4077.5 | 3799.0 | 738.62 |
| AkasaAir | 2230 | 3570.03 | 2893.0 | 1762.66 |


## 3. Route-Level Fare Distribution Checks

Summary of fare distribution across all origin-destination routes in the dataset:

| Route | Count | Min Fare | Avg Fare | Max Fare |
| :--- | :--- | :--- | :--- | :--- |
| AMD-BLR | 1111 | 3700.0 | 7216.28 | 28972.0 |
| AMD-BOM | 552 | 1999.0 | 4397.18 | 64849.0 |
| AMD-CCU | 260 | 6698.0 | 10371.87 | 34057.0 |
| AMD-DEL | 2511 | 2538.0 | 12056.7 | 81834.0 |
| AMD-HYD | 227 | 4919.0 | 7764.93 | 47937.0 |
| AMD-MAA | 150 | 3924.0 | 9265.59 | 34320.0 |
| BLR-AMD | 254 | 5495.0 | 6813.74 | 19768.0 |
| BLR-BOM | 1772 | 2464.0 | 5165.97 | 85601.0 |
| BLR-CCU | 1330 | 6053.0 | 8326.84 | 27284.0 |
| BLR-DEL | 7893 | 4972.0 | 14193.37 | 86217.0 |
| BLR-HYD | 769 | 2305.0 | 6054.88 | 35520.0 |
| BLR-MAA | 389 | 1400.0 | 2468.6 | 10444.0 |
| BOM-AMD | 275 | 1854.0 | 8698.62 | 78270.0 |
| BOM-BLR | 3527 | 2252.0 | 11510.3 | 90437.0 |
| BOM-CCU | 936 | 6677.0 | 13292.28 | 89866.0 |
| BOM-DEL | 10872 | 3757.0 | 17731.69 | 109645.0 |
| BOM-HYD | 586 | 3423.0 | 12537.44 | 72674.0 |
| BOM-MAA | 629 | 2720.0 | 9529.34 | 82351.0 |
| CCU-AMD | 120 | 6682.0 | 8514.21 | 15117.0 |
| CCU-BLR | 677 | 6195.0 | 8699.44 | 23517.0 |
| CCU-BOM | 1243 | 7215.0 | 10696.81 | 60369.0 |
| CCU-DEL | 4474 | 5982.0 | 15784.15 | 86689.0 |
| CCU-HYD | 222 | 5999.0 | 8937.16 | 22824.0 |
| CCU-MAA | 130 | 6507.0 | 11874.14 | 42785.0 |
| DEL-AMD | 714 | 2589.0 | 14090.23 | 64243.0 |
| DEL-BLR | 3878 | 4626.0 | 9807.53 | 86922.0 |
| DEL-BOM | 13877 | 3818.0 | 19257.42 | 110441.0 |
| DEL-CCU | 1971 | 5587.0 | 10854.2 | 81355.0 |
| DEL-HYD | 1136 | 4609.0 | 15888.43 | 77972.0 |
| DEL-MAA | 864 | 6018.0 | 13550.0 | 92601.0 |
| HYD-AMD | 139 | 5237.0 | 7217.9 | 17081.0 |
| HYD-BLR | 613 | 2460.0 | 5927.9 | 25107.0 |
| HYD-BOM | 1575 | 3008.0 | 11297.49 | 102321.0 |
| HYD-CCU | 533 | 5527.0 | 9128.38 | 25779.0 |
| HYD-DEL | 3779 | 5009.0 | 14646.68 | 63142.0 |
| HYD-MAA | 548 | 3396.0 | 7253.13 | 23317.0 |
| MAA-AMD | 136 | 3819.0 | 6308.87 | 13551.0 |
| MAA-BLR | 326 | 1494.0 | 2387.64 | 10614.0 |
| MAA-BOM | 867 | 2622.0 | 6929.22 | 25342.0 |
| MAA-CCU | 475 | 5203.0 | 8802.25 | 44736.0 |
| MAA-DEL | 4572 | 6029.0 | 16111.75 | 92689.0 |
| MAA-HYD | 599 | 3471.0 | 7681.33 | 17249.0 |

