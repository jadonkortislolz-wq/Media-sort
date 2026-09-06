import sys
from pathlib import Path

# Add project root
sys.path.insert(0, "/md0/media-sorter")

from tests.benchmark.benchmark_cases import BENCHMARK_CASES
from media_sorter.tokenizer import FilenameTokenizer

tokenizer = FilenameTokenizer()

print(f"Total benchmark cases: {len(BENCHMARK_CASES)}")
tokenizer_mismatches = []

for case in BENCHMARK_CASES:
    p = Path(case.filename)
    tokens = tokenizer.tokenize(p)
    mismatches = {}
    
    if case.expected_title != tokens.title:
        mismatches["title"] = (case.expected_title, tokens.title)
    if case.expected_year is not None and case.expected_year != tokens.year:
        mismatches["year"] = (case.expected_year, tokens.year)
    if case.expected_season is not None and case.expected_season != tokens.season:
        mismatches["season"] = (case.expected_season, tokens.season)
    if case.expected_episode is not None and case.expected_episode != tokens.episode:
        mismatches["episode"] = (case.expected_episode, tokens.episode)
    if case.expected_multi_episodes is not None:
        actual_multi = getattr(tokens, "multi_episodes", [])
        if actual_multi != case.expected_multi_episodes:
            mismatches["multi_episodes"] = (case.expected_multi_episodes, actual_multi)
    if case.expected_date is not None:
        actual_date = getattr(tokens, "air_date", None) or getattr(tokens, "date_stamp", None)
        if actual_date != case.expected_date:
            mismatches["date"] = (case.expected_date, actual_date)
    if case.expected_edition is not None:
        actual_edition = getattr(tokens, "edition", None)
        if actual_edition != case.expected_edition:
            mismatches["edition"] = (case.expected_edition, actual_edition)
    if case.expected_part is not None:
        actual_part = getattr(tokens, "part", None)
        if actual_part != case.expected_part:
            mismatches["part"] = (case.expected_part, actual_part)
    if case.expected_group is not None:
        actual_group = getattr(tokens, "group", None)
        if actual_group != case.expected_group:
            mismatches["group"] = (case.expected_group, actual_group)
            
    if mismatches:
        tokenizer_mismatches.append((case, mismatches))

print(f"Tokenizer mismatches count: {len(tokenizer_mismatches)} / {len(BENCHMARK_CASES)}")
for case, diffs in tokenizer_mismatches:
    print(f"[{case.id}] ({case.domain} / {case.edge_case_type}) {case.filename}")
    for k, (exp, act) in diffs.items():
        print(f"    {k}: expected={exp!r} got={act!r}")
