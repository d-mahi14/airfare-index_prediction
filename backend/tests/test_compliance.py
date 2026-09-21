"""
backend/tests/test_compliance.py
Unit and integration tests for compliance registry and robots.txt checker with mocked HTTP.
"""
import io
import urllib.error
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from compliance.check import run_compliance_check
from compliance.registry import SourceConfig, SourceRegistry
from compliance.robots import DEFAULT_USER_AGENT, RobotsChecker, RobotsResult

_PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestSourceRegistry:
    def test_load_default_sources_yaml(self):
        registry = SourceRegistry()
        sources = registry.list_sources()
        assert len(sources) == 11

        expected_names = [
            "IndiGo",
            "Air India",
            "Air India Express",
            "Akasa Air",
            "SpiceJet",
            "MakeMyTrip",
            "Yatra",
            "EaseMyTrip",
            "Cleartrip",
            "Ixigo",
            "Goibibo",
        ]
        for name in expected_names:
            src = registry.get_source(name)
            assert src is not None, f"Source '{name}' missing from registry"
            assert src.name == name
            assert src.base_url.startswith("https://")
            assert src.type in {"airline", "ota"}
            assert src.collection_mode == "recorded_fixture"
            assert src.tos_notes == "TO BE REVIEWED BY HUMAN"
            assert len(src.search_paths_to_check) > 0

    def test_get_by_mode(self):
        registry = SourceRegistry()
        fixture_sources = registry.get_by_mode("recorded_fixture")
        assert len(fixture_sources) == 11

        live_sources = registry.get_by_mode("live_scrape")
        assert len(live_sources) == 0

    def test_get_by_type(self):
        registry = SourceRegistry()
        airlines = registry.get_by_type("airline")
        otas = registry.get_by_type("ota")
        assert len(airlines) == 5
        assert len(otas) == 6

    def test_missing_file_raises_error(self, tmp_path):
        missing_file = tmp_path / "non_existent.yaml"
        with pytest.raises(FileNotFoundError):
            SourceRegistry(config_path=missing_file)

    def test_invalid_yaml_format_raises_error(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("invalid_key: 123", encoding="utf-8")
        with pytest.raises(ValueError):
            SourceRegistry(config_path=bad_file)


class TestRobotsChecker:
    @pytest.fixture
    def mock_robots_text(self):
        return (
            "User-agent: *\n"
            "Disallow: /admin/\n"
            "Disallow: /booking/private/\n"
            "Disallow: /api/internal/\n"
            "Allow: /flights\n"
            "Allow: /flight-search\n"
            "Crawl-delay: 5\n"
            "\n"
            "User-agent: APIxBot\n"
            "Disallow: /restricted/\n"
            "Allow: /\n"
        )

    @patch("urllib.request.urlopen")
    def test_fetch_and_parse_allowed_paths(self, mock_urlopen, tmp_path, mock_robots_text):
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = mock_robots_text.encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        checker = RobotsChecker(cache_dir=tmp_path)
        base_url = "https://example.com"

        # Check APIxBot permissions
        assert checker.is_allowed(base_url, "/flights", user_agent="APIxBot") is True
        assert checker.is_allowed(base_url, "/restricted/page", user_agent="APIxBot") is False

        # Check general agent permissions
        assert checker.is_allowed(base_url, "/admin/settings", user_agent="OtherBot") is False
        assert checker.is_allowed(base_url, "/flights", user_agent="OtherBot") is True

    @patch("urllib.request.urlopen")
    def test_crawl_delay_parsed(self, mock_urlopen, tmp_path, mock_robots_text):
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = mock_robots_text.encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        checker = RobotsChecker(cache_dir=tmp_path)
        base_url = "https://example.com"

        delay = checker.get_crawl_delay(base_url, user_agent="OtherBot")
        assert delay == 5.0

    @patch("urllib.request.urlopen")
    def test_fetch_failure_unknown_not_allowed(self, mock_urlopen, tmp_path):
        """CRITICAL: Failed robots.txt fetches must result in is_allowed=False (unknown != allowed)."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection timed out")

        checker = RobotsChecker(cache_dir=tmp_path)
        base_url = "https://failing-domain.com"

        res = checker.fetch_robots(base_url)
        assert res.is_reachable is False
        assert "Connection timed out" in res.error_message

        # Path must be rejected when robots.txt is unreachable
        assert checker.is_allowed(base_url, "/any-path") is False
        assert checker.is_allowed(base_url, "/") is False

    @patch("urllib.request.urlopen")
    def test_http_500_error_rejected(self, mock_urlopen, tmp_path):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://error-domain.com/robots.txt",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=io.BytesIO(b"Server Error"),
        )

        checker = RobotsChecker(cache_dir=tmp_path)
        base_url = "https://error-domain.com"

        res = checker.fetch_robots(base_url)
        assert res.is_reachable is False
        assert res.status_code == 500
        assert checker.is_allowed(base_url, "/search") is False

    @patch("urllib.request.urlopen")
    def test_caching_behavior(self, mock_urlopen, tmp_path, mock_robots_text):
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = mock_robots_text.encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        checker = RobotsChecker(cache_dir=tmp_path)
        base_url = "https://cached-domain.com"

        # First call fetches from network
        res1 = checker.fetch_robots(base_url)
        assert mock_urlopen.call_count == 1

        # Second call uses in-memory cache
        res2 = checker.fetch_robots(base_url)
        assert mock_urlopen.call_count == 1
        assert res1 is res2


class TestComplianceCLI:
    @patch("urllib.request.urlopen")
    def test_compliance_check_run(self, mock_urlopen, tmp_path):
        mock_robots_content = (
            "User-agent: *\n"
            "Disallow: /admin/\n"
            "Allow: /flight-search\n"
            "Allow: /flights\n"
            "Crawl-delay: 2\n"
        )
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = mock_robots_content.encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        output_md = tmp_path / "COMPLIANCE_TEST.md"
        checker = RobotsChecker(cache_dir=tmp_path / "robots_cache")
        registry = SourceRegistry()

        results = run_compliance_check(
            registry=registry,
            checker=checker,
            output_md_path=output_md,
        )

        assert len(results) == 11
        assert output_md.exists()

        md_content = output_md.read_text(encoding="utf-8")
        assert "# APIx Data Collection Compliance & Robots.txt Audit" in md_content
        assert "TO BE REVIEWED BY HUMAN" in md_content
        assert "IndiGo" in md_content
        assert "MakeMyTrip" in md_content
