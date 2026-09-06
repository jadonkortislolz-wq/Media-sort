"""Benchmark Case Inventory and Data Structures (Requirement R2).

Defines the BenchmarkCase dataclass and a comprehensive suite of 60+ real-world
media filename patterns across 6 domains:
1. Standard TV (SxxExx, multi-ep, scene notation, Roman numerals, season packs)
2. Anime (Fansub brackets, Kanji titles, parenthesized years, 4-digit absolute numbering, OVAs)
3. Movies (Release years, numerical titles, multi-part CD1/CD2, special editions)
4. Specials & Extras (Season 00 specials, featurettes, trailers, deleted scenes)
5. Daily / Dated Shows (ISO dated, dot dated, underscore dated, dated podcasts)
6. Messy & Complex (Unicode accents, scene tags, resolution dimensions, forbidden chars, Windows reserved)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from media_sorter.analyzer import MediaMetadata
from media_sorter.config import Settings
from media_sorter.scanner import ScannedFile


@dataclass
class BenchmarkCase:
    id: str
    domain: str
    filename: str
    expected_category: str
    expected_title: str
    expected_year: Optional[int] = None
    expected_season: Optional[int] = None
    expected_episode: Optional[int] = None
    expected_multi_episodes: Optional[List[int]] = None
    expected_date: Optional[str] = None
    expected_edition: Optional[str] = None
    expected_part: Optional[int] = None
    expected_group: Optional[str] = None
    expected_destination_subpath: Optional[str] = None
    edge_case_type: str = ""


BENCHMARK_CASES: List[BenchmarkCase] = [
    # =========================================================================
    # Domain 1: Standard TV
    # =========================================================================
    BenchmarkCase(
        id="TV-01",
        domain="Standard TV",
        filename="Breaking.Bad.S05E14.Ozymandias.1080p.BluRay.x264-ROVERS.mkv",
        expected_category="tv",
        expected_title="Breaking Bad",
        expected_season=5,
        expected_episode=14,
        expected_group="ROVERS",
        expected_destination_subpath="TV Shows/Breaking Bad/Season 05/Breaking Bad - S05E14.mkv",
        edge_case_type="standard_sxxexx",
    ),
    BenchmarkCase(
        id="TV-02",
        domain="Standard TV",
        filename="Stranger.Things.S04E01-E02.Chapter.One.720p.WEB-DL.mkv",
        expected_category="tv",
        expected_title="Stranger Things",
        expected_season=4,
        expected_episode=1,
        expected_multi_episodes=[1, 2],
        expected_destination_subpath="TV Shows/Stranger Things/Season 04/Stranger Things - S04E01-E02.mkv",
        edge_case_type="multi_episode_hyphen_range",
    ),
    BenchmarkCase(
        id="TV-03",
        domain="Standard TV",
        filename="House.M.D.S03E01E02.1080p.mkv",
        expected_category="tv",
        expected_title="House M D",
        expected_season=3,
        expected_episode=1,
        expected_multi_episodes=[1, 2],
        expected_destination_subpath="TV Shows/House M D/Season 03/House M D - S03E01-E02.mkv",
        edge_case_type="multi_episode_concatenated",
    ),
    BenchmarkCase(
        id="TV-04",
        domain="Standard TV",
        filename="The.Wire.1x09.HDTV.mkv",
        expected_category="tv",
        expected_title="The Wire",
        expected_season=1,
        expected_episode=9,
        expected_destination_subpath="TV Shows/The Wire/Season 01/The Wire - S01E09.mkv",
        edge_case_type="scene_season_x_episode",
    ),
    BenchmarkCase(
        id="TV-05",
        domain="Standard TV",
        filename="The.Office.2x01-02.mkv",
        expected_category="tv",
        expected_title="The Office",
        expected_season=2,
        expected_episode=1,
        expected_multi_episodes=[1, 2],
        expected_destination_subpath="TV Shows/The Office/Season 02/The Office - S02E01-E02.mkv",
        edge_case_type="scene_multi_episode_range",
    ),
    BenchmarkCase(
        id="TV-06",
        domain="Standard TV",
        filename="Rome.Season.II.Episode.IV.mkv",
        expected_category="tv",
        expected_title="Rome",
        expected_season=2,
        expected_episode=4,
        expected_destination_subpath="TV Shows/Rome/Season 02/Rome - S02E04.mkv",
        edge_case_type="roman_numerals",
    ),
    BenchmarkCase(
        id="TV-07",
        domain="Standard TV",
        filename="Doctor Who Season 5 Episode 1 Eleventh Hour.mkv",
        expected_category="tv",
        expected_title="Doctor Who",
        expected_season=5,
        expected_episode=1,
        expected_destination_subpath="TV Shows/Doctor Who/Season 05/Doctor Who - S05E01.mkv",
        edge_case_type="word_season_episode",
    ),
    BenchmarkCase(
        id="TV-08",
        domain="Standard TV",
        filename="Succession.S02.Complete.1080p.WEB-DL.mkv",
        expected_category="tv",
        expected_title="Succession",
        expected_season=2,
        expected_destination_subpath="TV Shows/Succession/Season 02/Succession - Season 02.mkv",
        edge_case_type="season_pack_complete",
    ),
    BenchmarkCase(
        id="TV-09",
        domain="Standard TV",
        filename="Game.of.Thrones.S08E03.720p.HDTV.x264-AVS.mkv",
        expected_category="tv",
        expected_title="Game of Thrones",
        expected_season=8,
        expected_episode=3,
        expected_group="AVS",
        expected_destination_subpath="TV Shows/Game of Thrones/Season 08/Game of Thrones - S08E03.mkv",
        edge_case_type="standard_sxxexx_scene_group",
    ),
    BenchmarkCase(
        id="TV-10",
        domain="Standard TV",
        filename="Chernobyl.S01E05.Vichnaya.Pamyat.1080p.mkv",
        expected_category="tv",
        expected_title="Chernobyl",
        expected_season=1,
        expected_episode=5,
        expected_destination_subpath="TV Shows/Chernobyl/Season 01/Chernobyl - S01E05.mkv",
        edge_case_type="sxxexx_with_episode_title",
    ),
    BenchmarkCase(
        id="TV-11",
        domain="Standard TV",
        filename="Friends.S06E15-E16.The.One.That.Could.Have.Been.mkv",
        expected_category="tv",
        expected_title="Friends",
        expected_season=6,
        expected_episode=15,
        expected_multi_episodes=[15, 16],
        expected_destination_subpath="TV Shows/Friends/Season 06/Friends - S06E15-E16.mkv",
        edge_case_type="multi_episode_double_digit",
    ),

    # =========================================================================
    # Domain 2: Anime
    # =========================================================================
    BenchmarkCase(
        id="ANIME-01",
        domain="Anime",
        filename="[SubsPlease] Frieren - Beyond Journey's End - 01 (1080p) [ABCD1234].mkv",
        expected_category="anime",
        expected_title="Frieren - Beyond Journey's End",
        expected_episode=1,
        expected_group="SubsPlease",
        expected_destination_subpath="Anime/Frieren - Beyond Journey's End/Frieren - Beyond Journey's End - 01 [SubsPlease].mkv",
        edge_case_type="fansub_brackets_crc",
    ),
    BenchmarkCase(
        id="ANIME-02",
        domain="Anime",
        filename="[SubsPlease] 葬送のフリーレン - 12 (1080p) [98E7B1A2].mkv",
        expected_category="anime",
        expected_title="葬送のフリーレン",
        expected_episode=12,
        expected_group="SubsPlease",
        expected_destination_subpath="Anime/葬送のフリーレン/葬送のフリーレン - 12 [SubsPlease].mkv",
        edge_case_type="unicode_kanji_title",
    ),
    BenchmarkCase(
        id="ANIME-03",
        domain="Anime",
        filename="[HorribleSubs] Fairy Tail (2014) - 176 [720p].mkv",
        expected_category="anime",
        expected_title="Fairy Tail (2014)",
        expected_episode=176,
        expected_group="HorribleSubs",
        expected_destination_subpath="Anime/Fairy Tail (2014)/Fairy Tail (2014) - 176 [HorribleSubs].mkv",
        edge_case_type="parenthesized_title_year",
    ),
    BenchmarkCase(
        id="ANIME-04",
        domain="Anime",
        filename="[Erai-raws] One Piece - 1088 [1080p].mkv",
        expected_category="anime",
        expected_title="One Piece",
        expected_episode=1088,
        expected_group="Erai-raws",
        expected_destination_subpath="Anime/One Piece/One Piece - 1088 [Erai-raws].mkv",
        edge_case_type="four_digit_absolute_numbering",
    ),
    BenchmarkCase(
        id="ANIME-05",
        domain="Anime",
        filename="[SubsPlease] Dungeon Meshi - 01-02 (1080p).mkv",
        expected_category="anime",
        expected_title="Dungeon Meshi",
        expected_episode=1,
        expected_multi_episodes=[1, 2],
        expected_group="SubsPlease",
        expected_destination_subpath="Anime/Dungeon Meshi/Dungeon Meshi - 01-02 [SubsPlease].mkv",
        edge_case_type="multi_episode_anime",
    ),
    BenchmarkCase(
        id="ANIME-06",
        domain="Anime",
        filename="[TaigaSubs] Attack on Titan OVA - 01 [720p].mkv",
        expected_category="anime",
        expected_title="Attack on Titan OVA",
        expected_episode=1,
        expected_group="TaigaSubs",
        expected_destination_subpath="Anime/Attack on Titan OVA/Attack on Titan OVA - 01 [TaigaSubs].mkv",
        edge_case_type="anime_ova",
    ),
    BenchmarkCase(
        id="ANIME-07",
        domain="Anime",
        filename="Naruto Episode 207 The Supposed Sealed Ability.mkv",
        expected_category="anime",
        expected_title="Naruto",
        expected_episode=207,
        expected_destination_subpath="Anime/Naruto/Naruto - 207.mkv",
        edge_case_type="standalone_episode_keyword",
    ),
    BenchmarkCase(
        id="ANIME-08",
        domain="Anime",
        filename="[Judas] Fate Stay Night - Heaven's Feel - I. Presage Flower [BD 1080p].mkv",
        expected_category="anime",
        expected_title="Fate Stay Night - Heaven's Feel - I. Presage Flower",
        expected_group="Judas",
        expected_destination_subpath="Anime/Fate Stay Night - Heaven's Feel - I. Presage Flower/Fate Stay Night - Heaven's Feel - I. Presage Flower [Judas].mkv",
        edge_case_type="anime_movie_roman_numeral",
    ),
    BenchmarkCase(
        id="ANIME-09",
        domain="Anime",
        filename="BLEACH - Sennen Kessen-hen - 27 [E89717B7].mkv",
        expected_category="anime",
        expected_title="BLEACH - Sennen Kessen-hen",
        expected_episode=27,
        expected_destination_subpath="Anime/BLEACH - Sennen Kessen-hen/BLEACH - Sennen Kessen-hen - 27.mkv",
        edge_case_type="no_group_fansub_crc",
    ),
    BenchmarkCase(
        id="ANIME-10",
        domain="Anime",
        filename="[Erai-raws] Jujutsu Kaisen 2nd Season - 14 [1080p][Multiple Subtitle].mkv",
        expected_category="anime",
        expected_title="Jujutsu Kaisen 2nd Season",
        expected_episode=14,
        expected_group="Erai-raws",
        expected_destination_subpath="Anime/Jujutsu Kaisen 2nd Season/Jujutsu Kaisen 2nd Season - 14 [Erai-raws].mkv",
        edge_case_type="cour_season_title_tags",
    ),
    BenchmarkCase(
        id="ANIME-11",
        domain="Anime",
        filename="[SubsPlease] Mushoku Tensei S2 - 18 (1080p) [F28B1452].mkv",
        expected_category="anime",
        expected_title="Mushoku Tensei S2",
        expected_episode=18,
        expected_group="SubsPlease",
        expected_destination_subpath="Anime/Mushoku Tensei S2/Mushoku Tensei S2 - 18 [SubsPlease].mkv",
        edge_case_type="short_season_notation",
    ),

    # =========================================================================
    # Domain 3: Movies
    # =========================================================================
    BenchmarkCase(
        id="MOVIE-01",
        domain="Movies",
        filename="Inception.2010.1080p.BluRay.x264-FraMeSToR.mkv",
        expected_category="movie",
        expected_title="Inception",
        expected_year=2010,
        expected_group="FraMeSToR",
        expected_destination_subpath="Movies/Inception (2010)/Inception (2010).mkv",
        edge_case_type="standard_movie_year",
    ),
    BenchmarkCase(
        id="MOVIE-02",
        domain="Movies",
        filename="1917.2019.1080p.BluRay.x264.mkv",
        expected_category="movie",
        expected_title="1917",
        expected_year=2019,
        expected_destination_subpath="Movies/1917 (2019)/1917 (2019).mkv",
        edge_case_type="numerical_title_with_year",
    ),
    BenchmarkCase(
        id="MOVIE-03",
        domain="Movies",
        filename="2001.A.Space.Odyssey.1968.REMASTERED.1080p.mkv",
        expected_category="movie",
        expected_title="2001 A Space Odyssey",
        expected_year=1968,
        expected_edition="Remastered",
        expected_destination_subpath="Movies/2001 A Space Odyssey (1968)/2001 A Space Odyssey (1968) [Remastered].mkv",
        edge_case_type="numerical_title_year_and_edition",
    ),
    BenchmarkCase(
        id="MOVIE-04",
        domain="Movies",
        filename="Blade.Runner.2049.2017.2160p.UHD.BluRay.x265.mkv",
        expected_category="movie",
        expected_title="Blade Runner 2049",
        expected_year=2017,
        expected_destination_subpath="Movies/Blade Runner 2049 (2017)/Blade Runner 2049 (2017).mkv",
        edge_case_type="future_year_in_title",
    ),
    BenchmarkCase(
        id="MOVIE-05",
        domain="Movies",
        filename="Wonder.Woman.1984.2020.1080p.WEB-DL.mkv",
        expected_category="movie",
        expected_title="Wonder Woman 1984",
        expected_year=2020,
        expected_destination_subpath="Movies/Wonder Woman 1984 (2020)/Wonder Woman 1984 (2020).mkv",
        edge_case_type="year_in_title",
    ),
    BenchmarkCase(
        id="MOVIE-06",
        domain="Movies",
        filename="Class.of.1999.1990.720p.mkv",
        expected_category="movie",
        expected_title="Class of 1999",
        expected_year=1990,
        expected_destination_subpath="Movies/Class of 1999 (1990)/Class of 1999 (1990).mkv",
        edge_case_type="past_year_in_title",
    ),
    BenchmarkCase(
        id="MOVIE-07",
        domain="Movies",
        filename="Titanic.1997.DVD.CD1.avi",
        expected_category="movie",
        expected_title="Titanic",
        expected_year=1997,
        expected_part=1,
        expected_destination_subpath="Movies/Titanic (1997)/Titanic (1997) [Pt.1].avi",
        edge_case_type="multi_part_cd1",
    ),
    BenchmarkCase(
        id="MOVIE-08",
        domain="Movies",
        filename="Titanic.1997.DVD.CD2.avi",
        expected_category="movie",
        expected_title="Titanic",
        expected_year=1997,
        expected_part=2,
        expected_destination_subpath="Movies/Titanic (1997)/Titanic (1997) [Pt.2].avi",
        edge_case_type="multi_part_cd2",
    ),
    BenchmarkCase(
        id="MOVIE-09",
        domain="Movies",
        filename="Kill.Bill.Vol.1.2003.1080p.BluRay.mkv",
        expected_category="movie",
        expected_title="Kill Bill Vol 1",
        expected_year=2003,
        expected_destination_subpath="Movies/Kill Bill Vol 1 (2003)/Kill Bill Vol 1 (2003).mkv",
        edge_case_type="volume_in_movie_title",
    ),
    BenchmarkCase(
        id="MOVIE-10",
        domain="Movies",
        filename="The.Lord.of.the.Rings.The.Fellowship.of.the.Ring.2001.Extended.1080p.mkv",
        expected_category="movie",
        expected_title="The Lord of the Rings The Fellowship of the Ring",
        expected_year=2001,
        expected_edition="Extended",
        expected_destination_subpath="Movies/The Lord of the Rings The Fellowship of the Ring (2001)/The Lord of the Rings The Fellowship of the Ring (2001) [Extended].mkv",
        edge_case_type="edition_extended",
    ),
    BenchmarkCase(
        id="MOVIE-11",
        domain="Movies",
        filename="Aliens.1986.Directors.Cut.1080p.BluRay.mkv",
        expected_category="movie",
        expected_title="Aliens",
        expected_year=1986,
        expected_edition="Director's Cut",
        expected_destination_subpath="Movies/Aliens (1986)/Aliens (1986) [Director's Cut].mkv",
        edge_case_type="edition_directors_cut",
    ),
    BenchmarkCase(
        id="MOVIE-12",
        domain="Movies",
        filename="Gladiator.2000.Remastered.1080p.BluRay.mkv",
        expected_category="movie",
        expected_title="Gladiator",
        expected_year=2000,
        expected_edition="Remastered",
        expected_destination_subpath="Movies/Gladiator (2000)/Gladiator (2000) [Remastered].mkv",
        edge_case_type="edition_remastered",
    ),
    BenchmarkCase(
        id="MOVIE-13",
        domain="Movies",
        filename="Seven.Samurai.1954.Criterion.Collection.1080p.BluRay.mkv",
        expected_category="movie",
        expected_title="Seven Samurai",
        expected_year=1954,
        expected_edition="Criterion",
        expected_destination_subpath="Movies/Seven Samurai (1954)/Seven Samurai (1954) [Criterion].mkv",
        edge_case_type="edition_criterion",
    ),
    BenchmarkCase(
        id="MOVIE-14",
        domain="Movies",
        filename="Blade.Runner.1982.Final.Cut.2160p.UHD.mkv",
        expected_category="movie",
        expected_title="Blade Runner",
        expected_year=1982,
        expected_edition="Final Cut",
        expected_destination_subpath="Movies/Blade Runner (1982)/Blade Runner (1982) [Final Cut].mkv",
        edge_case_type="edition_final_cut",
    ),

    # =========================================================================
    # Domain 4: Specials & Extras
    # =========================================================================
    BenchmarkCase(
        id="SPECIAL-01",
        domain="Specials & Extras",
        filename="The.Office.S00E01.The.Outtakes.mkv",
        expected_category="tv",
        expected_title="The Office",
        expected_season=0,
        expected_episode=1,
        expected_destination_subpath="TV Shows/The Office/Season 00/The Office - S00E01.mkv",
        edge_case_type="season_00_special",
    ),
    BenchmarkCase(
        id="SPECIAL-02",
        domain="Specials & Extras",
        filename="Doctor.Who.S00E25.The.Day.of.the.Doctor.1080p.mkv",
        expected_category="tv",
        expected_title="Doctor Who",
        expected_season=0,
        expected_episode=25,
        expected_destination_subpath="TV Shows/Doctor Who/Season 00/Doctor Who - S00E25.mkv",
        edge_case_type="season_00_high_episode",
    ),
    BenchmarkCase(
        id="SPECIAL-03",
        domain="Specials & Extras",
        filename="Breaking.Bad.S05E00.Special.mkv",
        expected_category="tv",
        expected_title="Breaking Bad",
        expected_season=5,
        expected_episode=0,
        expected_destination_subpath="TV Shows/Breaking Bad/Season 05/Breaking Bad - S05E00.mkv",
        edge_case_type="mid_season_special_e00",
    ),
    BenchmarkCase(
        id="SPECIAL-04",
        domain="Specials & Extras",
        filename="Inception.2010-behindthescenes.mkv",
        expected_category="movie",
        expected_title="Inception",
        expected_year=2010,
        expected_destination_subpath="Movies/Inception (2010)/Inception (2010)-behindthescenes.mkv",
        edge_case_type="movie_extra_behind_the_scenes",
    ),
    BenchmarkCase(
        id="SPECIAL-05",
        domain="Specials & Extras",
        filename="The.Matrix.1999-featurette.mkv",
        expected_category="movie",
        expected_title="The Matrix",
        expected_year=1999,
        expected_destination_subpath="Movies/The Matrix (1999)/The Matrix (1999)-featurette.mkv",
        edge_case_type="movie_extra_featurette",
    ),
    BenchmarkCase(
        id="SPECIAL-06",
        domain="Specials & Extras",
        filename="Interstellar.2014-deleted.mkv",
        expected_category="movie",
        expected_title="Interstellar",
        expected_year=2014,
        expected_destination_subpath="Movies/Interstellar (2014)/Interstellar (2014)-deleted.mkv",
        edge_case_type="movie_extra_deleted_scenes",
    ),
    BenchmarkCase(
        id="SPECIAL-07",
        domain="Specials & Extras",
        filename="Interstellar.2014-trailer.mp4",
        expected_category="movie",
        expected_title="Interstellar",
        expected_year=2014,
        expected_destination_subpath="Movies/Interstellar (2014)/Interstellar (2014)-trailer.mp4",
        edge_case_type="movie_extra_trailer",
    ),
    BenchmarkCase(
        id="SPECIAL-08",
        domain="Specials & Extras",
        filename="Game.of.Thrones.S00E02.A.Day.in.the.Life.mkv",
        expected_category="tv",
        expected_title="Game of Thrones",
        expected_season=0,
        expected_episode=2,
        expected_destination_subpath="TV Shows/Game of Thrones/Season 00/Game of Thrones - S00E02.mkv",
        edge_case_type="tv_special_episode_title",
    ),
    BenchmarkCase(
        id="SPECIAL-09",
        domain="Specials & Extras",
        filename="Sherlock.S00E01.Many.Happy.Returns.mkv",
        expected_category="tv",
        expected_title="Sherlock",
        expected_season=0,
        expected_episode=1,
        expected_destination_subpath="TV Shows/Sherlock/Season 00/Sherlock - S00E01.mkv",
        edge_case_type="tv_special_prequel",
    ),

    # =========================================================================
    # Domain 5: Daily / Dated Shows
    # =========================================================================
    BenchmarkCase(
        id="DAILY-01",
        domain="Daily / Dated Shows",
        filename="The.Daily.Show.2024-01-15.1080p.HDTV.mkv",
        expected_category="tv",
        expected_title="The Daily Show",
        expected_year=2024,
        expected_date="2024-01-15",
        expected_destination_subpath="TV Shows/The Daily Show/Season 2024/The Daily Show - 2024-01-15.mkv",
        edge_case_type="iso_dated_tv",
    ),
    BenchmarkCase(
        id="DAILY-02",
        domain="Daily / Dated Shows",
        filename="The.Tonight.Show.Starring.Jimmy.Fallon.2024.03.12.720p.mkv",
        expected_category="tv",
        expected_title="The Tonight Show Starring Jimmy Fallon",
        expected_year=2024,
        expected_date="2024-03-12",
        expected_destination_subpath="TV Shows/The Tonight Show Starring Jimmy Fallon/Season 2024/The Tonight Show Starring Jimmy Fallon - 2024-03-12.mkv",
        edge_case_type="dot_dated_tv",
    ),
    BenchmarkCase(
        id="DAILY-03",
        domain="Daily / Dated Shows",
        filename="Last.Week.Tonight.with.John.Oliver.2023-11-05.1080p.mkv",
        expected_category="tv",
        expected_title="Last Week Tonight with John Oliver",
        expected_year=2023,
        expected_date="2023-11-05",
        expected_destination_subpath="TV Shows/Last Week Tonight with John Oliver/Season 2023/Last Week Tonight with John Oliver - 2023-11-05.mkv",
        edge_case_type="weekly_dated_show",
    ),
    BenchmarkCase(
        id="DAILY-04",
        domain="Daily / Dated Shows",
        filename="Late.Night.with.Seth.Meyers.2024_02_20.720p.mkv",
        expected_category="tv",
        expected_title="Late Night with Seth Meyers",
        expected_year=2024,
        expected_date="2024-02-20",
        expected_destination_subpath="TV Shows/Late Night with Seth Meyers/Season 2024/Late Night with Seth Meyers - 2024-02-20.mkv",
        edge_case_type="underscore_dated_tv",
    ),
    BenchmarkCase(
        id="DAILY-05",
        domain="Daily / Dated Shows",
        filename="The Daily - 2026-03-12 - The Sunday Read.mp3",
        expected_category="podcast",
        expected_title="The Sunday Read",
        expected_year=2026,
        expected_date="2026-03-12",
        expected_destination_subpath="Podcasts/The Daily/2026/The Daily - 2026-03-12 - The Sunday Read.mp3",
        edge_case_type="dated_podcast",
    ),
    BenchmarkCase(
        id="DAILY-06",
        domain="Daily / Dated Shows",
        filename="Jimmy.Kimmel.Live.2024-04-18.720p.HDTV.mkv",
        expected_category="tv",
        expected_title="Jimmy Kimmel Live",
        expected_year=2024,
        expected_date="2024-04-18",
        expected_destination_subpath="TV Shows/Jimmy Kimmel Live/Season 2024/Jimmy Kimmel Live - 2024-04-18.mkv",
        edge_case_type="daily_show_iso",
    ),
    BenchmarkCase(
        id="DAILY-07",
        domain="Daily / Dated Shows",
        filename="PBS.NewsHour.2024.05.01.720p.mkv",
        expected_category="tv",
        expected_title="PBS NewsHour",
        expected_year=2024,
        expected_date="2024-05-01",
        expected_destination_subpath="TV Shows/PBS NewsHour/Season 2024/PBS NewsHour - 2024-05-01.mkv",
        edge_case_type="news_broadcast_dot_date",
    ),
    BenchmarkCase(
        id="DAILY-08",
        domain="Daily / Dated Shows",
        filename="The.Late.Show.with.Stephen.Colbert.2024-02-14.1080p.mkv",
        expected_category="tv",
        expected_title="The Late Show with Stephen Colbert",
        expected_year=2024,
        expected_date="2024-02-14",
        expected_destination_subpath="TV Shows/The Late Show with Stephen Colbert/Season 2024/The Late Show with Stephen Colbert - 2024-02-14.mkv",
        edge_case_type="late_night_show_iso",
    ),
    BenchmarkCase(
        id="DAILY-09",
        domain="Daily / Dated Shows",
        filename="NPR.News.Now.2024-06-10.mp3",
        expected_category="podcast",
        expected_title="NPR News Now",
        expected_year=2024,
        expected_date="2024-06-10",
        expected_destination_subpath="Podcasts/NPR News Now/2024/NPR News Now - 2024-06-10.mp3",
        edge_case_type="podcast_daily_news",
    ),

    # =========================================================================
    # Domain 6: Messy & Complex
    # =========================================================================
    BenchmarkCase(
        id="MESSY-01",
        domain="Messy & Complex",
        filename="Amélie.2001.PROPER.REMASTERED.1080p.BluRay.x264-CiNEFiLE.mkv",
        expected_category="movie",
        expected_title="Amélie",
        expected_year=2001,
        expected_edition="Remastered",
        expected_group="CiNEFiLE",
        expected_destination_subpath="Movies/Amélie (2001)/Amélie (2001) [Remastered].mkv",
        edge_case_type="unicode_accented_characters",
    ),
    BenchmarkCase(
        id="MESSY-02",
        domain="Messy & Complex",
        filename="Wolfs.2024.1080p.Apple.TV.WEB-DL.DDP5.1.Atmos.H.264.mkv",
        expected_category="movie",
        expected_title="Wolfs",
        expected_year=2024,
        expected_destination_subpath="Movies/Wolfs (2024)/Wolfs (2024).mkv",
        edge_case_type="apple_tv_scene_tag",
    ),
    BenchmarkCase(
        id="MESSY-03",
        domain="Messy & Complex",
        filename="Gladiator.II.2024.1080p.HDTV.x264-[rartv].mkv",
        expected_category="movie",
        expected_title="Gladiator II",
        expected_year=2024,
        expected_group="rartv",
        expected_destination_subpath="Movies/Gladiator II (2024)/Gladiator II (2024).mkv",
        edge_case_type="roman_numeral_title_bracket_group",
    ),
    BenchmarkCase(
        id="MESSY-04",
        domain="Messy & Complex",
        filename="Interstellar.1920x1080.mkv",
        expected_category="movie",
        expected_title="Interstellar",
        expected_destination_subpath="Movies/Interstellar/Interstellar.mkv",
        edge_case_type="resolution_dimensions",
    ),
    BenchmarkCase(
        id="MESSY-05",
        domain="Messy & Complex",
        filename="[YTS.MX] Movie Title - 2024 [1080p].mkv",
        expected_category="movie",
        expected_title="Movie Title",
        expected_year=2024,
        expected_group="YTS.MX",
        expected_destination_subpath="Movies/Movie Title (2024)/Movie Title (2024).mkv",
        edge_case_type="bracket_group_movie_not_anime",
    ),
    BenchmarkCase(
        id="MESSY-06",
        domain="Messy & Complex",
        filename="The.Dark.Knight.2008.1080p.forced.srt",
        expected_category="subtitle",
        expected_title="The Dark Knight",
        expected_year=2008,
        expected_destination_subpath="Movies/The Dark Knight (2008)/The Dark Knight (2008).forced.srt",
        edge_case_type="subtitle_forced_tag",
    ),
    BenchmarkCase(
        id="MESSY-07",
        domain="Messy & Complex",
        filename='Show: "Special" <Episode> | 1?.mkv',
        expected_category="tv",
        expected_title="Show Special Episode 1",
        expected_episode=1,
        expected_destination_subpath="TV Shows/Show Special Episode 1/Season 01/Show Special Episode 1 - S01E01.mkv",
        edge_case_type="illegal_characters",
    ),
    BenchmarkCase(
        id="MESSY-08",
        domain="Messy & Complex",
        filename="CON.mp4",
        expected_category="home_video",
        expected_title="CON",
        expected_destination_subpath="Home Videos/2026/2026-01 - Event/_CON.mp4",
        edge_case_type="windows_reserved_device_name",
    ),
    BenchmarkCase(
        id="MESSY-09",
        domain="Messy & Complex",
        filename="  Messy  Show . S01E01 .  1080p .mkv",
        expected_category="tv",
        expected_title="Messy Show",
        expected_season=1,
        expected_episode=1,
        expected_destination_subpath="TV Shows/Messy Show/Season 01/Messy Show - S01E01.mkv",
        edge_case_type="irregular_whitespace_and_dots",
    ),
    BenchmarkCase(
        id="MESSY-10",
        domain="Messy & Complex",
        filename="Show_Name__2022__S02E03__HDTV.mkv",
        expected_category="tv",
        expected_title="Show Name",
        expected_year=2022,
        expected_season=2,
        expected_episode=3,
        expected_destination_subpath="TV Shows/Show Name/Season 02/Show Name - S02E03.mkv",
        edge_case_type="consecutive_underscores",
    ),
]

CASES_BY_ID: Dict[str, BenchmarkCase] = {c.id: c for c in BENCHMARK_CASES}

CASES_BY_DOMAIN: Dict[str, List[BenchmarkCase]] = {}
for c in BENCHMARK_CASES:
    CASES_BY_DOMAIN.setdefault(c.domain, []).append(c)


def create_benchmark_inputs(case: BenchmarkCase) -> Tuple[ScannedFile, MediaMetadata, Settings, Optional[Path]]:
    """Build pure in-memory, zero-disk, zero-network inputs for a benchmark case.

    Returns:
        Tuple of (ScannedFile, MediaMetadata, Settings, optional primary_dst_path)
    """
    file_path = Path(case.filename)
    ext = file_path.suffix.lower()

    is_sidecar = case.expected_category == "subtitle" or ext in {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".nfo"}
    sidecar_type = "subtitle" if (case.expected_category == "subtitle" or ext in {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"}) else None

    # Primary media path for paired sidecars (e.g. subtitles)
    primary_dst_path: Optional[Path] = None
    primary_media_path: Optional[Path] = None
    if is_sidecar and case.expected_category == "subtitle":
        # Simulate paired primary movie file
        primary_media_path = file_path.with_name(f"{case.expected_title}.{case.expected_year or 2008}.1080p.mkv")
        primary_dst_path = Path(f"/test_dest/Movies/{case.expected_title} ({case.expected_year or 2008})/{case.expected_title} ({case.expected_year or 2008}).mkv")

    scanned = ScannedFile(
        path=file_path,
        size=1024 * 1024 * 350,  # 350 MB simulated file size
        mtime=1700000000.0,
        is_sidecar=is_sidecar,
        sidecar_type=sidecar_type,
        primary_media_path=primary_media_path,
    )

    if ext in {".mp3", ".flac", ".ogg", ".m4a", ".aac"}:
        metadata = MediaMetadata(
            path=file_path,
            mime_type="audio/mpeg" if ext == ".mp3" else "audio/flac",
            container=ext.lstrip("."),
            duration_seconds=1800.0,
            has_audio=True,
            has_video=False,
        )
    elif is_sidecar:
        metadata = MediaMetadata(
            path=file_path,
            mime_type="text/plain",
            container=ext.lstrip("."),
            duration_seconds=0.0,
            has_subtitles=True,
        )
    else:
        # Realistic durations per domain
        durations = {
            "Standard TV": 2700.0,
            "Anime": 1440.0,
            "Movies": 7200.0,
            "Specials & Extras": 1800.0,
            "Daily / Dated Shows": 2400.0,
            "Messy & Complex": 5400.0,
        }
        dur = durations.get(case.domain, 3600.0)
        metadata = MediaMetadata(
            path=file_path,
            mime_type="video/x-matroska" if ext == ".mkv" else ("video/mp4" if ext == ".mp4" else "video/x-msvideo"),
            container=ext.lstrip(".") or "mkv",
            duration_seconds=dur,
            has_video=True,
            has_audio=True,
        )

    # Isolated settings: isolated paths preventing any interaction with real folders
    settings = Settings(
        general=dict(dry_run=True, rename_files=True),
        storage=dict(
            source_dirs=["/test_source"],
            destination_base="/test_dest",
        ),
    )

    return scanned, metadata, settings, primary_dst_path


@dataclass
class CaseResult:
    case_id: str
    domain: str
    filename: str
    edge_case_type: str
    passed: bool
    duration_ms: float
    diffs: Dict[str, Dict[str, Any]]
    actual_category: str
    actual_title: Optional[str]
    actual_destination_subpath: Optional[str]
    exception: Optional[str] = None


def evaluate_benchmark_case(case: BenchmarkCase) -> CaseResult:
    """Evaluate a benchmark case against tokenizer, classifier, and namer in pure memory.

    Measures execution duration and computes field-level diffs against expectations.
    Catches any unexpected errors to prevent runner crashes.
    """
    import time
    from media_sorter.classifier import MediaClassifier
    from media_sorter.namer import MediaNamer
    from media_sorter.tokenizer import FilenameTokenizer

    start_time = time.perf_counter()
    diffs: Dict[str, Dict[str, Any]] = {}
    actual_category = "unknown"
    actual_title: Optional[str] = None
    actual_subpath: Optional[str] = None
    exc_str: Optional[str] = None

    try:
        file_path = Path(case.filename)
        scanned, metadata, settings, primary_dst = create_benchmark_inputs(case)

        # 1. Tokenize
        tokenizer = FilenameTokenizer()
        tokens = tokenizer.tokenize(file_path)
        actual_title = tokens.title

        # 2. Classify
        classifier = MediaClassifier(confidence_threshold=0.75, provider=None)
        cls_result = classifier.classify(scanned, tokens, metadata)
        actual_category = cls_result.category

        # 3. Destination resolution
        namer = MediaNamer(settings)
        dest_path = namer.generate_destination_path(cls_result, primary_dst_path=primary_dst)
        base_dir = settings.get_destination_base_path()
        try:
            actual_subpath = dest_path.relative_to(base_dir).as_posix()
        except ValueError:
            actual_subpath = dest_path.as_posix()

        # Category comparison
        if cls_result.category != case.expected_category:
            diffs["category"] = {
                "expected": case.expected_category,
                "actual": cls_result.category,
            }

        # Title comparison
        if tokens.title != case.expected_title:
            diffs["title"] = {
                "expected": case.expected_title,
                "actual": tokens.title,
            }

        # Year comparison
        if case.expected_year is not None:
            if tokens.year != case.expected_year:
                diffs["year"] = {
                    "expected": case.expected_year,
                    "actual": tokens.year,
                }

        # Season comparison
        if case.expected_season is not None:
            if tokens.season != case.expected_season:
                diffs["season"] = {
                    "expected": case.expected_season,
                    "actual": tokens.season,
                }

        # Episode comparison
        if case.expected_episode is not None:
            if tokens.episode != case.expected_episode:
                diffs["episode"] = {
                    "expected": case.expected_episode,
                    "actual": tokens.episode,
                }

        # Multi-episodes comparison
        if case.expected_multi_episodes is not None:
            actual_multi = getattr(tokens, "multi_episodes", [])
            if actual_multi != case.expected_multi_episodes:
                diffs["multi_episodes"] = {
                    "expected": case.expected_multi_episodes,
                    "actual": actual_multi,
                }

        # Date comparison
        if case.expected_date is not None:
            actual_date = getattr(tokens, "air_date", None) or getattr(tokens, "date_stamp", None)
            if actual_date != case.expected_date:
                diffs["date"] = {
                    "expected": case.expected_date,
                    "actual": actual_date,
                }

        # Edition comparison
        if case.expected_edition is not None:
            actual_edition = getattr(tokens, "edition", None)
            if actual_edition != case.expected_edition:
                diffs["edition"] = {
                    "expected": case.expected_edition,
                    "actual": actual_edition,
                }

        # Part comparison
        if case.expected_part is not None:
            actual_part = getattr(tokens, "part", None)
            if actual_part != case.expected_part:
                diffs["part"] = {
                    "expected": case.expected_part,
                    "actual": actual_part,
                }

        # Group comparison
        if case.expected_group is not None:
            actual_group = getattr(tokens, "group", None)
            if actual_group != case.expected_group:
                diffs["group"] = {
                    "expected": case.expected_group,
                    "actual": actual_group,
                }

        # Destination subpath comparison
        if case.expected_destination_subpath is not None:
            if actual_subpath != case.expected_destination_subpath:
                diffs["destination_subpath"] = {
                    "expected": case.expected_destination_subpath,
                    "actual": actual_subpath,
                }

    except Exception as exc:
        exc_str = f"{type(exc).__name__}: {exc}"
        diffs["unhandled_exception"] = {
            "expected": "clean execution",
            "actual": exc_str,
        }

    duration_ms = (time.perf_counter() - start_time) * 1000.0

    return CaseResult(
        case_id=case.id,
        domain=case.domain,
        filename=case.filename,
        edge_case_type=case.edge_case_type,
        passed=len(diffs) == 0,
        duration_ms=round(duration_ms, 3),
        diffs=diffs,
        actual_category=actual_category,
        actual_title=actual_title,
        actual_destination_subpath=actual_subpath,
        exception=exc_str,
    )

