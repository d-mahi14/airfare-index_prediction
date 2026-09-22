import os
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.models.airfare import AirfareObservation, Source, Route, Airline
from backtest.loaders import load_kaggle_historical_data

def test_load_kaggle_historical_data(db_engine):
    sample_csv = os.path.join(os.path.dirname(__file__), "..", "fixtures", "kaggle_sample.csv")
    
    # Load the fixture data
    load_kaggle_historical_data(sample_csv, db_engine, fixture_mode=True)
    
    with Session(db_engine) as session:
        # Check observations count
        obs = session.scalars(select(AirfareObservation)).all()
        assert len(obs) == 5
        
        # Check source
        sources = session.scalars(select(Source)).all()
        assert len(sources) == 1
        assert sources[0].name == "external_historical_kaggle_2023"
        
        # Check routes
        routes = session.scalars(select(Route)).all()
        assert len(routes) == 4
        route_codes = set(r.route_code for r in routes)
        assert route_codes == {"DEL-BOM", "DEL-BLR", "HYD-CCU", "MAA-AMD"}
        
        # Check airlines
        airlines = session.scalars(select(Airline)).all()
        assert len(airlines) == 4
        airline_names = set(a.name for a in airlines)
        assert airline_names == {"SpiceJet", "Indigo", "GO FIRST", "Vistara"}
        
        # Check a specific flight for correct mapping
        vistara_flight = session.execute(
            select(AirfareObservation).join(Airline).where(Airline.name == "Vistara")
        ).scalar_one()
        
        assert vistara_flight.total_fare == 25000
        assert vistara_flight.lead_days == 45
        assert vistara_flight.target_lead_window == 45
        assert vistara_flight.dep_band == "early"
        assert vistara_flight.stops == 2
        assert vistara_flight.currency == "INR"
        assert vistara_flight.status == "valid"
        
        spicejet_flights = session.execute(
            select(AirfareObservation).join(Airline).where(Airline.name == "SpiceJet")
        ).scalars().all()
        assert len(spicejet_flights) == 2
