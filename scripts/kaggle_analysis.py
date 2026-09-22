"""
scripts/kaggle_analysis.py

Generates validation analysis report for Kaggle Historical Data.
"""
import logging
import os
import pandas as pd

from backend.app.database import get_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_report():
    engine = get_engine()
    
    logger.info("Fetching Kaggle historical observations from DB...")
    
    # query to fetch all required data
    query = """
    SELECT 
        o.total_fare,
        o.lead_days,
        o.target_lead_window,
        r.route_code,
        a.name as airline_name
    FROM airfare_observations o
    JOIN sources s ON o.source_id = s.id
    JOIN routes r ON o.route_id = r.id
    JOIN airlines a ON o.airline_id = a.id
    WHERE s.name = 'external_historical_kaggle_2023'
    """
    
    df = pd.read_sql(query, engine)
    logger.info(f"Loaded {len(df)} rows for analysis.")
    
    if len(df) == 0:
        logger.error("No data found for kaggle source.")
        return
        
    report_lines = []
    
    report_lines.append("# Kaggle Historical Data Validation Report\n")
    report_lines.append("> [!IMPORTANT]")
    report_lines.append("> **Constraint Notice:** This dataset resolves to a single constant collection date (`2023-01-15`) for all observations. ")
    report_lines.append("> Therefore, **no daily index was or could be validated from this file**. This report ")
    report_lines.append("> evaluates ONLY the method's mechanics (loading, stratification, carrier price structures, and lead-time elasticity patterns).")
    report_lines.append("> Furthermore, this validates mechanics against 2023 data, not current market prices.\n")
    
    report_lines.append("## 1. Lead-Time Elasticity Curves (1-50 days)\n")
    report_lines.append("The following table shows the average total fare by lead days, providing finer-grained visibility beyond the standard 5 buckets.\n")
    
    # Lead-time elasticity across all flights
    lead_time_agg = df.groupby('lead_days')['total_fare'].agg(['count', 'mean']).reset_index()
    lead_time_agg['mean'] = lead_time_agg['mean'].round(2)
    report_lines.append("| Lead Days | Avg Fare (INR) | Observation Count |")
    report_lines.append("| :--- | :--- | :--- |")
    # Show first 15 days, then every 5th day to keep it readable
    for _, row in lead_time_agg.iterrows():
        ld = int(row['lead_days'])
        if ld <= 15 or ld % 5 == 0:
            report_lines.append(f"| {ld} | {row['mean']} | {int(row['count'])} |")
    report_lines.append("\n")
    
    report_lines.append("## 2. Carrier Price Structure\n")
    report_lines.append("Average fares across the airlines in the dataset:\n")
    carrier_agg = df.groupby('airline_name')['total_fare'].agg(['count', 'mean', 'median', 'std']).reset_index()
    carrier_agg = carrier_agg.sort_values(by='mean', ascending=False)
    report_lines.append("| Airline | Count | Avg Fare | Median Fare | Std Dev |")
    report_lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for _, row in carrier_agg.iterrows():
        mean_v = round(row['mean'], 2)
        med_v = round(row['median'], 2)
        std_v = round(row['std'], 2)
        report_lines.append(f"| {row['airline_name']} | {int(row['count'])} | {mean_v} | {med_v} | {std_v} |")
    report_lines.append("\n")
    
    report_lines.append("## 3. Route-Level Fare Distribution Checks\n")
    report_lines.append("Summary of fare distribution across all origin-destination routes in the dataset:\n")
    route_agg = df.groupby('route_code')['total_fare'].agg(['count', 'mean', 'min', 'max']).reset_index()
    route_agg = route_agg.sort_values(by='route_code')
    report_lines.append("| Route | Count | Min Fare | Avg Fare | Max Fare |")
    report_lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for _, row in route_agg.iterrows():
        mean_v = round(row['mean'], 2)
        min_v = round(row['min'], 2)
        max_v = round(row['max'], 2)
        report_lines.append(f"| {row['route_code']} | {int(row['count'])} | {min_v} | {mean_v} | {max_v} |")
    report_lines.append("\n")
    
    report_path = os.path.join(os.path.dirname(__file__), "..", "docs", "kaggle_validation_report.md")
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))
        
    logger.info(f"Report written to {report_path}")

if __name__ == "__main__":
    generate_report()
