"""
compliance
Compliance and ethical data collection subsystem for APIx.

Provides:
  - SourceRegistry: loader and validator for config/sources.yaml
  - RobotsChecker: robots.txt fetcher, parser, and permission evaluator
  - DEFAULT_USER_AGENT: Fixed identifiable bot user agent
"""
from compliance.registry import SourceConfig, SourceRegistry
from compliance.robots import DEFAULT_USER_AGENT, RobotsChecker, RobotsResult

__all__ = [
    "SourceConfig",
    "SourceRegistry",
    "RobotsChecker",
    "RobotsResult",
    "DEFAULT_USER_AGENT",
]
