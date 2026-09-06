import sys
from pathlib import Path

# Add project root
sys.path.insert(0, "/md0/media-sorter")

from tests.benchmark.benchmark_cases import BENCHMARK_CASES, evaluate_benchmark_case

print(f"Total benchmark cases: {len(BENCHMARK_CASES)}")

category_mismatches = []
subpath_mismatches = []

for case in BENCHMARK_CASES:
    res = evaluate_benchmark_case(case)
    if not res.passed:
        diff_keys = list(res.diffs.keys())
        if "category" in diff_keys:
            category_mismatches.append((case, res.diffs["category"]))
        if "destination_subpath" in diff_keys:
            subpath_mismatches.append((case, res.diffs["destination_subpath"]))

print(f"\n--- Category Mismatches: {len(category_mismatches)} ---")
for case, diff in category_mismatches:
    print(f"[{case.id}] ({case.domain}) {case.filename}: expected={diff['expected']} got={diff['actual']}")

print(f"\n--- Destination Subpath Mismatches: {len(subpath_mismatches)} ---")
print(f"Total subpath mismatches: {len(subpath_mismatches)}")
