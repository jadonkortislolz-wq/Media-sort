"""Filename and path tokenization engine for Media Sorter.

Robustly extracts semantic media tokens (title, year, season, episode, artist,
album, track, disc, quality, codec, release group, date stamps) from messy filenames,
scene releases, anime fansub conventions, and folder hierarchies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Regex patterns for Video & Episodic Media
RE_SEASON_EPISODE = re.compile(
    r"""(?ix)
    (?:
        (?<![0-9a-z])s(?P<season>\d{1,2})[\.\s_-]*(?:e|ep|ed|op)(?P<episode>\d{1,3})
        (?:[\.\s_-]*(?:e|x|-)(?P<episode_end>\d{1,3}))?(?![0-9]) # multi-episode like S01E01-E02
    |
        (?<![0-9a-z])(?P<season_x>\d{1,2})x(?!(?:264|265|vid|hevc|avc))(?P<episode_x>\d{1,3})(?![0-9])
    |
        \bseason[\.\s_-]*(?P<season_word>\d{1,2})[\.\s_-]*(?:episode|ep)[\.\s_-]*(?P<episode_word>\d{1,3})\b
    |
        \b(?:episodes?|ep)[\.\s_-]*(?P<episode_standalone>\d{1,4})(?![0-9])\b
    )
    """
)

# Anime fansub format: [ReleaseGroup] Show Title - 01 (or 01v2) [1080p] [CRC32].mkv
RE_ANIME_RELEASE = re.compile(
    r"""(?ix)
    ^\s*(?:\[(?P<group>[^\]]+)\]\s*)?
    (?P<title>[^\[\]\(\)]+?)\s*-\s*
    (?P<episode>\d{1,4})(?:v\d+)?\s*
    (?:\s+(?:\[?[0-9A-Fa-f]{8}\]?|\[(?P<tag>[^\]]+)\]|\((?P<tag_paren>[^\)]+)\)|[A-Za-z0-9_.-]+))*\s*\]?$
    """
)

# Movie title and year: Title.Year.Quality or Title (Year)
RE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")

# Technical specs
RE_RESOLUTION = re.compile(r"\b(2160p|4k|1080p|1080i|720p|576p|480p)\b", re.IGNORECASE)
RE_DIMENSIONS = re.compile(r"\b(?:\d{3,4})x(?P<height>2160|1080|720|576|480)\b", re.IGNORECASE)
RE_SOURCE = re.compile(r"\b(bluray|blu-ray|bdrip|web-dl|webrip|web|hdtv|dvdrip|dvd|remux)\b", re.IGNORECASE)
RE_VIDEO_CODEC = re.compile(r"\b(x265|x264|h\.?265|h\.?264|hevc|avc|av1|xvid|divx)\b", re.IGNORECASE)
RE_AUDIO_CODEC = re.compile(r"\b(truehd|atmos|dts-hd|dts|flac|aac|ac3|ddp?5\.1|mp3)\b", re.IGNORECASE)
RE_RELEASE_GROUP = re.compile(r"-([A-Za-z0-9_]+)(?:\[.*?\])?$", re.IGNORECASE)

# Music / Audio track patterns: 01 - Title, 1-01 Title, Artist - 01 - Title
RE_MUSIC_TRACK = re.compile(
    r"""(?ix)
    ^(?:(?P<disc>\d{1,2})[-_.])?(?P<track>\d{1,3})[\.\s_-]+(?P<title>.+)$
    """
)

# Photo and Home Video date stamps: IMG_20240812_142010, VID_20240812_142010, 2024-08-12 14.20.10
RE_CAMERA_DATE = re.compile(
    r"""(?ix)
    (?:img|vid|dsc|pano|mov)?[-_]?(?P<year>19\d{2}|20\d{2})[-_]?(?P<month>\d{2})[-_]?(?P<day>\d{2})
    (?:[-_](?P<hour>\d{2})[-_]?(?P<minute>\d{2})[-_]?(?P<second>\d{2}))?
    """
)

# Podcast dated format: Show Name - 2026-03-15 - Episode Title
RE_PODCAST_DATE = re.compile(
    r"""(?ix)
    ^(?P<show>.+?)\s*-\s*(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\s*-\s*(?P<title>.+)$
    """
)


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
    is_anime: bool = False
    is_episodic: bool = False
    is_music: bool = False
    is_photo_or_home_video: bool = False


class FilenameTokenizer:
    """Parses raw filenames and directory paths into semantic tokens."""

    def tokenize(self, file_path: Path) -> TokenizedFilename:
        stem = file_path.stem
        raw_name = file_path.name
        tokens = TokenizedFilename(raw_name=raw_name)

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

        # 2. Check for Podcast date format
        pod_m = RE_PODCAST_DATE.match(stem)
        if pod_m:
            tokens.title = pod_m.group("title").strip()
            tokens.artist = pod_m.group("show").strip()
            tokens.year = int(pod_m.group("year"))
            tokens.date_stamp = f"{pod_m.group('year')}-{pod_m.group('month')}-{pod_m.group('day')}"
            return tokens

        # 3. Check for Camera / Date stamp (Photos & Home Videos)
        cam_m = RE_CAMERA_DATE.search(stem)
        if cam_m:
            y, m, d = cam_m.group("year"), cam_m.group("month"), cam_m.group("day")
            tokens.date_stamp = f"{y}-{m}-{d}"
            tokens.year = int(y)
            tokens.is_photo_or_home_video = True

        # 4. Check for Anime format
        anime_m = RE_ANIME_RELEASE.match(stem)
        if anime_m and (anime_m.group("group") or file_path.suffix.lower() in {".mkv", ".mp4", ".avi", ".mov", ".ts", ".webm", ".m4v", ".flv"}):
            ep_val = int(anime_m.group("episode"))
            grp_name = anime_m.group("group").strip() if anime_m.group("group") else None
            if 1900 <= ep_val <= 2099:
                # 4-digit number in year range is a release year (e.g. [Group] Title - 2024 [1080p])
                tokens.year = ep_val
                tokens.title = self._clean_title(anime_m.group("title"))
                tokens.group = grp_name
                tokens.is_anime = False
                tokens.is_episodic = False
                return tokens
            else:
                tokens.is_anime = True
                tokens.group = grp_name
                tokens.title = self._clean_title(anime_m.group("title"))
                tokens.episode = ep_val
                tokens.season = self._extract_season_from_path(file_path) or 1
                tokens.is_episodic = True
                return tokens

        # 4. Check for Standard TV episodic patterns (S01E02, 1x02, Season 1 Episode 2, Episode 207)
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

            end_ep = tv_m.group("episode_end")
            if end_ep:
                tokens.multi_episodes = list(range(tokens.episode, int(end_ep) + 1))

            # Extract title before season marker
            prefix = stem[: tv_m.start()]
            clean_pfx = self._clean_title(prefix)
            if clean_pfx:
                tokens.title = clean_pfx
            else:
                tokens.title = self._extract_title_from_context(file_path) or "Episode"

            # Check for year in prefix
            if prefix:
                yr_m = RE_YEAR.search(prefix)
                if yr_m:
                    tokens.year = int(yr_m.group(1))
                    tokens.title = self._clean_title(prefix[: yr_m.start()])

            # Extract episode title after season marker
            suffix = stem[tv_m.end() :]
            ep_title = self._extract_episode_title(suffix)
            if ep_title:
                tokens.episode_title = ep_title

            # Release group at end
            grp_m = RE_RELEASE_GROUP.search(stem)
            if grp_m:
                tokens.group = grp_m.group(1)

            return tokens

        # 6. Check for Music track pattern
        mus_m = RE_MUSIC_TRACK.match(stem)
        if mus_m:
            tokens.is_music = True
            tokens.track = int(mus_m.group("track"))
            if mus_m.group("disc"):
                tokens.disc = int(mus_m.group("disc"))
            tokens.title = self._clean_title(mus_m.group("title"))

            # Parent folder context often holds Artist and Album
            parent = file_path.parent
            if parent and parent.name:
                parts = parent.name.split(" - ")
                if len(parts) >= 2:
                    tokens.artist = parts[0].strip()
                    tokens.album = parts[1].strip()
            return tokens

        # 7. Movie pattern: Title (Year) or Title.Year.Quality
        yr_m = RE_YEAR.search(stem)
        if yr_m:
            tokens.year = int(yr_m.group(1))
            prefix = stem[: yr_m.start()]
            tokens.title = self._clean_title(prefix)
            grp_m = RE_RELEASE_GROUP.search(stem)
            if grp_m:
                tokens.group = grp_m.group(1)
            return tokens

        # Fallback: clean the whole stem as title
        tokens.title = self._clean_title(stem)
        return tokens

    def _clean_title(self, raw: str) -> str:
        """Replace dots, underscores, and scene separators with clean spaces."""
        raw = re.sub(r"^\s*\[[^\]]+\]\s*", "", raw)
        cleaned = re.sub(r"[\._]+", " ", raw).strip()
        # Remove trailing hyphens or brackets
        cleaned = re.sub(r"[\-\(\)\[\]]+$", "", cleaned).strip()
        return cleaned

    def _extract_episode_title(self, suffix: str) -> Optional[str]:
        """Extract episode title from string after SxxExx marker, stripping tech tags."""
        s = suffix.strip(" .-_")
        if not s:
            return None
        # Split by known tech tags
        for reg in (RE_RESOLUTION, RE_SOURCE, RE_VIDEO_CODEC, RE_AUDIO_CODEC):
            m = reg.search(s)
            if m:
                s = s[: m.start()].strip(" .-_")

        # Strip release group
        grp = RE_RELEASE_GROUP.search(s)
        if grp:
            s = s[: grp.start()].strip(" .-_")

        cleaned = self._clean_title(s)
        return cleaned if cleaned else None

    def _extract_season_from_path(self, file_path: Path) -> Optional[int]:
        """Attempt to extract season number from parent directory names like 'Season 2' or 'S03'."""
        try:
            for part in file_path.parts[:-1]:
                m = re.search(r"(?i)\b(?:season|series|s)\s*(\d{1,2})\b", part)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
        return None

    def _extract_title_from_context(self, file_path: Path) -> Optional[str]:
        """Attempt to extract show title from immediate parent directory (e.g. Show/Episode 01.mkv or Show/Season 1/Ep01.mkv)."""
        try:
            parent = file_path.parent
            if not parent or str(parent) in ("/", ".", ""):
                return None
            p_name = parent.name
            if re.search(r"(?i)\b(?:season|series|s)\s*\d+\b", p_name):
                # Ascend one level if inside a season folder
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
