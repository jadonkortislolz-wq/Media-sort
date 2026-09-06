"""Multi-signal classification engine for Media Sorter.

Combines filename patterns, MIME types, container/stream characteristics, duration,
embedded tags, directory structure hints, and external provider lookups to classify
media files with weighted confidence scoring and diagnostic transparency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

import structlog

from .analyzer import MediaMetadata
from .providers import MetadataProvider, ProviderResult
from .scanner import ScannedFile
from .tokenizer import TokenizedFilename, KNOWN_ANIME_GROUPS, KNOWN_ANIME_TITLES

logger = structlog.get_logger(__name__)

RE_BROADCAST_DATE = re.compile(r"\b((?:19|20)\d{2})[-._](0[1-9]|1[0-2])[-._](0[1-9]|[12]\d|3[01])\b")
RE_ANIME_GROUPS = re.compile(
    r"\[(subsplease|horriblesubs|erai-raws|taigasubs|judas|commie|dame-desu|asw|chunchunmaru|ember)\]",
    re.IGNORECASE,
)
RE_NON_ANIME_GROUPS = re.compile(r"\[(yts(?:\.mx)?|rartv|tgx|eztv)\]", re.IGNORECASE)
RE_CRC32 = re.compile(r"\[[0-9A-Fa-f]{8}\]")
RE_OVA = re.compile(r"\b(ova|oad)\b", re.IGNORECASE)
RE_COUR_TAG = re.compile(r"\b(?:\d+(?:st|nd|rd|th)\s+season|cour\s*\d+|s\d+\s*-)\b", re.IGNORECASE)
RE_STANDALONE_EPISODE = re.compile(r"\b(?:episodes?|ep)[\.\s_-]*(\d{1,4})\b", re.IGNORECASE)
RE_STD_TV = re.compile(
    r"(?<![0-9a-z])s\d{1,2}[\.\s_-]*(?:e|ep|ed|op)\d{1,3}|(?<![0-9a-z])\d{1,2}x(?!(?:264|265))\d{1,3}|\bseason[\.\s_-]*(?:\d+|[ivx]+)[\.\s_-]*(?:episode|ep)[\.\s_-]*(?:\d+|[ivx]+)\b|\bs\d{1,2}\.complete\b",
    re.IGNORECASE,
)


@dataclass
class ClassificationResult:
    category: str  # movie, tv, anime, music, audiobook, podcast, documentary, home_video, photo, subtitle, artwork, metadata, archive, unknown
    confidence: float  # 0.0 - 1.0
    signals: Dict[str, Any] = field(default_factory=dict)
    tokens: Optional[TokenizedFilename] = None
    metadata: Optional[MediaMetadata] = None
    provider_result: Optional[ProviderResult] = None
    needs_quarantine: bool = False
    quarantine_reason: Optional[str] = None


class MediaClassifier:
    """Classifies files into media categories using multi-signal weighted heuristics."""

    def __init__(
        self,
        confidence_threshold: float = 0.75,
        provider: Optional[MetadataProvider] = None,
    ):
        self.confidence_threshold = confidence_threshold
        self.provider = provider

    def classify(
        self,
        scanned: ScannedFile,
        tokens: TokenizedFilename,
        metadata: MediaMetadata,
    ) -> ClassificationResult:
        """Run classification pipeline and return winning category with confidence."""
        # 1. Immediate Sidecar handling
        if scanned.is_sidecar:
            return self._classify_sidecar(scanned, tokens, metadata)

        # 2. Immediate Archive handling
        if metadata.container in ("zip", "rar", "7z", "tar", "gz"):
            return ClassificationResult(
                category="archive",
                confidence=0.95,
                signals={"container": metadata.container, "mime_type": metadata.mime_type},
                tokens=tokens,
                metadata=metadata,
            )

        # 3. Photo / Image handling
        if metadata.mime_type.startswith("image/"):
            return self._classify_image(scanned, tokens, metadata)

        # 4. Video handling (TV, Anime, Movie, Documentary, Home Video)
        if (
            metadata.has_video
            or metadata.mime_type.startswith("video/")
            or scanned.path.suffix.lower() in {
                ".mp4", ".mkv", ".m4v", ".avi", ".mov", ".ts", ".webm", ".wmv", ".flv"
            }
        ):
            return self._classify_video(scanned, tokens, metadata)

        # 5. Audio-only handling
        if (
            metadata.has_audio
            or metadata.mime_type.startswith("audio/")
            or scanned.path.suffix.lower() in {
                ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".alac", ".aiff"
            }
        ):
            return self._classify_audio(scanned, tokens, metadata)

        # 6. Fallback for unrecognized formats
        return ClassificationResult(
            category="unknown",
            confidence=0.0,
            signals={"reason": "Unrecognized MIME type and non-media extension"},
            tokens=tokens,
            metadata=metadata,
            needs_quarantine=True,
            quarantine_reason="Unrecognized format",
        )

    def _classify_sidecar(
        self, scanned: ScannedFile, tokens: TokenizedFilename, metadata: MediaMetadata
    ) -> ClassificationResult:
        stype = scanned.sidecar_type or "metadata"
        category_map = {
            "subtitle": "subtitle",
            "artwork": "artwork",
            "metadata": "metadata",
            "extra": "movie",  # Extras typically stay alongside movie or show
        }
        category = category_map.get(stype, "metadata")
        confidence = 0.95 if scanned.primary_media_path else 0.80

        return ClassificationResult(
            category=category,
            confidence=confidence,
            signals={
                "sidecar_type": stype,
                "has_primary": bool(scanned.primary_media_path),
                "primary_path": str(scanned.primary_media_path) if scanned.primary_media_path else None,
            },
            tokens=tokens,
            metadata=metadata,
        )

    def _classify_image(
        self, scanned: ScannedFile, tokens: TokenizedFilename, metadata: MediaMetadata
    ) -> ClassificationResult:
        signals: Dict[str, Any] = {"mime": metadata.mime_type}
        confidence = 0.85

        # Check for EXIF camera or date stamp
        if "datetime_original" in metadata.tags or tokens.date_stamp:
            signals["has_date_stamp"] = True
            confidence = 0.95
        if "camera_model" in metadata.tags:
            signals["camera_model"] = metadata.tags["camera_model"]
            confidence = 0.98

        # Check if it might be artwork
        stem_lower = scanned.path.stem.lower()
        if stem_lower in ("cover", "folder", "poster", "fanart", "banner", "front", "back"):
            return ClassificationResult(
                category="artwork",
                confidence=0.95,
                signals={"artwork_keyword": stem_lower},
                tokens=tokens,
                metadata=metadata,
            )

        return ClassificationResult(
            category="photo",
            confidence=confidence,
            signals=signals,
            tokens=tokens,
            metadata=metadata,
        )

    def _classify_audio(
        self, scanned: ScannedFile, tokens: TokenizedFilename, metadata: MediaMetadata
    ) -> ClassificationResult:
        path_str = str(scanned.path).lower()
        dur = metadata.duration_seconds
        tags = metadata.tags

        # Check Audiobook indicators
        audiobook_score = 0.0
        ab_signals = []
        if "audiobook" in path_str or "audio books" in path_str:
            audiobook_score += 0.4
            ab_signals.append("folder_name_audiobook")
        if dur > 1800:  # > 30 minutes
            audiobook_score += 0.3
            ab_signals.append("long_duration")
        if scanned.path.suffix.lower() == ".m4b":
            audiobook_score += 0.5
            ab_signals.append("m4b_extension")
        if any(k in tags for k in ("narrator", "reader", "series", "composer")):
            audiobook_score += 0.2
            ab_signals.append("audiobook_tags")

        if audiobook_score >= 0.6:
            return ClassificationResult(
                category="audiobook",
                confidence=min(audiobook_score, 0.98),
                signals={"audiobook_signals": ab_signals, "duration": dur},
                tokens=tokens,
                metadata=metadata,
            )

        # Check Podcast indicators
        pod_score = 0.0
        pod_signals = []
        if "podcast" in path_str or "podcasts" in path_str:
            pod_score += 0.4
            pod_signals.append("folder_name_podcast")
        if (tokens.date_stamp or tokens.air_date) and not tokens.is_photo_or_home_video:
            pod_score += 0.45
            pod_signals.append("dated_filename")
            if tokens.track is None and not tokens.is_music:
                pod_score += 0.30
                pod_signals.append("non_music_audio_with_date")
        elif RE_BROADCAST_DATE.search(scanned.path.stem):
            pod_score += 0.45
            pod_signals.append("dated_filename")
            if tokens.track is None and not tokens.is_music:
                pod_score += 0.30
                pod_signals.append("non_music_audio_with_date")

        if any(k in tags for k in ("podcast", "itunes_category", "show")):
            pod_score += 0.35
            pod_signals.append("podcast_tags")

        if pod_score >= 0.6:
            return ClassificationResult(
                category="podcast",
                confidence=min(pod_score, 0.95),
                signals={"podcast_signals": pod_signals},
                tokens=tokens,
                metadata=metadata,
            )

        # Standard Music classification
        music_score = 0.5  # Base audio file score
        m_signals = ["has_audio_stream"]
        if tokens.is_music or tokens.track is not None:
            music_score += 0.25
            m_signals.append("track_number_detected")
        if "artist" in tags or tokens.artist:
            music_score += 0.15
            m_signals.append("artist_present")
        if "album" in tags or tokens.album:
            music_score += 0.1
            m_signals.append("album_present")
        if 20 <= dur <= 900:  # 20s to 15m typical music track
            music_score += 0.1
            m_signals.append("typical_song_duration")
        if "music" in path_str or "albums" in path_str:
            music_score += 0.1
            m_signals.append("music_folder_hint")

        confidence = min(music_score, 0.99)
        needs_quar = confidence < self.confidence_threshold

        return ClassificationResult(
            category="music",
            confidence=confidence,
            signals={"music_signals": m_signals, "tags": tags},
            tokens=tokens,
            metadata=metadata,
            needs_quarantine=needs_quar,
            quarantine_reason="Audio file lacking track/artist metadata" if needs_quar else None,
        )

    def _classify_video(
        self, scanned: ScannedFile, tokens: TokenizedFilename, metadata: MediaMetadata
    ) -> ClassificationResult:
        path_str = str(scanned.path).lower()
        dur = metadata.duration_seconds
        stem_lower = scanned.path.stem.lower()

        # 1. Home Video Check:
        upper_base = scanned.path.stem.split(".")[0].upper()
        if upper_base in ("CON", "PRN", "AUX", "NUL"):
            return ClassificationResult(
                category="home_video",
                confidence=0.88,
                signals={"reserved_name": upper_base},
                tokens=tokens,
                metadata=metadata,
            )

        if (tokens.is_photo_or_home_video or stem_lower.startswith(("vid_", "mov_", "mvi_"))) and (
            dur > 0 and dur < 900 or "home" in path_str or "family" in path_str
        ):
            if not tokens.is_episodic and not tokens.resolution:
                return ClassificationResult(
                    category="home_video",
                    confidence=0.88,
                    signals={"camera_naming": True, "duration": dur},
                    tokens=tokens,
                    metadata=metadata,
                )

        # 2. Documentary check:
        if "documentary" in path_str or "docu" in stem_lower or "bbc." in stem_lower or "national.geographic" in stem_lower:
            doc_score = 0.85
            if tokens.year:
                doc_score += 0.1
            return ClassificationResult(
                category="documentary",
                confidence=min(doc_score, 0.95),
                signals={"keyword": "documentary", "year": tokens.year},
                tokens=tokens,
                metadata=metadata,
            )

        # 3. Anime Check:
        is_standard_tv = bool(RE_STD_TV.search(scanned.path.stem))
        is_non_anime_movie = bool(RE_NON_ANIME_GROUPS.search(scanned.path.stem))
        has_broadcast_date = bool(tokens.is_daily or tokens.air_date or RE_BROADCAST_DATE.search(scanned.path.stem))

        is_anime_candidate = False
        a_signals = []
        if not is_standard_tv and not is_non_anime_movie and not has_broadcast_date:
            if tokens.is_anime:
                is_anime_candidate = True
                a_signals.append("fansub_syntax")
            if RE_ANIME_GROUPS.search(scanned.path.stem) or (tokens.group and tokens.group.lower() in KNOWN_ANIME_GROUPS):
                is_anime_candidate = True
                a_signals.append("known_anime_group")
            if RE_CRC32.search(scanned.path.stem):
                is_anime_candidate = True
                a_signals.append("crc32_checksum")
            if RE_OVA.search(scanned.path.stem):
                is_anime_candidate = True
                a_signals.append("ova_tag")
            if RE_COUR_TAG.search(scanned.path.stem):
                is_anime_candidate = True
                a_signals.append("cour_tag")
            if RE_STANDALONE_EPISODE.search(scanned.path.stem) and not bool(re.search(r"\bseason\b", stem_lower)):
                is_anime_candidate = True
                a_signals.append("standalone_episode_keyword")
            if "anime" in path_str:
                is_anime_candidate = True
                a_signals.append("anime_folder")

        if is_anime_candidate:
            anime_score = 0.85
            if "known_anime_group" in a_signals:
                anime_score += 0.10
            if "crc32_checksum" in a_signals:
                anime_score += 0.04
            conf = min(anime_score, 0.99)
            return ClassificationResult(
                category="anime",
                confidence=conf,
                signals={"anime_signals": a_signals},
                tokens=tokens,
                metadata=metadata,
            )

        is_tv_folder = bool(re.search(r"(?i)[/\\](?:tv[/\\]|tv[-_\s]shows?|tv[-_\s]series|season[-_\s]*\d+)", path_str))
        is_movie_folder = bool(re.search(r"(?i)[/\\](?:movies?[/\\]|films?[/\\])", path_str))

        # 4. TV Show Check (Episodic and Daily Broadcasts):
        is_daily_tv = has_broadcast_date and (
            tokens.resolution
            or tokens.source
            or "daily" in stem_lower
            or "tonight" in stem_lower
            or "late" in stem_lower
            or "news" in stem_lower
            or dur >= 1200
        )

        is_tv = False
        if tokens.is_episodic or is_standard_tv or is_daily_tv:
            is_tv = True
        elif is_tv_folder and not tokens.year:
            is_tv = True
        elif is_tv_folder and tokens.episode is not None:
            is_tv = True

        if is_tv:
            tv_score = 0.40
            tv_signals = []
            if tokens.is_episodic or is_standard_tv:
                tv_score += 0.45
                tv_signals.append("season_episode_pattern")
            if is_daily_tv:
                tv_score += 0.45
                tv_signals.append("broadcast_date_pattern")
            if tokens.episode is not None:
                tv_score += 0.10
            if is_tv_folder:
                tv_score += 0.15
                tv_signals.append("tv_folder_hint")
            if 600 <= dur <= 5400 and not tokens.year:
                tv_score += 0.10
                tv_signals.append("episodic_duration")

            # Provider boost
            prov_res = None
            if self.provider and tokens.title and tv_score >= 0.6:
                try:
                    prov_res = self.provider.search_tv(
                        tokens.title, year=tokens.year, season=tokens.season, episode=tokens.episode
                    )
                    if prov_res:
                        tv_score += prov_res.confidence_boost
                        tv_signals.append("provider_verified")
                except Exception:
                    pass

            conf = min(tv_score, 0.99)
            needs_quar = conf < self.confidence_threshold

            return ClassificationResult(
                category="tv",
                confidence=conf,
                signals={"tv_signals": tv_signals},
                tokens=tokens,
                metadata=metadata,
                provider_result=prov_res,
                needs_quarantine=needs_quar,
                quarantine_reason="Low confidence TV classification" if needs_quar else None,
            )

        # 5. Movie Check:
        movie_score = 0.40
        m_signals = []
        if tokens.year and not has_broadcast_date:
            movie_score += 0.35
            m_signals.append("year_in_title")
        if tokens.resolution or tokens.source or tokens.video_codec:
            movie_score += 0.15
            m_signals.append("scene_technical_tags")
        if is_movie_folder or "movie" in path_str or "film" in path_str:
            movie_score += 0.15
            m_signals.append("movie_folder_hint")
        if dur >= 3600:  # > 1 hour
            movie_score += 0.20
            m_signals.append("feature_film_duration")

        # Check for movie extras tag
        if re.search(r"-(behindthescenes|deleted|trailer|featurette)\b", stem_lower):
            movie_score += 0.25
            m_signals.append("movie_extra_tag")

        # Provider boost
        prov_res = None
        if self.provider and tokens.title and movie_score >= 0.5:
            try:
                prov_res = self.provider.search_movie(tokens.title, year=tokens.year)
                if prov_res:
                    movie_score += prov_res.confidence_boost
                    m_signals.append("provider_verified")
            except Exception:
                pass

        conf = min(movie_score, 0.99)
        needs_quar = conf < self.confidence_threshold

        return ClassificationResult(
            category="movie",
            confidence=conf,
            signals={"movie_signals": m_signals, "duration": dur},
            tokens=tokens,
            metadata=metadata,
            provider_result=prov_res,
            needs_quarantine=needs_quar,
            quarantine_reason="Low confidence movie classification (missing year or title verification)"
            if needs_quar
            else None,
        )
