"""
scraper/collectors package
"""
from scraper.collectors.indigo_collector import IndiGoCollector
from scraper.collectors.makemytrip_collector import MakeMyTripCollector
from scraper.collectors.mock_collector import MockCollector
from scraper.collectors.recorded_collector import EaseMyTripCollector, RecordedCollector

__all__ = [
    "MockCollector",
    "RecordedCollector",
    "EaseMyTripCollector",
    "IndiGoCollector",
    "MakeMyTripCollector",
]
