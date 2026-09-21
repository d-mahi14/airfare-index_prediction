"""
compliance/check.py
CLI tool to audit robots.txt permissions and generate docs/COMPLIANCE.md.

Usage:
  python -m compliance.check
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from compliance.registry import SourceConfig, SourceRegistry
from compliance.robots import DEFAULT_USER_AGENT, RobotsChecker, RobotsResult

DOCS_COMPLIANCE_MD = Path(__file__).parent.parent / "docs" / "COMPLIANCE.md"


def run_compliance_check(
    registry: SourceRegistry = None,
    checker: RobotsChecker = None,
    output_md_path: Path = None,
) -> Dict[str, dict]:
    """
    Run compliance check across all registered sources.
    Prints an ASCII summary table to stdout and writes docs/COMPLIANCE.md.
    """
    if registry is None:
        registry = SourceRegistry()
    if checker is None:
        checker = RobotsChecker()
    if output_md_path is None:
        output_md_path = DOCS_COMPLIANCE_MD

    sources = registry.list_sources()
    check_time = datetime.now(timezone.utc)
    results = {}

    print("=" * 95)
    print(f"APIx COMPLIANCE AUDIT -- ROBOTS.TXT CHECK")
    print(f"Executed At : {check_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"User-Agent  : {DEFAULT_USER_AGENT}")
    print("=" * 95)
    print(f"{'Source':<18} | {'Type':<8} | {'Mode':<17} | {'Robots.txt':<12} | {'Crawl-Delay':<11} | {'Search Paths Allowed'}")
    print("-" * 95)

    for source in sources:
        res: RobotsResult = checker.fetch_robots(source.base_url)
        path_evaluations = {}

        for path in source.search_paths_to_check:
            allowed = checker.is_allowed(source.base_url, path)
            path_evaluations[path] = allowed

        # Calculate overall path allowance
        allowed_count = sum(1 for v in path_evaluations.values() if v)
        total_paths = len(path_evaluations)
        paths_summary = f"{allowed_count}/{total_paths} paths"

        reachability_str = "Reachable" if res.is_reachable else f"Error ({res.status_code or 'Fail'})"
        crawl_delay_str = f"{res.crawl_delay}s" if res.crawl_delay is not None else "None"

        print(
            f"{source.name:<18} | {source.type:<8} | {source.collection_mode:<17} | "
            f"{reachability_str:<12} | {crawl_delay_str:<11} | {paths_summary}"
        )

        excerpts = checker.get_relevant_excerpts(source.base_url, source.search_paths_to_check)

        results[source.name] = {
            "source": source,
            "robots_result": res,
            "path_evaluations": path_evaluations,
            "crawl_delay": res.crawl_delay,
            "excerpts": excerpts,
        }

    print("=" * 95)

    # Generate docs/COMPLIANCE.md
    generate_compliance_markdown(results, check_time, output_md_path)
    print(f"\n[+] Compliance documentation written to: {output_md_path}\n")

    return results


def generate_compliance_markdown(
    results: Dict[str, dict],
    check_time: datetime,
    output_path: Path,
) -> None:
    """Write the structured compliance report to Markdown."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# APIx Data Collection Compliance & Robots.txt Audit",
        "",
        f"> **Audit Date**: {check_time.strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        f"> **Auditing User-Agent**: `{DEFAULT_USER_AGENT}`  ",
        f"> **Policy Enforcement**: Strict ethical scraping. No evasion, no CAPTCHA solving, rate-limited.",
        "",
        "---",
        "",
        "## 1. Executive Summary Table",
        "",
        "| Source | Type | Collection Mode | Robots.txt Status | Crawl-Delay | Search Path Permissions | ToS Review Status |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for name, data in results.items():
        source: SourceConfig = data["source"]
        res: RobotsResult = data["robots_result"]
        paths: dict = data["path_evaluations"]

        status_badge = "✅ Reachable" if res.is_reachable else f"❌ {res.error_message or 'Unreachable'}"
        delay_str = f"{res.crawl_delay}s" if res.crawl_delay is not None else "None"

        path_details = []
        for p, is_allowed in paths.items():
            icon = "✅" if is_allowed else "❌"
            path_details.append(f"`{p}`: {icon}")
        paths_str = "<br>".join(path_details) if path_details else "N/A"

        lines.append(
            f"| **{name}** | {source.type} | `{source.collection_mode}` | {status_badge} | {delay_str} | {paths_str} | **{source.tos_notes}** |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 2. Ethical Data Collection Commitments",
        "",
        "1. **Pre-Fetch Verification**: Robots.txt rules are evaluated before any collector request.",
        "2. **Zero Evasion**: We do not solve CAPTCHAs, bypass Cloudflare/Akamai bot challenges, rotate proxies, or disguise User-Agents.",
        "3. **Human Terms of Service Review**: All sources default to `recorded_fixture` mode with `tos_notes: 'TO BE REVIEWED BY HUMAN'`. Live scraping is never activated without formal human authorization.",
        "4. **Fail-Closed Permissions**: If a domain's `robots.txt` cannot be fetched (HTTP 4xx/5xx or timeout), all search paths are treated as disallowed (`unknown != allowed`).",
        "",
        "---",
        "",
        "## 3. Raw Robots.txt Excerpts by Source",
        "",
    ])

    for name, data in results.items():
        source: SourceConfig = data["source"]
        res: RobotsResult = data["robots_result"]
        excerpts: List[str] = data["excerpts"]

        lines.extend([
            f"### {name} (`{source.base_url}`)",
            f"- **Type**: {source.type}",
            f"- **Robots URL**: [{res.robots_url}]({res.robots_url})",
            f"- **Collection Mode**: `{source.collection_mode}`",
            f"- **ToS Review Notes**: `{source.tos_notes}`",
            "",
            "```txt",
        ])

        if excerpts:
            for exc in excerpts:
                lines.append(exc)
        else:
            lines.append("# No relevant directives or file empty/unreachable")

        lines.extend([
            "```",
            "",
        ])

    output_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run_compliance_check()
