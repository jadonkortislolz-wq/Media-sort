"""Automated E2E Benchmark Test Suite (Requirement R2).

Executes 100% offline with zero network connectivity and zero mutations to real disk storage.
Parametrized across all 60+ benchmark cases across the 6 media domains:
1. Standard TV
2. Anime
3. Movies
4. Specials & Extras
5. Daily / Dated Shows
6. Messy & Complex
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Ensure project root is in sys.path regardless of how pytest is invoked
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from tests.benchmark.benchmark_cases import (
        BENCHMARK_CASES,
        BenchmarkCase,
        evaluate_benchmark_case,
    )
except ImportError:
    from benchmark_cases import (  # type: ignore
        BENCHMARK_CASES,
        BenchmarkCase,
        evaluate_benchmark_case,
    )


@pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.id)
def test_benchmark(case: BenchmarkCase) -> None:
    """Execute end-to-end benchmark test for an individual media file pattern.

    Tests FilenameTokenizer tokenization, MediaClassifier classification, and
    MediaNamer destination path generation against expected baseline values.
    """
    result = evaluate_benchmark_case(case)

    if not result.passed:
        error_lines = [
            f"Benchmark case {case.id} ({case.domain} - {case.edge_case_type}) failed:",
            f"  Filename: {case.filename}",
        ]
        for field_name, mismatch in result.diffs.items():
            error_lines.append(
                f"  * {field_name}: expected={mismatch['expected']!r}, got={mismatch['actual']!r}"
            )
        pytest.fail("\n".join(error_lines))
