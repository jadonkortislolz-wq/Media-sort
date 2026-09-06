import sys
sys.path.insert(0, "/md0/media-sorter")
from pathlib import Path

from test_enhanced_prototype import EnhancedTokenizer
from media_sorter.classifier import MediaClassifier, ClassificationResult
from media_sorter.namer import MediaNamer, sanitize_filename_component
from tests.benchmark.benchmark_cases import BENCHMARK_CASES, create_benchmark_inputs

tok = EnhancedTokenizer()
classifier = MediaClassifier(confidence_threshold=0.75, provider=None)

class EnhancedMediaNamer(MediaNamer):
    def generate_destination_path(self, cls_result, primary_dst_path=None):
        cat = cls_result.category
        tokens = cls_result.tokens
        meta = cls_result.metadata
        src_path = meta.path if meta else Path("file")
        ext = src_path.suffix.lstrip(".")
        base_dir = self.settings.get_destination_path(cat)

        if cls_result.needs_quarantine or cat == "unknown":
            return super().generate_destination_path(cls_result, primary_dst_path)

        if cat in ("subtitle", "artwork", "metadata"):
            return self._format_sidecar_path(cls_result, primary_dst_path, base_dir)

        # Enhanced Movie path
        if cat == "movie":
            # Extra suffix
            stem_lower = src_path.stem.lower()
            extra_suffix = ""
            for extra in ("-behindthescenes", "-featurette", "-deleted", "-trailer"):
                if extra in stem_lower:
                    extra_suffix = extra
                    break
            
            edition_str = f" [{tokens.edition}]" if (tokens and tokens.edition) else ""
            part_str = f" [{tokens.part_label}]" if (tokens and tokens.part_label) else ""
            title = tokens.title if (tokens and tokens.title) else src_path.stem
            
            if tokens and tokens.year:
                folder_name = f"{title} ({tokens.year})"
                if extra_suffix:
                    file_name = f"{folder_name}{extra_suffix}.{ext}"
                else:
                    file_name = f"{folder_name}{edition_str}{part_str}.{ext}"
            else:
                folder_name = title
                file_name = f"{title}.{ext}"
            return base_dir / folder_name / file_name

        # Enhanced TV path
        if cat == "tv":
            title = tokens.title if (tokens and tokens.title) else src_path.stem
            s_num = tokens.season if (tokens and tokens.season is not None) else 1
            
            if tokens and tokens.is_daily and tokens.air_date:
                folder_name = f"Season {s_num}"
                file_name = f"{title} - {tokens.air_date}.{ext}"
            elif tokens and tokens.is_season_pack:
                folder_name = f"Season {s_num:02d}"
                file_name = f"{title} - Season {s_num:02d}.{ext}"
            else:
                folder_name = f"Season {s_num:02d}"
                if tokens and tokens.multi_episodes:
                    first_ep = tokens.multi_episodes[0]
                    last_ep = tokens.multi_episodes[-1]
                    file_name = f"{title} - S{s_num:02d}E{first_ep:02d}-E{last_ep:02d}.{ext}"
                else:
                    ep_num = tokens.episode if (tokens and tokens.episode is not None) else 1
                    file_name = f"{title} - S{s_num:02d}E{ep_num:02d}.{ext}"
            return base_dir / title / folder_name / file_name

        # Enhanced Anime path
        if cat == "anime":
            title = tokens.title if (tokens and tokens.title) else src_path.stem
            grp_str = f" [{tokens.group}]" if (tokens and tokens.group) else ""
            if tokens and tokens.multi_episodes:
                first_ep = tokens.multi_episodes[0]
                last_ep = tokens.multi_episodes[-1]
                file_name = f"{title} - {first_ep:02d}-{last_ep:02d}{grp_str}.{ext}"
            elif tokens and tokens.episode is not None:
                ep_str = f"{tokens.episode:02d}" if tokens.episode < 100 else f"{tokens.episode}"
                file_name = f"{title} - {ep_str}{grp_str}.{ext}"
            else:
                file_name = f"{title}{grp_str}.{ext}"
            return base_dir / title / file_name

        return super().generate_destination_path(cls_result, primary_dst_path)

passed_count = 0
failed_cases = []

for case in BENCHMARK_CASES:
    file_path = Path(case.filename)
    scanned, metadata, settings, primary_dst = create_benchmark_inputs(case)
    tokens = tok.tokenize(file_path)
    cls_result = classifier.classify(scanned, tokens, metadata)
    namer = EnhancedMediaNamer(settings)
    dest_path = namer.generate_destination_path(cls_result, primary_dst_path=primary_dst)
    base_dir = settings.get_destination_base_path()
    try:
        subpath = dest_path.relative_to(base_dir).as_posix()
    except ValueError:
        subpath = dest_path.as_posix()

    diffs = {}
    if cls_result.category != case.expected_category:
        diffs["category"] = (case.expected_category, cls_result.category)
    if tokens.title != case.expected_title:
        diffs["title"] = (case.expected_title, tokens.title)
    if case.expected_destination_subpath and subpath != case.expected_destination_subpath:
        diffs["subpath"] = (case.expected_destination_subpath, subpath)

    if not diffs:
        passed_count += 1
    else:
        failed_cases.append((case, diffs))

print(f"\nSimulated E2E Benchmark: {passed_count} / {len(BENCHMARK_CASES)} passed ({passed_count/len(BENCHMARK_CASES)*100:.1f}%)")
for case, d in failed_cases:
    print(f"[{case.id}] ({case.domain}) {case.filename}")
    for k, (exp, act) in d.items():
        print(f"    {k}: expected={exp!r} got={act!r}")
