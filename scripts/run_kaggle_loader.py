import logging
import os
import sys

from backend.app.database import get_engine
from backtest.loaders import load_kaggle_historical_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "external", "Cleaned_dataset.csv")
    engine = get_engine()
    
    logger.info("Starting load of full Kaggle dataset...")
    load_kaggle_historical_data(csv_path, engine)
    logger.info("Finished loading Kaggle dataset.")
