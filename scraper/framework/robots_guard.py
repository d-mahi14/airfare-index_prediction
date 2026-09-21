"""
scraper/framework/robots_guard.py
Robots.txt compliance enforcement guard for all collectors.

Guarantees:
  - Evaluates robots.txt rules before any collector network request.
  - If a path is disallowed or robots.txt is unreachable (unknown != allowed),
    it immediately raises DisallowedError.
"""
import logging
from typing import Optional
import urllib.parse

from compliance.registry import SourceConfig
from compliance.robots import DEFAULT_USER_AGENT, RobotsChecker
from scraper.base import DisallowedError

logger = logging.getLogger(__name__)


class RobotsGuard:
    """Enforces robots.txt constraints on data collection sources."""

    def __init__(
        self,
        checker: Optional[RobotsChecker] = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self.checker = checker or RobotsChecker(user_agent=user_agent)
        self.user_agent = user_agent

    def check_or_raise(
        self,
        base_url_or_config: str | SourceConfig,
        path: str = "/",
        user_agent: Optional[str] = None,
    ) -> None:
        """
        Validate that the requested path is permitted under robots.txt.

        Raises:
            DisallowedError: if the path is explicitly disallowed or if robots.txt
                             is unreachable / unknown.
        """
        ua = user_agent or self.user_agent
        if isinstance(base_url_or_config, SourceConfig):
            base_url = base_url_or_config.base_url
        else:
            base_url = base_url_or_config

        target_url = urllib.parse.urljoin(base_url, path)
        allowed = self.checker.is_allowed(base_url, path=path, user_agent=ua)

        if not allowed:
            logger.error(
                f"RobotsGuard violation: Access to '{target_url}' for user-agent '{ua}' is DISALLOWED."
            )
            raise DisallowedError(
                f"Collection disallowed by robots.txt or compliance policy for target URL: {target_url}"
            )

        logger.debug(f"RobotsGuard passed for {target_url}")

    def is_allowed(
        self,
        base_url_or_config: str | SourceConfig,
        path: str = "/",
        user_agent: Optional[str] = None,
    ) -> bool:
        """Non-raising permission check."""
        try:
            self.check_or_raise(base_url_or_config, path=path, user_agent=user_agent)
            return True
        except DisallowedError:
            return False
