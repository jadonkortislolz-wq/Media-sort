import sys
sys.path.insert(0, "/md0/media-sorter")
from pathlib import Path

from test_enhanced_prototype import EnhancedTokenizer
from media_sorter.classifier import MediaClassifier
from media_sorter.namer import MediaNamer
from tests.benchmark.benchmark_cases import BENCHMARK_CASES, create_benchmark_inputs

tok = EnhancedTokenizer()
classifier = MediaClassifier(confidence_threshold=0.75, provider=None)

category_mismatches = []

for case in BENCHMARK_CASES:
    file_path = Path(case.filename)
    scanned, metadata, settings, primary_dst = create_benchmark_inputs(case)
    tokens = tok.tokenize(file_path)
    cls_result = classifier.classify(scanned, tokens, metadata)
    if cls_result.category != case.expected_category:
        category_mismatches.append((case, cls_result.category))

print(f"Remaining category mismatches: {len(category_mismatches)} / 64")
for case, act in category_mismatches:
    print(f"[{case.id}] ({case.domain}) {case.filename}: expected={case.expected_category} got={act}")
