"""
scraper/framework/block_detector.py
Detection of anti-bot challenges, CAPTCHAs, WAF blocks, and HTTP 429 rate limits.

Ethical scraping policy:
  - NEVER solve CAPTCHAs or bypass challenges.
  - NEVER rotate IPs or use proxy networks to evade rate limits or blocks.
  - NEVER attempt to log in or breach authentication gates.
  - When a block or challenge is encountered, detect it cleanly and return a BlockedResult.
"""
import logging
import re
from typing import Dict, Optional

from scraper.base import BlockedResult

logger = logging.getLogger(__name__)

# Signatures for automated bot challenge / CAPTCHA systems
_CAPTCHA_SIGNATURES = [
    re.compile(r"cf-chl-bypass", re.I),
    re.compile(r"challenge-platform", re.I),
    re.compile(r"cf-turnstile", re.I),
    re.compile(r"challenges\.cloudflare\.com", re.I),
    re.compile(r"just a moment\.\.\.", re.I),
    re.compile(r"verify you are human", re.I),
    re.compile(r"hcaptcha\.com", re.I),
    re.compile(r"class=[\"']h-captcha[\"']", re.I),
    re.compile(r"google\.com/recaptcha", re.I),
    re.compile(r"class=[\"']g-recaptcha[\"']", re.I),
    re.compile(r"grecaptcha\.render", re.I),
    re.compile(r"px-captcha", re.I),
    re.compile(r"perimeterx", re.I),
    re.compile(r"datadome", re.I),
    re.compile(r"distil_r_comments", re.I),
    re.compile(r"shieldsquare", re.I),
    re.compile(r"bot detection", re.I),
    re.compile(r"security check to access", re.I),
    re.compile(r"enable javascript and cookies to continue", re.I),
]

_WAF_SIGNATURES = [
    re.compile(r"access denied", re.I),
    re.compile(r"blocked by web application firewall", re.I),
    re.compile(r"incapsula incident id", re.I),
    re.compile(r"akamai error", re.I),
    re.compile(r"error 403: forbidden", re.I),
]


class BlockDetector:
    """Detects HTTP status codes and response bodies indicating scraping blocks or challenges."""

    @staticmethod
    def detect(
        status_code: Optional[int] = None,
        content: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        url: Optional[str] = None,
    ) -> Optional[BlockedResult]:
        """
        Analyze status code, response body, and headers for blocks or bot challenges.

        Returns:
            BlockedResult if blocked or challenged, None if response appears clean.
        """
        # 1. HTTP 429 Too Many Requests
        if status_code == 429:
            logger.warning(f"BlockDetector: HTTP 429 Too Many Requests detected on {url or 'target'}")
            return BlockedResult(
                is_blocked=True,
                block_type="rate_limit_429",
                status_code=429,
                message="HTTP 429 Too Many Requests: Rate limit exceeded",
                url=url,
            )

        # 2. HTTP 403 Forbidden / Cloudflare WAF Block
        if status_code == 403:
            logger.warning(f"BlockDetector: HTTP 403 Forbidden detected on {url or 'target'}")
            return BlockedResult(
                is_blocked=True,
                block_type="waf_challenge",
                status_code=403,
                message="HTTP 403 Forbidden: WAF or Access Control block",
                url=url,
            )

        if not content:
            return None

        # 3. CAPTCHA and Cloudflare / Turnstile challenges in response body
        for pattern in _CAPTCHA_SIGNATURES:
            if pattern.search(content):
                matched = pattern.pattern
                logger.warning(f"BlockDetector: CAPTCHA / bot challenge pattern matched '{matched}' on {url or 'target'}")
                return BlockedResult(
                    is_blocked=True,
                    block_type="captcha",
                    status_code=status_code,
                    message=f"Bot challenge/CAPTCHA detected (matched signature: '{matched}')",
                    url=url,
                )

        # 4. WAF block signatures in response body
        for pattern in _WAF_SIGNATURES:
            if pattern.search(content):
                matched = pattern.pattern
                logger.warning(f"BlockDetector: WAF block signature matched '{matched}' on {url or 'target'}")
                return BlockedResult(
                    is_blocked=True,
                    block_type="waf_challenge",
                    status_code=status_code,
                    message=f"WAF block signature detected (matched: '{matched}')",
                    url=url,
                )

        return None


def detect_block(
    status_code: Optional[int] = None,
    content: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    url: Optional[str] = None,
) -> Optional[BlockedResult]:
    """Convenience function for block detection."""
    return BlockDetector.detect(status_code=status_code, content=content, headers=headers, url=url)
