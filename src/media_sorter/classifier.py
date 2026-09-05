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
from .tokenizer import TokenizedFilename

logger = structlog.get_logger(__name__)


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

        # 4. Audio-only handling
        if metadata.has_audio and not metadata.has_video:
            return self._classify_audio(scanned, tokens, metadata)

        # 5. Video handling (TV, Anime, Movie, Documentary, Home Video)
        if metadata.has_video or metadata.mime_type.startswith("video/") or scanned.path.suffix.lower() in {
            ".mp4", ".mkv", ".m4v", ".avi", ".mov", ".ts", ".webm", ".wmv", ".flv"
        }:
            return self._classify_video(scanned, tokens, metadata)

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
        if tokens.date_stamp and not tokens.is_photo_or_home_video:
            pod_score += 0.35
            pod_signals.append("dated_filename")
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
        # If camera date stamp or recorded from mobile/camcorder without scene tags, and short/medium duration
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
        # Keyword in path or filename
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
        # High confidence anime indicators
        if tokens.is_anime or "anime" in path_str or "[horriblesubs]" in stem_lower or "[subsplease]" in stem_lower or "[judas]" in stem_lower or "[erai-raws]" in stem_lower:
            anime_score = 0.70
            a_signals = []
            if tokens.is_anime:
                anime_score += 0.2
                a_signals.append("fansub_syntax")
            if tokens.group:
                anime_score += 0.08
                a_signals.append("release_group")
            if "anime" in path_str:
                anime_score += 0.1
                a_signals.append("anime_folder")

            conf = min(anime_score, 0.98)
            return ClassificationResult(
                category="anime",
                confidence=conf,
                signals={"anime_signals": a_signals},
                tokens=tokens,
                metadata=metadata,
                needs_quarantine=conf < self.confidence_threshold,
                quarantine_reason="Low confidence anime release" if conf < self.confidence_threshold else None,
            )

        is_tv_folder = bool(re.search(r"(?i)[/\\](?:tv[/\\]|tv[-_\s]shows?|tv[-_\s]series|season[-_\s]*\d+)", path_str))
        is_movie_folder = bool(re.search(r"(?i)[/\\](?:movies?[/\\]|films?[/\\])", path_str))

        # 4. TV Show (Episodic) Check:
        is_tv = False
        if tokens.is_episodic:
            is_tv = True
        elif is_tv_folder and not tokens.year:
            is_tv = True
        elif is_tv_folder and tokens.episode is not None:
            is_tv = True

        if is_tv:
            tv_score = 0.40
            tv_signals = []
            if tokens.is_episodic:
                tv_score += 0.45
                tv_signals.append("season_episode_pattern")
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
        if tokens.year:
            movie_score += 0.35
            m_signals.append("year_in_title")
        if tokens.resolution or tokens.source or tokens.video_codec:
            movie_score += 0.15
            m_signals.append("scene_technical_tags")
        if is_movie_folder or "movie" in path_str or "film" in path_str:
            movie_score += 0.15
            m_signals.append("movie_folder_hint")
        if dur >= 3600:  # > 1 hour
            movie_score += 0.15
            m_signals.append("feature_film_duration")

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
