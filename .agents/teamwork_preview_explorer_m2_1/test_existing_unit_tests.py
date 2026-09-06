import sys
sys.path.insert(0, "/md0/media-sorter")
from pathlib import Path
from test_enhanced_prototype import EnhancedTokenizer

tok = EnhancedTokenizer()

# 1. test_tv_show_tokenization
t1 = tok.tokenize(Path("Breaking.Bad.S05E14.Ozymandias.1080p.BluRay.x264-ROVERS.mkv"))
assert t1.is_episodic is True
assert t1.title == "Breaking Bad"
assert t1.season == 5
assert t1.episode == 14
assert t1.episode_title == "Ozymandias"
assert t1.resolution == "1080p"
assert t1.source == "BLURAY"
assert t1.video_codec == "x264"
assert t1.group == "ROVERS"
print("test_tv_show_tokenization: PASS")

# 2. test_tv_multi_episode
t2 = tok.tokenize(Path("Stranger.Things.S04E01-E02.Chapter.One.720p.WEB-DL.mkv"))
assert t2.is_episodic is True
assert t2.season == 4
assert t2.episode == 1
assert t2.multi_episodes == [1, 2]
assert t2.resolution == "720p"
print("test_tv_multi_episode: PASS")

# 3. test_anime_fansub_tokenization
t3 = tok.tokenize(Path("[SubsPlease] Frieren - Beyond Journey's End - 01 (1080p) [ABCD1234].mkv"))
assert t3.is_anime is True
assert t3.is_episodic is True
assert t3.group == "SubsPlease"
assert "Frieren" in t3.title
assert t3.episode == 1
assert t3.season == 1
print("test_anime_fansub_tokenization: PASS")

# 4. test_movie_tokenization
t4 = tok.tokenize(Path("Inception.2010.2160p.UHD.Remux.HEVC.TrueHD.Atmos-FraMeSToR.mkv"))
assert t4.is_episodic is False
assert t4.title == "Inception"
assert t4.year == 2010
assert t4.resolution == "2160p"
assert t4.video_codec == "hevc"
assert t4.audio_codec == "TRUEHD"
print("test_movie_tokenization: PASS")

# 5. test_music_track_tokenization
t5 = tok.tokenize(Path("/Music/Daft Punk - Discovery/02 - One More Time.flac"))
assert t5.is_music is True
assert t5.track == 2
assert t5.title == "One More Time"
assert t5.artist == "Daft Punk"
assert t5.album == "Discovery"
print("test_music_track_tokenization: PASS")

# 6. test_camera_and_date_tokenization
t6 = tok.tokenize(Path("IMG_20240815_142301.jpg"))
assert t6.is_photo_or_home_video is True
assert t6.date_stamp == "2024-08-15"
assert t6.year == 2024
print("test_camera_and_date_tokenization: PASS")

# 7. test_podcast_tokenization
t7 = tok.tokenize(Path("The Daily - 2026-03-12 - The Sunday Read.mp3"))
assert t7.artist == "The Daily"
assert t7.year == 2026
assert t7.date_stamp == "2026-03-12"
assert t7.title == "The Sunday Read"
print("test_podcast_tokenization: PASS")

# 8. test_movie_with_dimensions_not_episodic
t8 = tok.tokenize(Path("Interstellar.1920x1080.mkv"))
assert t8.is_episodic is False
assert t8.season is None
assert t8.episode is None
assert t8.resolution == "1080p"
assert "Interstellar" in t8.title

t8b = tok.tokenize(Path("Dune.Part.Two.3840x2160.mkv"))
assert t8b.is_episodic is False
assert t8b.season is None
assert t8b.episode is None
assert t8b.resolution == "2160p"
print("test_movie_with_dimensions_not_episodic: PASS")

# 9. test_movie_bracket_group_year_not_anime
t9 = tok.tokenize(Path("[YTS.MX] Movie Title - 2024 [1080p].mkv"))
assert t9.is_anime is False
assert t9.is_episodic is False
assert t9.year == 2024
assert t9.title == "Movie Title"
print("test_movie_bracket_group_year_not_anime: PASS")

# 10. test_standalone_episode_tokenization
t10 = tok.tokenize(Path("Naruto Episode 207 The Supposed Sealed Ability.mkv"))
assert t10.is_episodic is True
assert t10.title == "Naruto"
assert t10.season == 1
assert t10.episode == 207
assert t10.episode_title == "The Supposed Sealed Ability"
print("test_standalone_episode_tokenization: PASS")

# 11. test_anime_fansub_without_group_tokenization
t11 = tok.tokenize(Path("BLEACH꞉ Sennen Kessen-hen - 27 E89717B7].mkv"))
assert t11.is_anime is True
assert t11.is_episodic is True
assert "BLEACH" in t11.title
assert t11.episode == 27
assert t11.season == 1
print("test_anime_fansub_without_group_tokenization: PASS")

# 12. test_anime_ending_opening_tokenization
t12 = tok.tokenize(Path("[A&C] Sword Art Online Alicization S03ED01 [BDrip 1080p] [09F0EA6C].mkv"))
assert t12.is_episodic is True
assert "Sword Art Online" in t12.title
assert t12.season == 3
assert t12.episode == 1
print("test_anime_ending_opening_tokenization: PASS")

print("\nALL 12 EXISTING UNIT TESTS PASSED WITH ENHANCED TOKENIZER!")
