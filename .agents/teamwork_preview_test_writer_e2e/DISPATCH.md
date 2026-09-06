## 2026-09-05T23:53:52Z
Your working directory is: /md0/media-sorter/.agents/teamwork_preview_test_writer_e2e
The authoritative original request is: /md0/media-sorter/.agents/ORIGINAL_REQUEST.md
You MUST read /md0/media-sorter/.agents/ORIGINAL_REQUEST.md before starting work.

Context & Prior Explorer Findings:
- Read /md0/media-sorter/.agents/orchestrator_2/PROJECT.md
- Read /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_2/handoff.md (sections 4.2, 4.3)
- Read /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_1/handoff.md

Write Ownership (Exclusive):
- tests/benchmark/__init__.py
- tests/benchmark/benchmark_cases.py
- tests/benchmark/test_benchmark.py
- tests/benchmark/runner.py
- /md0/media-sorter/TEST_READY.md
You MUST NOT edit any application source code (`src/media_sorter/*`) or existing unit tests.

Mission:
Implement the E2E Benchmark Test Suite & Offline Runner (Requirement R2).

Tasks:
1. Establish `tests/benchmark/benchmark_cases.py`:
   - Define dataclass `BenchmarkCase` with fields:
     `id: str`, `domain: str`, `filename: str`, `expected_category: str`, `expected_title: str`,
     `expected_year: Optional[int] = None`, `expected_season: Optional[int] = None`,
     `expected_episode: Optional[int] = None`, `expected_multi_episodes: Optional[List[int]] = None`,
     `expected_date: Optional[str] = None`, `expected_edition: Optional[str] = None`,
     `expected_part: Optional[int] = None`, `expected_group: Optional[str] = None`,
     `expected_destination_subpath: Optional[str] = None`, `edge_case_type: str = ""`
   - Build a comprehensive inventory of 55+ real-world media filename patterns across 6 domains:
     * Standard TV: SxxExx, multi-ep ranges (`E01-E02`), concatenated `E01E02`, scene `1x09`, scene multi-ep `2x01-02`, Roman numerals (`Rome.Season.II.Episode.IV`), season packs (`Succession.S02.Complete.1080p`).
     * Anime: Fansub brackets `[SubsPlease] Frieren - 01 (1080p)`, Kanji titles, title parentheses `[HorribleSubs] Fairy Tail (2014) - 176 [720p]`, 4-digit absolute numbering `[Erai-raws] One Piece - 1088`, multi-episode anime `[SubsPlease] Dungeon Meshi - 01-02`, OVAs `[TaigaSubs] Attack on Titan OVA - 01`, standalone keywords `Naruto Episode 207`.
     * Movies: Release years `Inception.2010`, numbers in title `1917.2019.1080p`, `2001.A.Space.Odyssey.1968`, `Blade.Runner.2049.2017`, `Wonder.Woman.1984.2020`, multi-part `Titanic.1997.DVD.CD1.avi`, `Kill.Bill.Vol.1.2003`, special editions `Extended`, `Director's Cut`, `Remastered`, `Criterion`, `Final Cut`.
     * Specials & Extras: Season 00 TV specials (`The.Office.S00E01.The.Outtakes`, `Doctor.Who.S00E25`), bonus featurettes, deleted scenes.
     * Daily / Dated Shows: ISO dated `The.Daily.Show.2024-01-15`, dot dates `The.Tonight.Show.2024.03.12`, underscore dates, dated podcasts.
     * Messy & Complex: Accented characters `Amélie.2001`, Apple TV/HDTV scene tags, resolution dimensions `1920x1080`, subtitle language tags `.forced.srt`, illegal characters, Windows reserved device names.

2. Establish `tests/benchmark/test_benchmark.py`:
   - Implement pytest test runner parametrized over all benchmark cases:
     `@pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.id)`
   - Must run 100% offline with zero external network connectivity and zero mutations to real disk storage.
   - Tests `FilenameTokenizer().tokenize(Path(case.filename))`, `MediaClassifier().classify()`, and `MediaNamer().generate_destination_path()`.
   - Provide clear assertions comparing tokens, category, and destination path against expected values.

3. Establish `tests/benchmark/runner.py`:
   - Standalone CLI benchmark runner executable via `.venv/bin/python -m tests.benchmark.runner`.
   - Computes per-domain pass/fail statistics, execution timing, and field diffs for any failed case.
   - Renders a clean terminal summary table and exports `tests/benchmark/benchmark_summary.json`.

4. Publish `/md0/media-sorter/TEST_READY.md`:
   - Document test runner invocation command (`.venv/bin/pytest tests/benchmark/test_benchmark.py` and `.venv/bin/python -m tests.benchmark.runner`).
   - Complete coverage table across all 6 domains and 55+ test cases.
   - Initial pass/fail baseline report noting current gaps (which M2 and M3 will fix).

5. Verification:
   Run your runner via `.venv/bin/python -m tests.benchmark.runner` and run `.venv/bin/pytest tests/benchmark/test_benchmark.py` (it is expected that some edge cases will fail initially against current codebase; the suite itself must run cleanly without crashing).
   Verify that all existing 75 tests in `tests/` continue to pass via `.venv/bin/pytest tests/unit/ tests/integration/`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Write your progress in `progress.md` and complete handoff report in `handoff.md` with execution outputs and coverage metrics.
