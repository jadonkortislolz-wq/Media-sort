"""Standalone CLI Benchmark Runner & Diagnostic Reporter (Requirement R2).

Executable via:
    .venv/bin/python -m tests.benchmark.runner
    .venv/bin/python tests/benchmark/runner.py

Computes per-domain pass/fail statistics, execution timing, and field diffs for
any failed case. Renders a clean terminal summary table and exports
tests/benchmark/benchmark_summary.json.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from tests.benchmark.benchmark_cases import (
        BENCHMARK_CASES,
        BenchmarkCase,
        CaseResult,
        evaluate_benchmark_case,
    )
except ImportError:
    from benchmark_cases import (  # type: ignore
        BENCHMARK_CASES,
        BenchmarkCase,
        CaseResult,
        evaluate_benchmark_case,
    )

DEFAULT_JSON_PATH = Path(__file__).parent / "benchmark_summary.json"


class BenchmarkRunner:
    """Orchestrates execution, diagnostic collection, and reporting for benchmark cases."""

    def __init__(
        self,
        cases: Optional[List[BenchmarkCase]] = None,
        json_output_path: Path = DEFAULT_JSON_PATH,
        verbose: bool = False,
        show_diffs: bool = True,
        strict: bool = False,
    ):
        self.cases = cases or BENCHMARK_CASES
        self.json_output_path = json_output_path
        self.verbose = verbose
        self.show_diffs = show_diffs
        self.strict = strict
        self.results: List[CaseResult] = []

    def run(self) -> Dict[str, Any]:
        """Execute all configured benchmark cases and collect results."""
        self.results.clear()
        for case in self.cases:
            result = evaluate_benchmark_case(case)
            self.results.append(result)

        summary_data = self._build_summary_data()
        self._export_json(summary_data)
        return summary_data

    def _build_summary_data(self) -> Dict[str, Any]:
        total_cases = len(self.results)
        passed_cases = sum(1 for r in self.results if r.passed)
        failed_cases = total_cases - passed_cases
        pass_rate = (passed_cases / total_cases * 100.0) if total_cases else 0.0
        total_duration_ms = sum(r.duration_ms for r in self.results)

        # Domain breakdown
        domain_stats: Dict[str, Dict[str, Any]] = {}
        for r in self.results:
            d = domain_stats.setdefault(
                r.domain,
                {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "pass_rate_pct": 0.0,
                    "total_duration_ms": 0.0,
                    "avg_duration_ms": 0.0,
                },
            )
            d["total"] += 1
            if r.passed:
                d["passed"] += 1
            else:
                d["failed"] += 1
            d["total_duration_ms"] += r.duration_ms

        for d in domain_stats.values():
            if d["total"] > 0:
                d["pass_rate_pct"] = round(d["passed"] / d["total"] * 100.0, 1)
                d["avg_duration_ms"] = round(d["total_duration_ms"] / d["total"], 2)

        # Failures list
        failures = [
            {
                "id": r.case_id,
                "domain": r.domain,
                "filename": r.filename,
                "edge_case_type": r.edge_case_type,
                "diffs": r.diffs,
                "actual_category": r.actual_category,
                "actual_title": r.actual_title,
                "actual_destination_subpath": r.actual_destination_subpath,
                "duration_ms": r.duration_ms,
            }
            for r in self.results
            if not r.passed
        ]

        # Serialized results
        all_results_data = [
            {
                "id": r.case_id,
                "domain": r.domain,
                "filename": r.filename,
                "edge_case_type": r.edge_case_type,
                "passed": r.passed,
                "duration_ms": r.duration_ms,
                "diffs": r.diffs,
                "actual_category": r.actual_category,
                "actual_title": r.actual_title,
                "actual_destination_subpath": r.actual_destination_subpath,
                "exception": r.exception,
            }
            for r in self.results
        ]

        return {
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version.split()[0],
                "total_duration_ms": round(total_duration_ms, 2),
                "runner": "MediaSorter Offline E2E Benchmark Runner",
            },
            "summary": {
                "total_cases": total_cases,
                "passed_cases": passed_cases,
                "failed_cases": failed_cases,
                "pass_rate_pct": round(pass_rate, 2),
            },
            "domains": domain_stats,
            "failures": failures,
            "all_results": all_results_data,
        }

    def _export_json(self, data: Dict[str, Any]) -> None:
        self.json_output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.json_output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def print_terminal_report(self, summary_data: Dict[str, Any]) -> None:
        """Render a styled terminal summary table and failure details."""
        try:
            self._print_rich_report(summary_data)
        except Exception:
            self._print_plain_report(summary_data)

    def _print_rich_report(self, data: Dict[str, Any]) -> None:
        from rich.console import Console
        from rich.markup import escape
        from rich.panel import Panel
        from rich.table import Table

        console = Console()
        console.print()
        console.print(
            Panel.fit(
                "[bold cyan]Media Sorter E2E Benchmark Test Suite & Offline Runner[/bold cyan]\n"
                f"[dim]Timestamp: {data['metadata']['timestamp']} | Total Cases: {data['summary']['total_cases']}[/dim]",
                border_style="cyan",
            )
        )

        table = Table(title="Benchmark Results by Domain", show_footer=True)
        table.add_column("Domain", style="bold white", footer="Total / Overall")
        table.add_column("Total", justify="right", footer=str(data["summary"]["total_cases"]))
        table.add_column("Passed", justify="right", style="green", footer=str(data["summary"]["passed_cases"]))
        table.add_column("Failed", justify="right", style="red", footer=str(data["summary"]["failed_cases"]))
        table.add_column(
            "Pass Rate",
            justify="right",
            style="bold yellow",
            footer=f"{data['summary']['pass_rate_pct']:.1f}%",
        )
        table.add_column(
            "Avg Time (ms)",
            justify="right",
            style="dim",
            footer=f"{data['metadata']['total_duration_ms']:.1f}ms total",
        )

        for domain, stats in data["domains"].items():
            rate = stats["pass_rate_pct"]
            rate_style = "green" if rate == 100.0 else ("yellow" if rate >= 50.0 else "red")
            table.add_row(
                domain,
                str(stats["total"]),
                str(stats["passed"]),
                str(stats["failed"]),
                f"[{rate_style}]{rate:.1f}%[/{rate_style}]",
                f"{stats['avg_duration_ms']:.2f}ms",
            )

        console.print(table)
        console.print()

        # Print failures if requested
        if self.show_diffs and data["failures"]:
            console.print(f"[bold red]Diagnostic Gap Details ({len(data['failures'])} failures pending M2/M3):[/bold red]")
            for item in data["failures"]:
                esc_filename = escape(item["filename"])
                console.print(
                    f"\n  [bold red]✖ [{item['id']}][/bold red] [bold white]{esc_filename}[/bold white] "
                    f"([dim]{item['domain']} / {item['edge_case_type']}[/dim])"
                )
                for field_name, diff in item["diffs"].items():
                    exp_val = escape(repr(diff["expected"]))
                    act_val = escape(repr(diff["actual"]))
                    console.print(
                        f"      [yellow]• {field_name}:[/yellow] "
                        f"expected=[green]{exp_val}[/green], got=[red]{act_val}[/red]"
                    )


        console.print()
        console.print(
            f"[dim]Summary report exported to:[/dim] [cyan]{self.json_output_path.resolve()}[/cyan]\n"
        )

    def _print_plain_report(self, data: Dict[str, Any]) -> None:
        print("=" * 80)
        print(" Media Sorter E2E Benchmark Test Suite & Offline Runner")
        print(f" Timestamp: {data['metadata']['timestamp']} | Total: {data['summary']['total_cases']}")
        print("=" * 80)
        print(f"{'Domain':<25} {'Total':>8} {'Passed':>8} {'Failed':>8} {'Pass %':>10} {'Avg (ms)':>10}")
        print("-" * 80)
        for domain, stats in data["domains"].items():
            print(
                f"{domain:<25} {stats['total']:>8} {stats['passed']:>8} {stats['failed']:>8} "
                f"{stats['pass_rate_pct']:>9.1f}% {stats['avg_duration_ms']:>10.2f}"
            )
        print("-" * 80)
        summ = data["summary"]
        print(
            f"{'Total / Overall':<25} {summ['total_cases']:>8} {summ['passed_cases']:>8} {summ['failed_cases']:>8} "
            f"{summ['pass_rate_pct']:>9.1f}% {data['metadata']['total_duration_ms']:>10.2f}ms"
        )
        print("=" * 80)

        if self.show_diffs and data["failures"]:
            print(f"\nDiagnostic Gap Details ({len(data['failures'])} failures pending M2/M3):")
            for item in data["failures"]:
                print(f"  * [{item['id']}] {item['filename']} ({item['domain']} / {item['edge_case_type']})")
                for k, v in item["diffs"].items():
                    print(f"      - {k}: expected={v['expected']!r}, got={v['actual']!r}")

        print(f"\nSummary JSON exported to: {self.json_output_path.resolve()}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline E2E Benchmark Runner for Media Sorter Pattern Recognition."
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Filter execution by specific domain (e.g. 'Anime', 'Standard TV', 'Movies').",
    )
    parser.add_argument(
        "--case",
        type=str,
        default=None,
        help="Filter execution by specific BenchmarkCase ID (e.g. 'TV-01', 'ANIME-04').",
    )
    parser.add_argument(
        "--json-output",
        type=str,
        default=str(DEFAULT_JSON_PATH),
        help="Output JSON summary destination path.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output reporting.",
    )
    parser.add_argument(
        "--no-diffs",
        action="store_true",
        help="Suppress detailed failure diff output.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero status code if any benchmark case fails.",
    )

    args = parser.parse_args()

    selected_cases = BENCHMARK_CASES
    if args.domain:
        selected_cases = [c for c in selected_cases if c.domain.lower() == args.domain.lower()]
        if not selected_cases:
            print(f"Error: No benchmark cases match domain '{args.domain}'", file=sys.stderr)
            return 2

    if args.case:
        selected_cases = [c for c in selected_cases if c.id.upper() == args.case.upper()]
        if not selected_cases:
            print(f"Error: No benchmark case matches ID '{args.case}'", file=sys.stderr)
            return 2

    runner = BenchmarkRunner(
        cases=selected_cases,
        json_output_path=Path(args.json_output),
        verbose=args.verbose,
        show_diffs=not args.no_diffs,
        strict=args.strict,
    )

    summary_data = runner.run()
    runner.print_terminal_report(summary_data)

    if args.strict and summary_data["summary"]["failed_cases"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
