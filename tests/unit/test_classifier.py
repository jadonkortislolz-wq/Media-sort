from pathlib import Path
import pytest
from media_sorter.analyzer import MediaMetadata, StreamInfo
from media_sorter.classifier import MediaClassifier
from media_sorter.providers import MockMetadataProvider, ProviderResult
from media_sorter.scanner import ScannedFile
from media_sorter.tokenizer import FilenameTokenizer, TokenizedFilename


@pytest.fixture
def classifier():
    return MediaClassifier(confidence_threshold=0.75)


def test_classify_tv_show(classifier):
    scanned = ScannedFile(path=Path("/downloads/Game.of.Thrones.S01E01.1080p.mkv"), size=1000000, mtime=1000.0)
    tokens = TokenizedFilename(
        raw_name="Game.of.Thrones.S01E01.1080p.mkv",
        title="Game of Thrones",
        season=1,
        episode=1,
        is_episodic=True,
    )
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="video/x-matroska",
        container="mkv",
        duration_seconds=3600,
        has_video=True,
    )

    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "tv"
    assert res.confidence >= 0.75
    assert res.needs_quarantine is False


def test_classify_anime(classifier):
    scanned = ScannedFile(path=Path("/downloads/[SubsPlease] Jujutsu Kaisen - 01 [1080p].mkv"), size=1000000, mtime=1000.0)
    tokens = TokenizedFilename(
        raw_name="[SubsPlease] Jujutsu Kaisen - 01 [1080p].mkv",
        title="Jujutsu Kaisen",
        episode=1,
        season=1,
        group="SubsPlease",
        is_anime=True,
        is_episodic=True,
    )
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="video/x-matroska",
        container="mkv",
        duration_seconds=1400,
        has_video=True,
    )

    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "anime"
    assert res.confidence >= 0.75
    assert res.needs_quarantine is False


def test_classify_movie(classifier):
    scanned = ScannedFile(path=Path("/downloads/Interstellar.2014.1080p.mkv"), size=5000000, mtime=1000.0)
    tokens = TokenizedFilename(
        raw_name="Interstellar.2014.1080p.mkv",
        title="Interstellar",
        year=2014,
        resolution="1080p",
    )
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="video/x-matroska",
        container="mkv",
        duration_seconds=10140,  # ~2.8 hours
        has_video=True,
    )

    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "movie"
    assert res.confidence >= 0.75
    assert res.needs_quarantine is False


def test_classify_music(classifier):
    scanned = ScannedFile(path=Path("/music/01 - Come Together.flac"), size=30000000, mtime=1000.0)
    tokens = TokenizedFilename(
        raw_name="01 - Come Together.flac",
        title="Come Together",
        track=1,
        is_music=True,
    )
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="audio/flac",
        container="flac",
        duration_seconds=259,
        has_audio=True,
        has_video=False,
        tags={"artist": "The Beatles", "album": "Abbey Road"},
    )

    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "music"
    assert res.confidence >= 0.75
    assert res.needs_quarantine is False


def test_classify_audiobook(classifier):
    scanned = ScannedFile(path=Path("/audiobooks/Dune - Part 01.m4b"), size=50000000, mtime=1000.0)
    tokens = TokenizedFilename(raw_name="Dune - Part 01.m4b", title="Dune")
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="audio/mp4",
        container="m4b",
        duration_seconds=28800,  # 8 hours
        has_audio=True,
        has_video=False,
        tags={"narrator": "George Guidall"},
    )

    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "audiobook"
    assert res.confidence >= 0.75
    assert res.needs_quarantine is False


def test_low_confidence_triggers_quarantine(classifier):
    # Ambiguous video clip with no year, no episode, no metadata
    scanned = ScannedFile(path=Path("/incoming/unknown_recording_xyz.mkv"), size=10000, mtime=1000.0)
    tokens = TokenizedFilename(raw_name="unknown_recording_xyz.mkv", title="unknown recording xyz")
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="video/x-matroska",
        container="mkv",
        duration_seconds=120,
        has_video=True,
    )

    res = classifier.classify(scanned, tokens, meta)
    assert res.confidence < 0.75
    assert res.needs_quarantine is True
    assert res.quarantine_reason is not None


def test_unsupported_format_triggers_quarantine(classifier):
    scanned = ScannedFile(path=Path("/incoming/corrupt_data.bin"), size=1000, mtime=1000.0)
    tokens = TokenizedFilename(raw_name="corrupt_data.bin")
    meta = MediaMetadata(path=scanned.path, mime_type="application/octet-stream", container="bin")

    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "unknown"
    assert res.needs_quarantine is True


def test_classify_with_metadata_provider():
    mock_prov = MockMetadataProvider(
        mock_data={
            "movie:oppenheimer": ProviderResult(
                canonical_title="Oppenheimer",
                year=2023,
                media_type="movie",
                confidence_boost=0.15,
            ),
            "tv:the last of us": ProviderResult(
                canonical_title="The Last of Us",
                year=2023,
                media_type="tv",
                season=1,
                episode=3,
                episode_title="Long, Long Time",
                confidence_boost=0.20,
            ),
        }
    )
    prov_classifier = MediaClassifier(confidence_threshold=0.75, provider=mock_prov)

    # 1. Movie verified with provider
    scanned_m = ScannedFile(path=Path("/downloads/Oppenheimer.mkv"), size=1000000, mtime=1000.0)
    tokens_m = TokenizedFilename(raw_name="Oppenheimer.mkv", title="Oppenheimer")
    meta_m = MediaMetadata(path=scanned_m.path, mime_type="video/x-matroska", container="mkv", duration_seconds=10800, has_video=True)
    res_m = prov_classifier.classify(scanned_m, tokens_m, meta_m)
    assert res_m.category == "movie"
    assert res_m.provider_result is not None
    assert res_m.provider_result.year == 2023

    # 2. TV Show verified with provider
    scanned_tv = ScannedFile(path=Path("/downloads/The.Last.of.Us.S01E03.mkv"), size=1000000, mtime=1000.0)
    tokens_tv = TokenizedFilename(raw_name="The.Last.of.Us.S01E03.mkv", title="The Last of Us", season=1, episode=3, is_episodic=True)
    meta_tv = MediaMetadata(path=scanned_tv.path, mime_type="video/x-matroska", container="mkv", duration_seconds=4500, has_video=True)
    res_tv = prov_classifier.classify(scanned_tv, tokens_tv, meta_tv)
    assert res_tv.category == "tv"
    assert res_tv.provider_result is not None
    assert res_tv.provider_result.episode_title == "Long, Long Time"


def test_classify_podcast(classifier):
    scanned = ScannedFile(path=Path("/podcasts/Hardcore History 2023-05-12 Episode 68.mp3"), size=50000000, mtime=1000.0)
    tokens = TokenizedFilename(raw_name="Hardcore History 2023-05-12 Episode 68.mp3", title="Episode 68", date_stamp="2023-05-12")
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="audio/mpeg",
        container="mp3",
        duration_seconds=14400,
        has_audio=True,
        has_video=False,
        tags={"podcast": "Dan Carlin's Hardcore History"},
    )
    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "podcast"
    assert res.confidence >= 0.75


def test_classify_photo_and_home_video(classifier):
    # Photo test
    scanned_p = ScannedFile(path=Path("/photos/IMG_20250615_123456.jpg"), size=4000000, mtime=1000.0)
    tokens_p = TokenizedFilename(raw_name="IMG_20250615_123456.jpg", is_photo_or_home_video=True, date_stamp="2025-06-15")
    meta_p = MediaMetadata(path=scanned_p.path, mime_type="image/jpeg", container="jpeg", tags={"camera_model": "Pixel 9 Pro"})
    res_p = classifier.classify(scanned_p, tokens_p, meta_p)
    assert res_p.category == "photo"
    assert res_p.confidence >= 0.90

    # Home Video test
    scanned_v = ScannedFile(path=Path("/home_videos/VID_20250615_140000.mp4"), size=20000000, mtime=1000.0)
    tokens_v = TokenizedFilename(raw_name="VID_20250615_140000.mp4", is_photo_or_home_video=True, date_stamp="2025-06-15")
    meta_v = MediaMetadata(path=scanned_v.path, mime_type="video/mp4", container="mp4", duration_seconds=120, has_video=True)
    res_v = classifier.classify(scanned_v, tokens_v, meta_v)
    assert res_v.category == "home_video"


def test_classify_archive(classifier):
    scanned = ScannedFile(path=Path("/downloads/Season1_Extras.zip"), size=500000000, mtime=1000.0)
    tokens = TokenizedFilename(raw_name="Season1_Extras.zip")
    meta = MediaMetadata(path=scanned.path, mime_type="application/zip", container="zip")
    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "archive"
    assert res.confidence >= 0.90


def test_classify_movie_with_hdtv_and_rartv(classifier):
    scanned = ScannedFile(path=Path("/downloads/Gladiator.II.2024.1080p.HDTV.x264-[rartv].mkv"), size=4000000000, mtime=1000.0)
    tokens = TokenizedFilename(
        raw_name="Gladiator.II.2024.1080p.HDTV.x264-[rartv].mkv",
        title="Gladiator II",
        year=2024,
        resolution="1080p",
        video_codec="x264",
        source="HDTV",
        group="rartv",
    )
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="video/x-matroska",
        container="mkv",
        duration_seconds=5000,  # ~83 minutes
        has_video=True,
    )
    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "movie"
    assert res.confidence >= 0.75
    assert res.needs_quarantine is False


def test_classify_movie_with_apple_tv_tag(classifier):
    scanned = ScannedFile(path=Path("/downloads/Wolfs.2024.1080p.Apple.TV.WEB-DL.DDP5.1.Atmos.H.264.mkv"), size=4500000000, mtime=1000.0)
    tokens = TokenizedFilename(
        raw_name="Wolfs.2024.1080p.Apple.TV.WEB-DL.DDP5.1.Atmos.H.264.mkv",
        title="Wolfs",
        year=2024,
        resolution="1080p",
        video_codec="H.264",
        source="WEB-DL",
    )
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="video/x-matroska",
        container="mkv",
        duration_seconds=6400,
        has_video=True,
    )
    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "movie"
    assert res.confidence >= 0.75


def test_video_file_with_audio_not_classified_as_music(classifier):
    # Video container .mkv with audio track should never be classified as music
    scanned = ScannedFile(
        path=Path("/downloads/Star.Wars.The.Clone.Wars.S01E01.1080p.BluRay.REMUX.VC-1.DD5.1-NOGRP.mkv"),
        size=4500000000,
        mtime=1000.0,
    )
    tokens = TokenizedFilename(
        raw_name="Star.Wars.The.Clone.Wars.S01E01.1080p.BluRay.REMUX.VC-1.DD5.1-NOGRP.mkv",
        title="Star Wars The Clone Wars",
        season=1,
        episode=1,
        is_episodic=True,
    )
    meta = MediaMetadata(
        path=scanned.path,
        mime_type="video/x-matroska",
        container="mkv",
        has_audio=True,
        has_video=False,  # e.g. exotic codec in container
    )
    res = classifier.classify(scanned, tokens, meta)
    assert res.category == "tv"
    assert res.confidence >= 0.80
    assert res.needs_quarantine is False


