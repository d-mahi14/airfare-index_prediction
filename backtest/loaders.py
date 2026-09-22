"""
backtest/loaders.py

DataLoader for historical backtests, specifically the Kaggle Indian Domestic flights dataset.
"""
import logging
from datetime import date, datetime
from typing import Dict

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models.airfare import AirfareObservation, Airline, Route, Source

logger = logging.getLogger(__name__)

CITY_TO_IATA = {
    "Ahmedabad": "AMD",
    "Bangalore": "BLR",
    "Chennai": "MAA",
    "Delhi": "DEL",
    "Hyderabad": "HYD",
    "Kolkata": "CCU",
    "Mumbai": "BOM"
}

def _get_target_lead_window(days_left: int) -> int:
    """Map Days_left to the nearest target_lead_window (1, 7, 15, 30, 45)."""
    if days_left <= 4:
        return 1
    elif 5 <= days_left <= 11:
        return 7
    elif 12 <= days_left <= 22:
        return 15
    elif 23 <= days_left <= 37:
        return 30
    else:
        return 45

def get_or_create_source(session: Session) -> Source:
    source = session.execute(
        select(Source).where(Source.name == "external_historical_kaggle_2023")
    ).scalar_one_or_none()
    
    if not source:
        source = Source(name="external_historical_kaggle_2023", is_active=False)
        session.add(source)
        session.flush()
    return source

def get_or_create_airlines(session: Session, df: pd.DataFrame) -> Dict[str, Airline]:
    airlines = {}
    unique_airlines = df['Airline'].unique()
    for al_name in unique_airlines:
        airline = session.execute(
            select(Airline).where(Airline.name == al_name)
        ).scalar_one_or_none()
        
        if not airline:
            airline = Airline(name=al_name, is_active=False)
            session.add(airline)
            session.flush()
        airlines[al_name] = airline
    return airlines

def get_or_create_routes(session: Session, df: pd.DataFrame) -> Dict[str, Route]:
    routes = {}
    # Combine Source and Destination to find all unique routes
    df_routes = df[['Source', 'Destination']].drop_duplicates()
    for _, row in df_routes.iterrows():
        orig_city = row['Source']
        dest_city = row['Destination']
        
        orig_iata = CITY_TO_IATA.get(orig_city)
        dest_iata = CITY_TO_IATA.get(dest_city)
        
        if not orig_iata or not dest_iata:
            continue
            
        route_code = f"{orig_iata}-{dest_iata}"
        route = session.execute(
            select(Route).where(Route.route_code == route_code)
        ).scalar_one_or_none()
        
        if not route:
            route = Route(
                origin=orig_iata,
                destination=dest_iata,
                route_code=route_code,
                is_active=False
            )
            session.add(route)
            session.flush()
        routes[route_code] = route
    return routes

def load_kaggle_historical_data(csv_path: str, db_engine, fixture_mode: bool = False, batch_size: int = 10000):
    """
    Load Kaggle dataset into airfare_observations.
    """
    logger.info(f"Starting load from {csv_path}")
    
    df = pd.read_csv(csv_path)
    
    # Deduplicate to avoid unique constraint violation on (flight_number, travel_date, fare_class)
    df = df.drop_duplicates(subset=['Flight_code', 'Date_of_journey', 'Class'], keep='first')
    logger.info(f"Loaded and deduplicated {len(df)} rows to insert.")
        
    with Session(db_engine) as session:
        source = get_or_create_source(session)
        
        # Idempotency: clear existing for this source
        session.execute(delete(AirfareObservation).where(AirfareObservation.source_id == source.id))
        session.commit()
        
        # Prefetch lookups
        airlines_map = get_or_create_airlines(session, df)
        routes_map = get_or_create_routes(session, df)
        session.commit()
        
        records = []
        for index, row in df.iterrows():
            orig_iata = CITY_TO_IATA.get(row['Source'])
            dest_iata = CITY_TO_IATA.get(row['Destination'])
            if not orig_iata or not dest_iata:
                continue
                
            route_code = f"{orig_iata}-{dest_iata}"
            route = routes_map.get(route_code)
            airline = airlines_map.get(row['Airline'])
            
            if not route or not airline:
                continue
                
            travel_date = datetime.strptime(row['Date_of_journey'], '%Y-%m-%d').date()
            days_left = int(row['Days_left'])
            
            # Dep time formatting
            dep_time_str = row.get('Departure', '')
            dep_band = None
            if "Before 6 AM" in dep_time_str:
                dep_band = "early"
            elif "6 AM - 12 PM" in dep_time_str:
                dep_band = "morning"
            elif "12 PM - 6 PM" in dep_time_str:
                dep_band = "afternoon"
            elif "After 6 PM" in dep_time_str:
                dep_band = "evening"
            
            # Stops parsing
            stops = 0
            stops_str = str(row['Total_stops']).lower()
            if '1' in stops_str or '1-stop' in stops_str:
                stops = 1
            elif '2' in stops_str:
                stops = 2
            elif 'non-stop' not in stops_str and '0' not in stops_str:
                stops = 1 # fallback guess
                
            # Kaggle data maps to 2023-01-15 exactly for collection date.
            collection_date = date(2023, 1, 15)
            
            record = AirfareObservation(
                collection_date=collection_date,
                source_id=source.id,
                route_id=route.id,
                airline_id=airline.id,
                flight_number=row['Flight_code'][:20],
                travel_date=travel_date,
                lead_days=days_left,
                fare_class=row['Class'],
                total_fare=float(row['Fare']),
                currency="INR",
                stops=stops,
                dep_band=dep_band,
                status='valid',
                is_synthetic=False,
                target_lead_window=_get_target_lead_window(days_left)
            )
            records.append(record)
            
            if len(records) >= batch_size:
                session.bulk_save_objects(records)
                session.commit()
                records = []
                
        if records:
            session.bulk_save_objects(records)
            session.commit()

        logger.info("Load complete.")
