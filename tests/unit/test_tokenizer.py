from pathlib import Path
import pytest
from media_sorter.tokenizer import FilenameTokenizer


@pytest.fixture
def tokenizer():
    return FilenameTokenizer()


def test_tv_show_tokenization(tokenizer):
    tokens = tokenizer.tokenize(Path("Breaking.Bad.S05E14.Ozymandias.1080p.BluRay.x264-ROVERS.mkv"))
    assert tokens.is_episodic is True
    assert tokens.title == "Breaking Bad"
    assert tokens.season == 5
    assert tokens.episode == 14
    assert tokens.episode_title == "Ozymandias"
    assert tokens.resolution == "1080p"
    assert tokens.source == "BLURAY"
    assert tokens.video_codec == "x264"
    assert tokens.group == "ROVERS"


def test_tv_multi_episode(tokenizer):
    tokens = tokenizer.tokenize(Path("Stranger.Things.S04E01-E02.Chapter.One.720p.WEB-DL.mkv"))
    assert tokens.is_episodic is True
    assert tokens.season == 4
    assert tokens.episode == 1
    assert tokens.multi_episodes == [1, 2]
    assert tokens.resolution == "720p"


def test_anime_fansub_tokenization(tokenizer):
    tokens = tokenizer.tokenize(Path("[SubsPlease] Frieren - Beyond Journey's End - 01 (1080p) [ABCD1234].mkv"))
    assert tokens.is_anime is True
    assert tokens.is_episodic is True
    assert tokens.group == "SubsPlease"
    assert "Frieren" in tokens.title
    assert tokens.episode == 1
    assert tokens.season == 1


def test_movie_tokenization(tokenizer):
    tokens = tokenizer.tokenize(Path("Inception.2010.2160p.UHD.Remux.HEVC.TrueHD.Atmos-FraMeSToR.mkv"))
    assert tokens.is_episodic is False
    assert tokens.title == "Inception"
    assert tokens.year == 2010
    assert tokens.resolution == "2160p"
    assert tokens.video_codec == "hevc"
    assert tokens.audio_codec == "TRUEHD"


def test_music_track_tokenization(tokenizer):
    tokens = tokenizer.tokenize(Path("/Music/Daft Punk - Discovery/02 - One More Time.flac"))
    assert tokens.is_music is True
    assert tokens.track == 2
    assert tokens.title == "One More Time"
    assert tokens.artist == "Daft Punk"
    assert tokens.album == "Discovery"


def test_camera_and_date_tokenization(tokenizer):
    tokens = tokenizer.tokenize(Path("IMG_20240815_142301.jpg"))
    assert tokens.is_photo_or_home_video is True
    assert tokens.date_stamp == "2024-08-15"
    assert tokens.year == 2024


def test_podcast_tokenization(tokenizer):
    tokens = tokenizer.tokenize(Path("The Daily - 2026-03-12 - The Sunday Read.mp3"))
    assert tokens.artist == "The Daily"
    assert tokens.year == 2026
    assert tokens.date_stamp == "2026-03-12"
    assert tokens.title == "The Sunday Read"


def test_movie_with_dimensions_not_episodic(tokenizer):
    tokens = tokenizer.tokenize(Path("Interstellar.1920x1080.mkv"))
    assert tokens.is_episodic is False
    assert tokens.season is None
    assert tokens.episode is None
    assert tokens.resolution == "1080p"
    assert "Interstellar" in tokens.title

    tokens4k = tokenizer.tokenize(Path("Dune.Part.Two.3840x2160.mkv"))
    assert tokens4k.is_episodic is False
    assert tokens4k.season is None
    assert tokens4k.episode is None
    assert tokens4k.resolution == "2160p"


def test_movie_bracket_group_year_not_anime(tokenizer):
    tokens = tokenizer.tokenize(Path("[YTS.MX] Movie Title - 2024 [1080p].mkv"))
    assert tokens.is_anime is False
    assert tokens.is_episodic is False
    assert tokens.year == 2024
    assert tokens.title == "Movie Title"

