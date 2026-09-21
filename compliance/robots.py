"""
compliance/robots.py
Robots.txt parser, validator, and caching client.

Enforces strict compliance rules:
  1. Identifies itself with a fixed, identifiable research User-Agent.
  2. Fetches and parses robots.txt with safe fallback (unknown != allowed).
  3. Caches results in memory and disk to minimize server load.
  4. Exposes is_allowed() and get_crawl_delay().
"""
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "APIxBot/1.0 (+https://github.com/d-mahi14/airfare-index_prediction; research-compliance@apix.internal)"
DEFAULT_CACHE_DIR = Path(__file__).parent.parent / "data" / "compliance" / "robots_cache"


@dataclass
class RobotsResult:
    """Result of fetching and parsing robots.txt for a domain."""

    base_url: str
    robots_url: str
    is_reachable: bool
    status_code: Optional[int] = None
    raw_content: str = ""
    error_message: Optional[str] = None
    crawl_delay: Optional[float] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parser: Optional[RobotFileParser] = None

    def is_allowed(self, path_or_url: str, user_agent: str = DEFAULT_USER_AGENT) -> bool:
        """
        Check if a given path/URL is allowed by robots.txt.
        CRITICAL: If robots.txt was unreachable or failed to fetch, returns False (unknown != allowed).
        """
        if not self.is_reachable or self.parser is None:
            return False

        url = path_or_url
        if not url.startswith("http://") and not url.startswith("https://"):
            url = urllib.parse.urljoin(self.base_url, path_or_url)

        return self.parser.can_fetch(user_agent, url)


class RobotsChecker:
    """Client for fetching, caching, and evaluating robots.txt permissions."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        cache_dir: Optional[Path | str] = None,
        timeout: int = 10,
    ):
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.timeout = timeout
        self._memory_cache: Dict[str, RobotsResult] = {}
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_robots_url(self, base_url: str) -> str:
        """Construct the full robots.txt URL from a base URL."""
        parsed = urllib.parse.urlparse(base_url)
        scheme = parsed.scheme if parsed.scheme else "https"
        netloc = parsed.netloc if parsed.netloc else parsed.path
        return f"{scheme}://{netloc}/robots.txt"

    def fetch_robots(self, base_url: str, force_refresh: bool = False) -> RobotsResult:
        """
        Fetch and parse robots.txt for the given base URL.
        Caches in-memory and writes raw robots.txt to disk cache.
        """
        robots_url = self._get_robots_url(base_url)

        if not force_refresh and base_url in self._memory_cache:
            return self._memory_cache[base_url]

        parsed_netloc = urllib.parse.urlparse(base_url).netloc.replace(":", "_")
        cache_file = self.cache_dir / f"{parsed_netloc}_robots.txt"

        req = urllib.request.Request(
            robots_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/plain, */*",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                status_code = response.getcode()
                raw_bytes = response.read()
                raw_content = raw_bytes.decode("utf-8", errors="replace")

                # Parse robots.txt
                parser = RobotFileParser()
                parser.parse(raw_content.splitlines())

                # Extract crawl-delay if specified
                crawl_delay = parser.crawl_delay(self.user_agent)
                if crawl_delay is None:
                    crawl_delay = parser.crawl_delay("*")

                # Write to disk cache
                try:
                    cache_file.write_text(raw_content, encoding="utf-8")
                except Exception as exc:
                    logger.debug(f"Could not cache robots.txt to file: {exc}")

                result = RobotsResult(
                    base_url=base_url,
                    robots_url=robots_url,
                    is_reachable=True,
                    status_code=status_code,
                    raw_content=raw_content,
                    crawl_delay=crawl_delay,
                    parser=parser,
                )
                self._memory_cache[base_url] = result
                return result

        except urllib.error.HTTPError as err:
            logger.warning(f"HTTP error fetching robots.txt for {base_url}: {err.code} {err.reason}")
            result = RobotsResult(
                base_url=base_url,
                robots_url=robots_url,
                is_reachable=False,
                status_code=err.code,
                error_message=f"HTTP {err.code}: {err.reason}",
            )
            self._memory_cache[base_url] = result
            return result

        except urllib.error.URLError as err:
            logger.warning(f"Network error fetching robots.txt for {base_url}: {err.reason}")
            result = RobotsResult(
                base_url=base_url,
                robots_url=robots_url,
                is_reachable=False,
                error_message=f"Network Error: {err.reason}",
            )
            self._memory_cache[base_url] = result
            return result

        except Exception as err:
            logger.warning(f"Unexpected error fetching robots.txt for {base_url}: {err}")
            result = RobotsResult(
                base_url=base_url,
                robots_url=robots_url,
                is_reachable=False,
                error_message=f"Error: {str(err)}",
            )
            self._memory_cache[base_url] = result
            return result

    def is_allowed(
        self,
        base_url_or_full_url: str,
        path: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> bool:
        """
        Check if fetching a path from the domain is permitted.
        If fetch failed or domain is unreachable, returns False.
        """
        ua = user_agent or self.user_agent
        if path is not None:
            base_url = base_url_or_full_url
            target_url = urllib.parse.urljoin(base_url, path)
        else:
            parsed = urllib.parse.urlparse(base_url_or_full_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            target_url = base_url_or_full_url

        result = self.fetch_robots(base_url)
        return result.is_allowed(target_url, user_agent=ua)

    def get_crawl_delay(
        self,
        base_url: str,
        user_agent: Optional[str] = None,
    ) -> Optional[float]:
        """Return the specified crawl delay in seconds, if declared."""
        ua = user_agent or self.user_agent
        result = self.fetch_robots(base_url)
        if not result.is_reachable or not result.parser:
            return None
        delay = result.parser.crawl_delay(ua)
        if delay is None:
            delay = result.parser.crawl_delay("*")
        return delay

    def get_relevant_excerpts(self, base_url: str, paths: List[str], max_lines: int = 15) -> List[str]:
        """Extract matching disallow/allow lines relevant to the specified search paths."""
        result = self.fetch_robots(base_url)
        if not result.is_reachable or not result.raw_content:
            return [f"Unable to fetch robots.txt ({result.error_message or 'unreachable'})"]

        lines = result.raw_content.splitlines()
        relevant = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lower = stripped.lower()
            if any(path.lower() in lower for path in paths) or "crawl-delay" in lower or "user-agent:" in lower:
                relevant.append(stripped)

        if not relevant:
            # Return first few non-comment directives
            directives = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
            relevant = directives[:max_lines]

        return relevant[:max_lines]
