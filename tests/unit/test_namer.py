from pathlib import Path
import pytest
from media_sorter.analyzer import MediaMetadata
from media_sorter.classifier import ClassificationResult
from media_sorter.config import Settings
from media_sorter.namer import MediaNamer, sanitize_filename_component
from media_sorter.tokenizer import TokenizedFilename


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def namer(settings):
    return MediaNamer(settings)


def test_sanitize_filename_forbidden_chars():
    messy = 'Movie: "The Final Chapter" <Director\'s Cut> | Part 1?.mkv'
    cleaned = sanitize_filename_component(messy)
    assert ":" not in cleaned
    assert '"' not in cleaned
    assert "<" not in cleaned
    assert ">" not in cleaned
    assert "|" not in cleaned
    assert "?" not in cleaned
    assert cleaned.endswith(".mkv")


def test_sanitize_windows_reserved_names():
    res = sanitize_filename_component("CON.mp4")
    assert res == "_CON.mp4"
    res2 = sanitize_filename_component("nul.txt")
    assert res2 == "_nul.txt"


def test_generate_movie_destination(namer):
    tokens = TokenizedFilename(
        raw_name="The.Matrix.1999.1080p.BluRay.x264.mkv",
        title="The Matrix",
        year=1999,
        resolution="1080p",
        video_codec="x264",
    )
    meta = MediaMetadata(path=Path("The.Matrix.1999.1080p.BluRay.x264.mkv"), mime_type="video/x-matroska", container="mkv")
    cls_res = ClassificationResult(category="movie", confidence=0.95, tokens=tokens, metadata=meta)

    dest = namer.generate_destination_path(cls_res)
    assert "The Matrix (1999)" in str(dest)
    assert dest.suffix == ".mkv"


def test_generate_tv_destination(namer):
    tokens = TokenizedFilename(
        raw_name="Breaking Bad S01E01 Pilot.mkv",
        title="Breaking Bad",
        season=1,
        episode=1,
        episode_title="Pilot",
    )
    meta = MediaMetadata(path=Path("Breaking Bad S01E01 Pilot.mkv"), mime_type="video/x-matroska", container="mkv")
    cls_res = ClassificationResult(category="tv", confidence=0.95, tokens=tokens, metadata=meta)

    dest = namer.generate_destination_path(cls_res)
    assert "Season 01" in str(dest)
    assert "Breaking Bad - S01E01 - Pilot.mkv" in str(dest)


def test_generate_quarantine_destination(namer):
    meta = MediaMetadata(path=Path("weird_unknown_file.xyz"), mime_type="application/octet-stream", container="xyz")
    cls_res = ClassificationResult(
        category="unknown",
        confidence=0.1,
        metadata=meta,
        needs_quarantine=True,
        quarantine_reason="unrecognized_format",
    )

    dest = namer.generate_destination_path(cls_res)
    assert "Quarantine" in str(dest)
    assert "unrecognized-format" in str(dest) or "unrecognized_format" in str(dest)


def test_sidecar_subtitle_matching(namer):
    sub_meta = MediaMetadata(path=Path("movie.en.srt"), mime_type="text/plain", container="srt")
    cls_res = ClassificationResult(category="subtitle", confidence=0.95, metadata=sub_meta)
    primary_dst = Path("/organized/Movies/Inception (2010)/Inception (2010) [1080p].mkv")

    sub_dst = namer.generate_destination_path(cls_res, primary_dst_path=primary_dst)
    assert sub_dst.parent == primary_dst.parent
    assert sub_dst.name == "Inception (2010) [1080p].en.srt"
