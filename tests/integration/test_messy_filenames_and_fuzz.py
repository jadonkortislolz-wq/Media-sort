from pathlib import Path
import pytest
from hypothesis import given, settings, strategies as st
from media_sorter.namer import FORBIDDEN_CHARS_PATTERN, RESERVED_NAMES, sanitize_filename_component
from media_sorter.tokenizer import FilenameTokenizer


@pytest.fixture
def tokenizer():
    return FilenameTokenizer()


# -----------------------------------------------------------------------------
# Real-World Messy Scene & International Filenames
# -----------------------------------------------------------------------------

MESSY_CASES = [
    (
        "[HorribleSubs] Shingeki no Kyojin - 59 [1080p].mkv",
        {"title": "Shingeki no Kyojin", "episode": 59, "is_anime": True},
    ),
    (
        "[SubsPlease] 葬送のフリーレン - 12 (1080p) [98E7B1A2].mkv",
        {"title": "葬送のフリーレン", "episode": 12, "is_anime": True},
    ),
    (
        "Amélie.2001.PROPER.REMASTERED.1080p.BluRay.x264-CiNEFiLE.mkv",
        {"title": "Amélie", "year": 2001, "resolution": "1080p"},
    ),
    (
        "Doctor.Who.2005.S01E01.Rose.720p.HDTV.x264-FoV.mkv",
        {"title": "Doctor Who", "year": 2005, "season": 1, "episode": 1},
    ),
    (
        "Game of Thrones - 1x09 - Baelor [720p HDTV].mkv",
        {"title": "Game of Thrones", "season": 1, "episode": 9},
    ),
    (
        "Mission.Impossible.Dead.Reckoning.Part.One.2023.2160p.WEB-DL.DDP5.1.Atmos.DV.HDR.H.265-FLUX.mkv",
        {"year": 2023, "resolution": "2160p", "video_codec": "h265"},
    ),
]


@pytest.mark.parametrize("filename,expected", MESSY_CASES)
def test_real_world_messy_filenames(tokenizer, filename, expected):
    tokens = tokenizer.tokenize(Path(filename))
    for key, val in expected.items():
        assert getattr(tokens, key) == val, f"Failed match for {key} in {filename}"


# -----------------------------------------------------------------------------
# Property-Based Fuzz Testing with Hypothesis
# -----------------------------------------------------------------------------

@given(st.text(min_size=1, max_size=500))
@settings(max_examples=150)
def test_sanitize_filename_component_fuzz(input_text):
    result = sanitize_filename_component(input_text, max_length=120)

    # 1. Result must never be empty
    assert len(result) > 0

    # 2. Result must contain no forbidden characters
    assert not FORBIDDEN_CHARS_PATTERN.search(result)

    # 3. Result must not have leading or trailing dots, spaces, or hyphens
    assert not result.startswith((" ", ".", "-"))
    assert not result.endswith((" ", ".", "-"))

    # 4. Result base name must not be a Windows reserved device name
    upper_base = result.split(".")[0].upper()
    assert upper_base not in RESERVED_NAMES

    # 5. Encoded byte length must stay within requested boundary (plus extension tolerance)
    assert len(result.encode("utf-8")) <= 140
