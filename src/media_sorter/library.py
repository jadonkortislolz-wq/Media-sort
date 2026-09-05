"""Library management and show/movie memory indexing engine.

Tracks known shows and movies in the library, syncs filesystem library directories,
and provides automatic show memory routing for incoming downloads.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy.orm import Session

from .config import Settings
from .models import LibraryItem, utc_now

logger = structlog.get_logger(__name__)

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts", ".flv", ".wmv"}


def clean_show_title(raw: str) -> str:
    """Strip release tags, quality, year suffixes, and bracketed text from a directory name."""
    clean = re.sub(r"\[[^\]]+\]|\([^\)]+\)", "", raw).strip()
    # Strip trailing quality / encoding specs
    clean = re.sub(
        r"(?i)\b(1080p|720p|2160p|4k|bluray|bdrip|webrip|web-dl|x264|x265|hevc|h\.?264|h\.?265|dts|aac|ac3|remux|repack)\b.*",
        "",
        clean,
    )
    # Strip Season pack identifiers like S01-S08 or Season 1
    clean = re.sub(r"(?i)\b(?:s\d+[-_s\d]*|season\s*\d+.*)\b", "", clean)
    clean = re.sub(r"[\._]+", " ", clean).strip(" -_")
    return clean if len(clean) >= 2 else raw.strip()


def sync_library_from_disk(session: Session, settings: Settings) -> Dict[str, int]:
    """Scan configured SHOWS_DIR and MOVIES_DIR on disk and synchronize library_items."""
    shows_dir = settings.get_destination_path("tv")
    movies_dir = settings.get_destination_path("movie")

    shows_count = 0
    movies_count = 0

    # Cache existing records in memory by (title.lower(), category)
    existing_items: Dict[Tuple[str, str], LibraryItem] = {
        (item.title.lower(), item.category): item for item in session.query(LibraryItem).all()
    }

    # 1. Scan Shows Directory
    if shows_dir.exists() and shows_dir.is_dir():
        try:
            for entry in shows_dir.iterdir():
                if entry.name.startswith(".") or not entry.is_dir():
                    continue

                folder_name = entry.name
                title = clean_show_title(folder_name)
                if not title:
                    continue

                # Count video files and detect seasons
                episodes = 0
                seasons = set()
                try:
                    for root, _, files in os.walk(entry):
                        for f in files:
                            ext = os.path.splitext(f)[1].lower()
                            if ext in VIDEO_EXTENSIONS:
                                episodes += 1
                                s_m = re.search(r"(?i)\b(?:season|s)\s*(\d{1,2})\b", Path(root).name)
                                if s_m:
                                    seasons.add(int(s_m.group(1)))
                except Exception:
                    pass

                key = (title.lower(), "tv")
                if key in existing_items:
                    item = existing_items[key]
                    item.destination_folder = str(entry)
                    item.item_count = max(item.item_count, episodes)
                    item.seasons_count = max(item.seasons_count, len(seasons))
                    item.last_updated = utc_now()
                else:
                    item = LibraryItem(
                        title=title,
                        category="tv",
                        destination_folder=str(entry),
                        item_count=episodes,
                        seasons_count=len(seasons),
                        first_detected=utc_now(),
                        last_updated=utc_now(),
                    )
                    session.add(item)
                    existing_items[key] = item
                shows_count += 1
        except Exception as e:
            logger.error("Error scanning shows directory for library", error=str(e))

    # 2. Scan Movies Directory
    if movies_dir.exists() and movies_dir.is_dir():
        try:
            for entry in movies_dir.iterdir():
                if entry.name.startswith("."):
                    continue

                title = entry.name
                year = None
                y_m = re.search(r"\b(19\d\d|20\d\d)\b", entry.name)
                if y_m:
                    year = int(y_m.group(1))
                    title = entry.name[: y_m.start()].strip(" (.-_")

                clean = clean_show_title(title)
                item_files = 1
                if entry.is_dir():
                    try:
                        item_files = sum(
                            1 for _, _, files in os.walk(entry)
                            for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
                        )
                    except Exception:
                        pass

                key = (clean.lower(), "movie")
                if key in existing_items:
                    item = existing_items[key]
                    item.destination_folder = str(entry)
                    item.year = year or item.year
                    item.item_count = max(item.item_count, item_files)
                    item.last_updated = utc_now()
                else:
                    item = LibraryItem(
                        title=clean,
                        category="movie",
                        year=year,
                        destination_folder=str(entry),
                        item_count=item_files,
                        first_detected=utc_now(),
                        last_updated=utc_now(),
                    )
                    session.add(item)
                    existing_items[key] = item
                movies_count += 1
        except Exception as e:
            logger.error("Error scanning movies directory for library", error=str(e))

    session.commit()
    logger.info("Library synchronized with disk", shows=shows_count, movies=movies_count)
    return {"shows_synced": shows_count, "movies_synced": movies_count}


def record_detected_item(
    session: Session,
    settings: Settings,
    title: str,
    category: str,
    destination_folder: Optional[str] = None,
    year: Optional[int] = None,
    poster_url: Optional[str] = None,
    delta_count: int = 0,
) -> LibraryItem:
    """Record or update a show or movie in the library database."""
    category = category.lower()
    if category not in ("tv", "movie"):
        category = "tv"

    clean = clean_show_title(title) if category == "tv" else title.strip()
    item = session.query(LibraryItem).filter_by(title=clean, category=category).first()

    if not destination_folder:
        dest_base = settings.get_destination_path(category)
        destination_folder = str(dest_base / clean)

    if item:
        if destination_folder:
            item.destination_folder = destination_folder
        if year:
            item.year = year
        if poster_url and not item.poster_url:
            item.poster_url = poster_url
        if delta_count:
            item.item_count = max(0, item.item_count + delta_count)
        item.last_updated = utc_now()
    else:
        item = LibraryItem(
            title=clean,
            category=category,
            year=year,
            destination_folder=destination_folder,
            poster_url=poster_url,
            item_count=max(0, delta_count),
            first_detected=utc_now(),
            last_updated=utc_now(),
        )
        session.add(item)

    session.commit()
    return item


def get_known_shows(session: Session) -> List[Dict[str, Any]]:
    """Return all known TV shows in the library for matching."""
    items = session.query(LibraryItem).filter_by(category="tv").all()
    shows = []
    for item in items:
        clean = item.title.strip()
        if len(clean) >= 2:
            shows.append({
                "title": clean,
                "raw_title": item.title,
                "destination_folder": item.destination_folder,
                "poster_url": item.poster_url,
                "item_count": item.item_count,
            })
    # Sort by title length descending so longer specific titles match first
    shows.sort(key=lambda x: len(x["title"]), reverse=True)
    return shows


def match_known_show(filename_or_text: str, known_shows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Check if filename_or_text contains or matches a known show in the library."""
    if not filename_or_text or not known_shows:
        return None

    # Replace separators with spaces
    normalized = re.sub(r"[\._]+", " ", filename_or_text)

    for show in known_shows:
        title = show["title"]
        if len(title) < 3:
            continue

        # Check whole word match
        pattern = r"(?i)(?<![a-z0-9])" + re.escape(title) + r"(?![a-z0-9])"
        if re.search(pattern, normalized):
            return show

    return None


def list_library_items(
    session: Session,
    category: Optional[str] = None,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """List library items with counts, optionally filtered by category and search term."""
    q = session.query(LibraryItem)
    if category and category.lower() in ("tv", "movie"):
        q = q.filter_by(category=category.lower())

    if search:
        s = f"%{search.strip()}%"
        q = q.filter(LibraryItem.title.ilike(s))

    items = q.order_by(LibraryItem.title.asc()).all()

    total_shows = session.query(LibraryItem).filter_by(category="tv").count()
    total_movies = session.query(LibraryItem).filter_by(category="movie").count()

    shows_list = []
    movies_list = []

    for item in items:
        d = {
            "id": item.id,
            "title": item.title,
            "category": item.category,
            "year": item.year,
            "destination_folder": item.destination_folder,
            "poster_url": item.poster_url,
            "item_count": item.item_count,
            "seasons_count": item.seasons_count,
            "first_detected": item.first_detected.isoformat() if item.first_detected else None,
            "last_updated": item.last_updated.isoformat() if item.last_updated else None,
        }
        if item.category == "tv":
            shows_list.append(d)
        else:
            movies_list.append(d)

    return {
        "total_shows": total_shows,
        "total_movies": total_movies,
        "shows": shows_list,
        "movies": movies_list,
    }
