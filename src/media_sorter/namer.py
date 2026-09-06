"""Naming and path formatting engine for Media Sorter.

Renders user-defined naming templates, safely formats multi-part tags, pairs sidecars
with primary media files, and enforces rigorous cross-platform filename sanitization
(Linux, Windows, macOS, NTFS, SMB/NFS, exFAT).
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional

from .classifier import ClassificationResult
from .config import Settings

# Windows reserved device names
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Illegal characters across file systems (< > : " / \ | ? *)
FORBIDDEN_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_component(name: str, max_length: int = 240) -> str:
    """Sanitize an individual filename or folder name component for safe cross-platform use."""
    # 1. Unicode normalization (NFC)
    clean = unicodedata.normalize("NFC", name)

    # 2. Replace forbidden characters with safe hyphen or space
    clean = FORBIDDEN_CHARS_PATTERN.sub("-", clean)

    # 3. Collapse multiple whitespace and hyphens
    clean = re.sub(r"\s+", " ", clean)
    clean = re.sub(r"-{2,}", "-", clean)

    # 4. Strip leading/trailing spaces, dots, and hyphens (vital for Windows / SMB)
    clean = clean.strip(" .-")

    if not clean:
        clean = "unnamed"

    # 5. Check Windows reserved words
    upper_base = clean.split(".")[0].upper()
    if upper_base in RESERVED_NAMES:
        clean = f"_{clean}"

    # 6. Truncate byte length for filesystem limits (e.g. 255 bytes on ext4/NTFS/ZFS)
    encoded = clean.encode("utf-8")
    if len(encoded) > max_length:
        parts = clean.rsplit(".", 1)
        if len(parts) == 2 and 1 <= len(parts[1]) <= 10:
            base, ext = parts
            ext_bytes = len(f".{ext}".encode("utf-8"))
            avail = max(max_length - ext_bytes, 10)
            base_enc = base.encode("utf-8")[:avail]
            base_clean = base_enc.decode("utf-8", errors="ignore").rstrip(" .-")
            clean = f"{base_clean}.{ext}" if base_clean else ext
        else:
            clean = encoded[:max_length].decode("utf-8", errors="ignore").rstrip(" .-")

    clean = clean.strip(" .-")
    return clean if clean else "unnamed"


DEFAULT_TEMPLATES = {
    "tv": "{title}/Season {season:02d}/{show_name}_{season_episode}.{ext}",
    "movie": "{title} ({year})/{movie_name}.{ext}",
    "anime": "{title}/Season {season:02d}/{show_name}_{season_episode} [{group}].{ext}",
}


class MediaNamer:
    """Renders organized destination paths from templates and classification results."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def generate_destination_path(
        self,
        cls_result: ClassificationResult,
        primary_dst_path: Optional[Path] = None,
    ) -> Path:
        """Construct full destination path for a given file and its classification."""
        category = cls_result.category
        base_dir = self.settings.get_destination_path(category)
        src_path = cls_result.metadata.path if cls_result.metadata else Path("unknown")
        ext = src_path.suffix.lstrip(".")

        # Handle Quarantine routing
        if cls_result.needs_quarantine or category == "unknown":
            reason = cls_result.quarantine_reason or "low_confidence"
            safe_reason = sanitize_filename_component(reason)
            q_template = self.settings.templates.quarantine
            filename = sanitize_filename_component(src_path.name)
            rel_str = q_template.format(reason=safe_reason, filename=filename, ext=ext)
            return (self.settings.get_destination_path("quarantine") / rel_str).resolve()

        # Handle Sidecars (Subtitles, Artwork, Metadata, Extras)
        if category in ("subtitle", "artwork", "metadata"):
            return self._format_sidecar_path(cls_result, primary_dst_path, base_dir)

        # Retrieve template
        template = getattr(self.settings.templates, category, None)
        context = self._build_context(cls_result)

        if category == "tv" and (not template or template == DEFAULT_TEMPLATES.get("tv")):
            formatted_rel = self._format_tv_path(cls_result, context)
        elif category == "movie" and (not template or template == DEFAULT_TEMPLATES.get("movie")):
            formatted_rel = self._format_movie_path(cls_result, context)
        elif category == "anime" and (not template or template == DEFAULT_TEMPLATES.get("anime")):
            formatted_rel = self._format_anime_path(cls_result, context)
        elif category == "podcast" and (not template or template == "{show}/{year}/{show} - {date} - {title}.{ext}"):
            formatted_rel = self._format_podcast_path(cls_result, context)
        else:
            if not template:
                template = "{filename}.{ext}"
            formatted_rel = self._render_template(template, context)

        # If file renaming is disabled, preserve original source filename
        if not getattr(self.settings.general, "rename_files", True) and src_path.name != "unknown":
            rel_path = Path(formatted_rel)
            if len(rel_path.parts) > 1:
                formatted_rel = str(rel_path.parent / src_path.name)
            else:
                formatted_rel = src_path.name

        # Sanitize each path component separately to preserve folder hierarchy
        parts = Path(formatted_rel).parts
        sanitized_parts = [sanitize_filename_component(p) for p in parts]
        return (base_dir / Path(*sanitized_parts)).resolve()

    def _format_tv_path(self, cls_result: ClassificationResult, context: Dict[str, Any]) -> str:
        show_name = context["show_name"]
        ext = context["ext"]
        tokens = cls_result.tokens

        # Daily / dated broadcast TV formatting
        date_val = context.get("date_val")
        if (tokens and tokens.is_daily) or (date_val and (not tokens or not tokens.season or tokens.season > 1000)):
            year = context.get("year")
            if not year or year == "Unknown":
                year = date_val.split("-")[0] if date_val else "Unknown"
            return f"{show_name}/Season {year}/{show_name} - {date_val}.{ext}"

        # Standard TV formatting (supporting Season 00, multi-ep, and season pack)
        season_num = context["season"]
        season_folder = f"Season {season_num:02d}"
        season_episode = context["season_episode"]
        return f"{show_name}/{season_folder}/{show_name} - {season_episode}.{ext}"

    def _format_movie_path(self, cls_result: ClassificationResult, context: Dict[str, Any]) -> str:
        title = context["title"]
        year = context["year"]
        ext = context["ext"]
        has_year = year and year != "Unknown"
        folder_name = f"{title} ({year})" if has_year else title
        base_name = f"{title} ({year})" if has_year else title

        edition_tag = context.get("edition_tag", "")
        part_tag = context.get("part_tag", "")
        extra_tag = context.get("extra_tag", "")
        return f"{folder_name}/{base_name}{edition_tag}{part_tag}{extra_tag}.{ext}"

    def _format_anime_path(self, cls_result: ClassificationResult, context: Dict[str, Any]) -> str:
        title = context["title"]
        ext = context["ext"]
        tokens = cls_result.tokens
        group_tag = context.get("group_tag", "")

        # Multi-episode anime
        if tokens and tokens.multi_episodes and len(tokens.multi_episodes) >= 2:
            first_ep = tokens.multi_episodes[0]
            last_ep = tokens.multi_episodes[-1]
            ep_str = f"{first_ep:02d}-{last_ep:02d}"
            return f"{title}/{title} - {ep_str}{group_tag}.{ext}"

        # Single episode anime
        if tokens and tokens.episode is not None:
            ep = tokens.episode
            ep_str = f"{ep:02d}" if ep < 10 else str(ep)
            return f"{title}/{title} - {ep_str}{group_tag}.{ext}"

        # Anime movie or special without episode number
        return f"{title}/{title}{group_tag}.{ext}"

    def _format_podcast_path(self, cls_result: ClassificationResult, context: Dict[str, Any]) -> str:
        show = context.get("show") or context.get("artist") or "Unknown Show"
        year = context.get("year")
        date = context.get("date")
        title = context.get("title")
        ext = context.get("ext")
        if title and title != show and title != "Unknown":
            return f"{show}/{year}/{show} - {date} - {title}.{ext}"
        return f"{show}/{year}/{show} - {date}.{ext}"

    def _format_sidecar_path(
        self,
        cls_result: ClassificationResult,
        primary_dst_path: Optional[Path],
        base_dir: Path,
    ) -> Path:
        src_path = cls_result.metadata.path
        ext = src_path.suffix.lstrip(".")

        if primary_dst_path:
            parent_dir = primary_dst_path.parent
            primary_stem = primary_dst_path.stem

            if cls_result.category == "subtitle":
                # Detect language code or compound tag in subtitle (e.g. movie.en.srt, movie.forced.srt)
                src_stem = src_path.stem
                m = re.search(
                    r"\.((?:[a-zA-Z]{2,3}\.)?(?:forced|sdh|cc)|[a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?)$",
                    src_stem,
                    re.IGNORECASE,
                )
                if m:
                    lang_suffix = f".{m.group(1)}"
                else:
                    parts = src_stem.split(".")
                    if len(parts) > 1 and len(parts[-1]) in (2, 3, 6):
                        lang_suffix = f".{parts[-1]}"
                    else:
                        lang_suffix = ""
                new_filename = f"{primary_stem}{lang_suffix}.{ext}"
                return parent_dir / sanitize_filename_component(new_filename)

            elif cls_result.category == "artwork":
                # e.g. poster.jpg, cover.jpg in the same movie/show folder
                return parent_dir / sanitize_filename_component(src_path.name)

            elif cls_result.category == "metadata":
                # NFO file matches primary stem or stays alongside
                new_filename = f"{primary_stem}.{ext}"
                return parent_dir / sanitize_filename_component(new_filename)

        # If orphan sidecar (no primary matched), place into respective folder
        sanitized_name = sanitize_filename_component(src_path.name)
        return (base_dir / sanitized_name).resolve()

    def _build_context(self, res: ClassificationResult) -> Dict[str, Any]:
        tokens = res.tokens
        meta = res.metadata
        src_path = meta.path if meta else Path("file")

        # Fix Season 00 / Episode 00 falsy bug
        season_num = tokens.season if (tokens and tokens.season is not None) else 1
        episode_num = tokens.episode if (tokens and tokens.episode is not None) else 1

        # Format season_episode string with multi-episode and season pack support
        if tokens and tokens.multi_episodes and len(tokens.multi_episodes) >= 2:
            season_ep_str = f"S{season_num:02d}E{tokens.multi_episodes[0]:02d}-E{tokens.multi_episodes[-1]:02d}"
        elif tokens and (tokens.is_season_pack or (tokens.season is not None and tokens.episode is None and not getattr(tokens, "multi_episodes", None))):
            season_ep_str = f"Season {season_num:02d}"
        else:
            season_ep_str = f"S{season_num:02d}E{episode_num:02d}"

        main_title = (tokens.title if tokens else None) or src_path.stem

        # Clean release group: omit when unknown, NEVER emit 'UnknownGroup'
        group_val = tokens.group if (tokens and tokens.group and tokens.group != "UnknownGroup") else ""
        group_tag = f" [{group_val}]" if group_val else ""

        # Extract movie edition, part, and extra tags
        edition_val = getattr(tokens, "edition", None) if tokens else None
        if not edition_val:
            em = re.search(r"\b(extended|directors?\.cut|remastered|criterion(?:\.collection)?|final\.cut)\b", src_path.stem, re.I)
            if em:
                raw_ed = em.group(1).lower().replace(".", " ")
                if "director" in raw_ed:
                    edition_val = "Director's Cut"
                elif "criterion" in raw_ed:
                    edition_val = "Criterion"
                elif "final" in raw_ed:
                    edition_val = "Final Cut"
                elif "remaster" in raw_ed:
                    edition_val = "Remastered"
                elif "extend" in raw_ed:
                    edition_val = "Extended"

        edition_tag = f" [{edition_val}]" if edition_val else ""

        part_val = getattr(tokens, "part", None) if tokens else None
        part_label = getattr(tokens, "part_label", None) if tokens else None
        if part_val is None:
            pm = re.search(r"\b(?:cd|part|pt)[\.\s_-]*(\d+)\b", src_path.stem, re.I)
            if pm:
                part_val = int(pm.group(1))
                part_label = f"Pt.{part_val}"
        elif not part_label:
            part_label = f"Pt.{part_val}"

        part_tag = f" [{part_label}]" if part_label else ""

        extra_m = re.search(r"-(behindthescenes|deleted|trailer|featurette)\b", src_path.stem, re.I)
        extra_tag = f"-{extra_m.group(1).lower()}" if extra_m else ""

        # Date resolution for daily TV shows and podcasts
        date_val = getattr(tokens, "air_date", None) or (tokens.date_stamp if tokens and not tokens.is_photo_or_home_video else None)
        if not date_val:
            dm = re.search(r"\b((?:19|20)\d{2})[-._](0[1-9]|1[0-2])[-._](0[1-9]|[12]\d|3[01])\b", src_path.stem)
            if dm:
                date_val = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"

        ctx: Dict[str, Any] = {
            "ext": src_path.suffix.lstrip("."),
            "filename": src_path.stem,
            "title": main_title,
            "show_name": main_title,
            "SHOW_NAME": main_title,
            "movie_name": main_title,
            "MOVIE_NAME": main_title,
            "season_episode": season_ep_str,
            "SEASON_EPISODE": season_ep_str,
            "year": (tokens.year if tokens else None) or "Unknown",
            "season": season_num,
            "episode": episode_num,
            "episode_title": (tokens.episode_title if tokens else None) or f"Episode {episode_num}",
            "artist": (tokens.artist if tokens else None) or "Unknown Artist",
            "album": (tokens.album if tokens else None) or "Unknown Album",
            "track": (tokens.track if tokens else 1) or 1,
            "disc": (tokens.disc if tokens else 1) or 1,
            "group": group_val,
            "group_tag": group_tag,
            "edition": edition_val,
            "edition_tag": edition_tag,
            "part": part_val,
            "part_label": part_label,
            "part_tag": part_tag,
            "extra_tag": extra_tag,
            "date_val": date_val,
            "resolution": (tokens.resolution if tokens and tokens.resolution else (meta.resolution_label if meta else "")),
            "codec": (tokens.video_codec or (meta.codec_video if meta else "h264")),
            "author": (tokens.artist if tokens else None) or "Unknown Author",
            "chapter": (tokens.title if tokens else None) or f"Chapter {tokens.track if tokens else 1}",
            "show": (tokens.artist if tokens else None) or "Unknown Show",
            "date": date_val or ((tokens.date_stamp if tokens else "2026-01-01") or "2026-01-01"),
            "month": 1,
            "day": 1,
            "time": "000000",
            "camera": "Camera",
            "event": "Event",
        }

        # Override from provider result if available
        if res.provider_result:
            p = res.provider_result
            if p.canonical_title:
                ctx["title"] = p.canonical_title
                ctx["show_name"] = p.canonical_title
                ctx["SHOW_NAME"] = p.canonical_title
                ctx["movie_name"] = p.canonical_title
                ctx["MOVIE_NAME"] = p.canonical_title
            if p.year:
                ctx["year"] = p.year
            if p.episode_title:
                ctx["episode_title"] = p.episode_title
            if p.artist:
                ctx["artist"] = p.artist
            if p.album:
                ctx["album"] = p.album

        # Parse date stamp fields if present
        date_source = (tokens and tokens.date_stamp) or (ctx.get("date") if res.category in ("home_video", "photo", "podcast") else None)
        if date_source and date_source != "Unknown":
            date_parts = str(date_source).split("-")
            if len(date_parts) == 3:
                try:
                    if ctx["year"] == "Unknown":
                        ctx["year"] = int(date_parts[0])
                    ctx["month"] = int(date_parts[1])
                    ctx["day"] = int(date_parts[2])
                except ValueError:
                    pass

        # Clean tags from meta
        if meta and meta.tags:
            if "camera_model" in meta.tags:
                ctx["camera"] = sanitize_filename_component(meta.tags["camera_model"])
            if "album" in meta.tags and not ctx.get("album"):
                ctx["album"] = meta.tags["album"]
            if "artist" in meta.tags and not ctx.get("artist"):
                ctx["artist"] = meta.tags["artist"]

        return ctx

    def _render_template(self, template: str, context: Dict[str, Any]) -> str:
        """Format template while gracefully cleaning empty technical brackets."""
        # Normalize <TAG> to {TAG} for convenience if users use angle brackets
        rendered = re.sub(r"<([a-zA-Z_0-9]+)>", r"{\1}", template)
        try:
            rendered = rendered.format(**context)
        except (KeyError, ValueError):
            # Safe token replacement if format specifier fails
            safe_ctx = {k: str(v) if v is not None else "" for k, v in context.items()}
            # Remove format specifiers like :02d
            simplified = re.sub(r"\{(\w+):[^}]+\}", r"{\1}", rendered)
            try:
                rendered = simplified.format(**safe_ctx)
            except Exception:
                rendered = f"{context.get('title', 'media')}.{context.get('ext', 'bin')}"

        # Clean empty technical brackets such as "[]" or "[  ]" or "()"
        rendered = re.sub(r"\[\s*\]", "", rendered)
        rendered = re.sub(r"\(\s*\)", "", rendered)
        rendered = re.sub(r"\s{2,}", " ", rendered)
        return rendered.strip()
