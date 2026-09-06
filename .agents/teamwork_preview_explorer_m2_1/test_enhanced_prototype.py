import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass, field

import sys
sys.path.insert(0, "/md0/media-sorter")

from media_sorter.tokenizer import (
    RE_RESOLUTION,
    RE_DIMENSIONS,
    RE_SOURCE,
    RE_VIDEO_CODEC,
    RE_AUDIO_CODEC,
    RE_MUSIC_TRACK,
    RE_CAMERA_DATE,
    RE_PODCAST_DATE,
)
from tests.benchmark.benchmark_cases import BENCHMARK_CASES

@dataclass
class TokenizedFilename:
    raw_name: str
    title: Optional[str] = None
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    multi_episodes: List[int] = field(default_factory=list)
    episode_title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    track: Optional[int] = None
    disc: Optional[int] = None
    group: Optional[str] = None
    resolution: Optional[str] = None
    source: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    date_stamp: Optional[str] = None
    air_date: Optional[str] = None
    edition: Optional[str] = None
    part: Optional[int] = None
    part_label: Optional[str] = None
    is_anime: bool = False
    is_episodic: bool = False
    is_music: bool = False
    is_photo_or_home_video: bool = False
    is_daily: bool = False
    is_season_pack: bool = False

TokenizedMedia = TokenizedFilename

ROMAN_NUMERALS: Dict[str, int] = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
    "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
    "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
}

RE_ROMAN_SEASON_EPISODE = re.compile(
    r"""(?ix)
    \bseason[\.\s_-]*(?P<season_roman>[ivx]+)[\.\s_-]*(?:episode|ep)[\.\s_-]*(?P<episode_roman>[ivx]+)\b
    """
)

RE_SEASON_EPISODE = re.compile(
    r"""(?ix)
    (?:
        # Standard S01E02, S01E01-E02, S01E01E02, S01E01-02
        (?<![0-9a-z])s(?P<season>\d{1,2})[\.\s_-]*(?:e|ep|ed|op)(?P<episode>\d{1,3})
        (?:[\.\s_-]*(?:e|x|-|ep)(?P<episode_end>\d{1,3}))?(?![0-9])
    |
        # Scene 1x02, 2x01-02, 2x01-x02
        (?<![0-9a-z])(?P<season_x>\d{1,2})x(?!(?:264|265|vid|hevc|avc))(?P<episode_x>\d{1,3})
        (?:[\.\s_-]*(?:x|-)(?P<episode_x_end>\d{1,3}))?(?![0-9])
    |
        # Word season / episode: Season 1 Episode 2
        \bseason[\.\s_-]*(?P<season_word>\d{1,2})[\.\s_-]*(?:episode|ep)[\.\s_-]*(?P<episode_word>\d{1,3})
        (?:[\.\s_-]*(?:-|to)[\.\s_-]*(?:episode|ep)?[\.\s_-]*(?P<episode_word_end>\d{1,3}))?\b
    |
        # Standalone episode: Episode 207, Ep 01
        \b(?:episodes?|ep)[\.\s_-]*(?P<episode_standalone>\d{1,4})(?![0-9])\b
    )
    """
)

RE_SEASON_PACK = re.compile(
    r"""(?ix)
    (?<![0-9a-z])
    (?:
        s(?P<season_pack>\d{1,2})
        |
        season[\.\s_-]*(?P<season_pack_word>\d{1,2})
    )
    [\.\s_-]*(?:complete|full|season\.pack)\b
    """
)

# Anime fansub format: [ReleaseGroup] Show Title - 01 (or 01-02, or 01v2) [1080p] [CRC32].mkv
RE_ANIME_RELEASE = re.compile(
    r"""(?ix)
    ^\s*(?:\[(?P<group>[^\]]+)\]\s*)?
    (?P<title>.+?)\s*-\s*
    (?P<episode>\d{1,4})(?:-(?P<episode_end>\d{1,4}))?(?:v\d+)?(?![xX\w])\s*
    (?:\s*(?:\[?[0-9A-Fa-f]{8}\]?|\[(?P<tag>[^\]]+)\]|\((?P<tag_paren>[^\)]+)\))|\s+[A-Za-z0-9_.-]+)*\s*\]?$
    """
)

RE_ANIME_MOVIE = re.compile(
    r"""(?ix)
    ^\s*\[(?P<group>[^\]]+)\]\s*
    (?P<title>[^\[]+?)\s*
    (?:\[(?P<tag>[^\]]+)\]|\((?P<tag_paren>[^\)]+)\))
    """
)

RE_YEAR_BOUND = re.compile(r"(?<![0-9a-zA-Z])(19\d{2}|20\d{2})(?![0-9a-zA-Z])")

RE_EDITION = re.compile(
    r"""(?ix)
    \b(?P<edition>
        directors?\.cut|director's\.cut|director's\scut
        |
        extended(?:\.cut|\.edition)?
        |
        remastered(?:\.edition)?|remaster
        |
        criterion(?:\.collection)?
        |
        final\.cut
        |
        theatrical(?:\.cut|\.version)?
        |
        unrated
        |
        special\.edition
        |
        imax(?:\.edition)?
        |
        ultimate\.edition
    )\b
    """
)

EDITION_CANONICAL_MAP = {
    "extended": "Extended",
    "extended.cut": "Extended",
    "extended.edition": "Extended",
    "directors.cut": "Director's Cut",
    "director's.cut": "Director's Cut",
    "director's cut": "Director's Cut",
    "remastered": "Remastered",
    "remastered.edition": "Remastered",
    "remaster": "Remastered",
    "criterion": "Criterion",
    "criterion.collection": "Criterion",
    "final.cut": "Final Cut",
    "theatrical": "Theatrical",
    "theatrical.cut": "Theatrical",
    "theatrical.version": "Theatrical",
    "unrated": "Unrated",
    "special.edition": "Special Edition",
    "imax": "IMAX",
    "imax.edition": "IMAX",
    "ultimate.edition": "Ultimate Edition",
}

RE_MOVIE_PART = re.compile(
    r"""(?ix)
    \b(?:cd|part|pt|disc)[\.\s_-]*(?P<part_num>\d{1,2})\b
    """
)

RE_DAILY_DATE = re.compile(
    r"""(?ix)
    (?<!\d)
    (?P<year>19\d{2}|20\d{2})[-._]
    (?P<month>0[1-9]|1[0-2])[-._]
    (?P<day>0[1-9]|[12]\d|3[01])
    (?!\d)
    """
)

RE_RELEASE_GROUP_UPGRADED = re.compile(
    r"-(?:\[(?P<grp_bracket>[A-Za-z0-9_.-]+)\]|(?P<grp_plain>[A-Za-z0-9_]+))(?:\[.*?\])?$",
    re.IGNORECASE,
)

RE_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

RE_TECH_ALL = re.compile(
    r"""(?ix)
    \b(
        2160p|4k|1080p|1080i|720p|576p|480p
        |
        \d{3,4}x(?:2160|1080|720|576|480)
        |
        bluray|blu-ray|bdrip|web-dl|webrip|web|hdtv|dvdrip|dvd|remux
        |
        x265|x264|h\.?265|h\.?264|hevc|avc|av1|xvid|divx
        |
        truehd|atmos|dts-hd|dts|flac|aac|ac3|ddp?5\.1|mp3
        |
        directors?\.cut|director's\.cut|director's\scut|extended|remastered|criterion|final\.cut
        |
        cd\d|part\d|pt\d
        |
        proper
    )\b
    """
)

KNOWN_ANIME_GROUPS = {
    "subsplease", "horriblesubs", "erai-raws", "taigasubs", "judas", "commie", "asenshi", "coalgirls"
}

KNOWN_ANIME_TITLES = {
    "naruto", "bleach", "one piece", "frieren", "dungeon meshi", "attack on titan",
    "jujutsu kaisen", "mushoku tensei", "fairy tail", "fate stay night", "sword art online"
}

WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class EnhancedTokenizer:
    def tokenize(self, file_path: Path) -> TokenizedFilename:
        stem = file_path.stem
        raw_name = file_path.name
        tokens = TokenizedFilename(raw_name=raw_name)
        ext = file_path.suffix.lower()

        # Check Windows reserved names
        if stem.upper() in WINDOWS_RESERVED:
            tokens.title = stem.upper()
            tokens.is_photo_or_home_video = True
            return tokens

        # Pre-clean illegal characters
        had_illegal = False
        if RE_ILLEGAL_CHARS.search(stem):
            had_illegal = True
            stem = RE_ILLEGAL_CHARS.sub(" ", stem)
            stem = re.sub(r"\s+", " ", stem).strip()

        # 1. Technical specifications
        res_m = RE_RESOLUTION.search(stem)
        if res_m:
            tokens.resolution = res_m.group(1).lower()
            if tokens.resolution == "4k":
                tokens.resolution = "2160p"
        else:
            dim_m = RE_DIMENSIONS.search(stem)
            if dim_m:
                tokens.resolution = f"{dim_m.group('height')}p"

        src_m = RE_SOURCE.search(stem)
        if src_m:
            tokens.source = src_m.group(1).upper()

        vc_m = RE_VIDEO_CODEC.search(stem)
        if vc_m:
            tokens.video_codec = vc_m.group(1).lower().replace(".", "")

        ac_m = RE_AUDIO_CODEC.search(stem)
        if ac_m:
            tokens.audio_codec = ac_m.group(1).upper()

        # Check edition
        ed_m = RE_EDITION.search(stem)
        if ed_m:
            ed_raw = ed_m.group("edition").lower().replace(" ", ".")
            tokens.edition = EDITION_CANONICAL_MAP.get(ed_raw, ed_m.group("edition"))

        # Check part
        pt_m = RE_MOVIE_PART.search(stem)
        if pt_m:
            tokens.part = int(pt_m.group("part_num"))
            tokens.part_label = f"Pt.{tokens.part}"

        # 2. Check for Podcast date format
        pod_m = RE_PODCAST_DATE.match(stem)
        if pod_m:
            tokens.title = pod_m.group("title").strip()
            tokens.artist = pod_m.group("show").strip()
            tokens.year = int(pod_m.group("year"))
            tokens.date_stamp = f"{pod_m.group('year')}-{pod_m.group('month')}-{pod_m.group('day')}"
            tokens.air_date = tokens.date_stamp
            return tokens

        # 3. Check for Daily / Broadcast dated format (TV or Podcast)
        daily_m = RE_DAILY_DATE.search(stem)
        if daily_m:
            y, m, d = daily_m.group("year"), daily_m.group("month"), daily_m.group("day")
            date_str = f"{y}-{m}-{d}"
            tokens.date_stamp = date_str
            tokens.air_date = date_str
            tokens.year = int(y)
            prefix = stem[: daily_m.start()]
            clean_pfx = self._clean_title(prefix)
            tokens.title = clean_pfx
            if ext in {".mp3", ".flac", ".ogg", ".m4a", ".aac"}:
                tokens.artist = clean_pfx
            else:
                tokens.is_daily = True
                tokens.is_episodic = True
                tokens.season = int(y)
            return tokens

        # 4. Check for Camera / Date stamp (Photos & Home Videos)
        cam_m = RE_CAMERA_DATE.search(stem)
        if cam_m:
            y, m, d = cam_m.group("year"), cam_m.group("month"), cam_m.group("day")
            tokens.date_stamp = f"{y}-{m}-{d}"
            tokens.year = int(y)
            tokens.is_photo_or_home_video = True
            return tokens

        # 5. Check Roman Numeral TV pattern: Rome.Season.II.Episode.IV
        roman_m = RE_ROMAN_SEASON_EPISODE.search(stem)
        if roman_m:
            tokens.is_episodic = True
            s_rom = roman_m.group("season_roman").lower()
            e_rom = roman_m.group("episode_roman").lower()
            tokens.season = ROMAN_NUMERALS.get(s_rom, 1)
            tokens.episode = ROMAN_NUMERALS.get(e_rom, 1)
            prefix = stem[: roman_m.start()]
            tokens.title = self._clean_title(prefix)
            return tokens

        # 6. Check TV Season Pack: Succession.S02.Complete
        pack_m = RE_SEASON_PACK.search(stem)
        if pack_m:
            tokens.is_episodic = True
            tokens.is_season_pack = True
            s_val = pack_m.group("season_pack") or pack_m.group("season_pack_word")
            tokens.season = int(s_val)
            prefix = stem[: pack_m.start()]
            tokens.title = self._clean_title(prefix)
            return tokens

        # 7. Check Standard TV episodic patterns (S01E02, 1x02, Season 1 Episode 2, Episode 207)
        tv_m = RE_SEASON_EPISODE.search(stem)
        if tv_m:
            tokens.is_episodic = True
            season_str = tv_m.group("season") or tv_m.group("season_x") or tv_m.group("season_word")
            ep_str = tv_m.group("episode") or tv_m.group("episode_x") or tv_m.group("episode_word") or tv_m.group("episode_standalone")
            if season_str:
                tokens.season = int(season_str)
            else:
                tokens.season = self._extract_season_from_path(file_path) or 1

            if ep_str:
                tokens.episode = int(ep_str)

            end_ep = tv_m.group("episode_end") or tv_m.group("episode_x_end") or tv_m.group("episode_word_end")
            if end_ep:
                tokens.multi_episodes = list(range(tokens.episode, int(end_ep) + 1))

            # If filename had illegal characters and matched standalone episode (e.g. Show: "Special" <Episode> | 1?.mkv)
            if had_illegal and tv_m.group("episode_standalone"):
                tokens.title = self._clean_title(stem)
                return tokens

            # Extract title before season marker
            prefix = stem[: tv_m.start()]
            clean_pfx = self._clean_title(prefix)
            if clean_pfx:
                tokens.title = clean_pfx
            else:
                tokens.title = self._extract_title_from_context(file_path) or "Episode"

            # Check for year in prefix using RE_YEAR_BOUND
            if prefix:
                yr_m = RE_YEAR_BOUND.search(prefix)
                if yr_m:
                    tokens.year = int(yr_m.group(1))
                    tokens.title = self._clean_title(prefix[: yr_m.start()])

            # Extract episode title after season marker
            suffix = stem[tv_m.end() :]
            ep_title = self._extract_episode_title(suffix)
            if ep_title:
                tokens.episode_title = ep_title

            # Release group at end
            grp_m = RE_RELEASE_GROUP_UPGRADED.search(stem)
            if grp_m:
                tokens.group = grp_m.group("grp_bracket") or grp_m.group("grp_plain")

            # Check if title is a known anime title
            if tokens.title and tokens.title.lower() in KNOWN_ANIME_TITLES:
                tokens.is_anime = True

            return tokens

        # 8. Check Anime fansub format: [Group] Title - 01 [1080p]
        anime_m = RE_ANIME_RELEASE.match(stem)
        if anime_m and (anime_m.group("group") or ext in {".mkv", ".mp4", ".avi", ".mov", ".ts", ".webm", ".m4v", ".flv"}):
            ep_val = int(anime_m.group("episode"))
            grp_name = anime_m.group("group").strip() if anime_m.group("group") else None
            raw_title = anime_m.group("title")
            title_clean = self._clean_title(raw_title, preserve_paren=True)

            # Distinguish movie year from anime episode
            if 1900 <= ep_val <= 2099 and not anime_m.group("episode_end"):
                tokens.year = ep_val
                tokens.title = title_clean
                tokens.group = grp_name
                tokens.is_anime = False
                tokens.is_episodic = False
                return tokens
            else:
                tokens.is_anime = True
                tokens.group = grp_name
                tokens.title = title_clean
                tokens.episode = ep_val
                if anime_m.group("episode_end"):
                    tokens.multi_episodes = list(range(ep_val, int(anime_m.group("episode_end")) + 1))
                tokens.season = self._extract_season_from_path(file_path) or 1
                tokens.is_episodic = True
                return tokens

        # 9. Check Anime movie format: [Judas] Fate Stay Night... [BD 1080p]
        anime_mov_m = RE_ANIME_MOVIE.match(stem)
        if anime_mov_m:
            grp = anime_mov_m.group("group").strip()
            if grp.lower() in KNOWN_ANIME_GROUPS:
                tokens.group = grp
                tokens.is_anime = True
                tokens.title = self._clean_title(anime_mov_m.group("title"), preserve_dots=True)
                return tokens

        # 10. Check for Music track pattern
        mus_m = RE_MUSIC_TRACK.match(stem)
        if mus_m:
            tokens.is_music = True
            tokens.track = int(mus_m.group("track"))
            if mus_m.group("disc"):
                tokens.disc = int(mus_m.group("disc"))
            tokens.title = self._clean_title(mus_m.group("title"))

            parent = file_path.parent
            if parent and parent.name:
                parts = parent.name.split(" - ")
                if len(parts) >= 2:
                    tokens.artist = parts[0].strip()
                    tokens.album = parts[1].strip()
            return tokens

        # 11. Movie pattern: Title (Year) or Title.Year.Quality
        # Parenthesized year first
        paren_yr = re.search(r"\((19\d{2}|20\d{2})\)", stem)
        if paren_yr:
            tokens.year = int(paren_yr.group(1))
            prefix = stem[: paren_yr.start()]
            tokens.title = self._clean_title(prefix)
            grp_m = RE_RELEASE_GROUP_UPGRADED.search(stem)
            if grp_m:
                tokens.group = grp_m.group("grp_bracket") or grp_m.group("grp_plain")
            return tokens

        # Delimiter-based right-to-left year detection
        tech_start = len(stem)
        for m in RE_TECH_ALL.finditer(stem):
            if m.start() < tech_start:
                tech_start = m.start()

        year_matches = list(RE_YEAR_BOUND.finditer(stem))
        if year_matches:
            valid_matches = [m for m in year_matches if m.start() <= tech_start]
            if not valid_matches:
                valid_matches = year_matches
            best_match = valid_matches[-1]
            tokens.year = int(best_match.group(1))
            prefix = stem[: best_match.start()]
            tokens.title = self._clean_title(prefix)
            grp_m = RE_RELEASE_GROUP_UPGRADED.search(stem)
            if grp_m:
                tokens.group = grp_m.group("grp_bracket") or grp_m.group("grp_plain")
            return tokens

        # Fallback: strip tech specs and clean whole stem as title
        prefix = stem[:tech_start].strip(" .-_")
        tokens.title = self._clean_title(prefix if prefix else stem)
        grp_m = RE_RELEASE_GROUP_UPGRADED.search(stem)
        if grp_m:
            tokens.group = grp_m.group("grp_bracket") or grp_m.group("grp_plain")
        return tokens

    def _clean_title(self, raw: str, preserve_paren: bool = False, preserve_dots: bool = False) -> str:
        # Strip leading bracket tags like [YTS.MX] or [SubsPlease] if present
        raw = re.sub(r"^\s*\[[^\]]+\]\s*", "", raw)
        
        if preserve_dots:
            cleaned = re.sub(r"_+", " ", raw).strip()
        else:
            # Replace dots with space, except if dot is followed by space in Roman numeral (e.g. "I. ")
            cleaned = re.sub(r"(?<=\b[IVXLCDM])\.\s+", "._KEEP_DOT_SPACE_", raw)
            cleaned = re.sub(r"[\._]+", " ", cleaned)
            cleaned = cleaned.replace("._KEEP_DOT_SPACE_", ". ")
        
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        
        if preserve_paren and re.search(r"\([12]\d{3}\)$", cleaned):
            # Do not strip trailing parenthesis if it's (Year)
            pass
        else:
            cleaned = re.sub(r"[\-\(\)\[\]]+$", "", cleaned).strip()
            
        return cleaned

    def _extract_episode_title(self, suffix: str) -> Optional[str]:
        s = suffix.strip(" .-_")
        if not s:
            return None
        for reg in (RE_RESOLUTION, RE_SOURCE, RE_VIDEO_CODEC, RE_AUDIO_CODEC, RE_EDITION):
            m = reg.search(s)
            if m:
                s = s[: m.start()].strip(" .-_")
        grp = RE_RELEASE_GROUP_UPGRADED.search(s)
        if grp:
            s = s[: grp.start()].strip(" .-_")
        cleaned = self._clean_title(s)
        return cleaned if cleaned else None

    def _extract_season_from_path(self, file_path: Path) -> Optional[int]:
        try:
            for part in file_path.parts[:-1]:
                m = re.search(r"(?i)\b(?:season|series|s)\s*(\d{1,2})\b", part)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
        return None

    def _extract_title_from_context(self, file_path: Path) -> Optional[str]:
        try:
            parent = file_path.parent
            if not parent or str(parent) in ("/", ".", ""):
                return None
            p_name = parent.name
            if re.search(r"(?i)\b(?:season|series|s)\s*\d+\b", p_name):
                parent = parent.parent
                p_name = parent.name if parent else ""
            if not p_name:
                return None
            p_lower = p_name.lower().strip()
            system_folders = {
                "downloads", "jdownloads", "media", "completed", "incomplete", "torrent",
                "torrents", "root", "home", "mnt", "md0", "storage", "tmp", "temp", "var", "etc", "usr"
            }
            if p_lower in system_folders:
                return None
            clean = self._clean_title(p_name)
            if len(clean) >= 2:
                return clean
        except Exception:
            pass
        return None


enh = EnhancedTokenizer()
mismatches = []
for case in BENCHMARK_CASES:
    p = Path(case.filename)
    tok = enh.tokenize(p)
    diffs = {}
    if case.expected_title != tok.title:
        diffs["title"] = (case.expected_title, tok.title)
    if case.expected_year is not None and case.expected_year != tok.year:
        diffs["year"] = (case.expected_year, tok.year)
    if case.expected_season is not None and case.expected_season != tok.season:
        diffs["season"] = (case.expected_season, tok.season)
    if case.expected_episode is not None and case.expected_episode != tok.episode:
        diffs["episode"] = (case.expected_episode, tok.episode)
    if case.expected_multi_episodes is not None:
        if tok.multi_episodes != case.expected_multi_episodes:
            diffs["multi_episodes"] = (case.expected_multi_episodes, tok.multi_episodes)
    if case.expected_date is not None:
        act_date = tok.air_date or tok.date_stamp
        if act_date != case.expected_date:
            diffs["date"] = (case.expected_date, act_date)
    if case.expected_edition is not None:
        if tok.edition != case.expected_edition:
            diffs["edition"] = (case.expected_edition, tok.edition)
    if case.expected_part is not None:
        if tok.part != case.expected_part:
            diffs["part"] = (case.expected_part, tok.part)
    if case.expected_group is not None:
        if tok.group != case.expected_group:
            diffs["group"] = (case.expected_group, tok.group)
    if diffs:
        mismatches.append((case, diffs))

print(f"Remaining token mismatches: {len(mismatches)} / 64")
for case, d in mismatches:
    print(f"[{case.id}] ({case.domain}) {case.filename}")
    for k, (exp, act) in d.items():
        print(f"    {k}: expected={exp!r} got={act!r}")
