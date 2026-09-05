"""Filesystem discovery and scanning engine for Media Sorter.

Efficiently traverses directories, enforces minimum file age checks (to prevent
processing files currently being written/downloaded), tests file locks, and detects
companion/sidecar files.
"""

from __future__ import annotations

import fnmatch
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Generator, List, Optional, Set, Tuple

import structlog

logger = structlog.get_logger(__name__)

# Known sidecar and companion extensions
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"}
ARTWORK_NAMES = {"poster", "cover", "folder", "fanart", "banner", "clearart", "disc", "logo"}
ARTWORK_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tbn"}
METADATA_EXTS = {".nfo", ".xml", ".json"}
EXTRA_TAGS = {"-trailer", "-sample", "-featurette", "-behindthescenes", "-deleted", "-short"}


@dataclass
class ScannedFile:
    path: Path
    size: int
    mtime: float
    is_sidecar: bool = False
    sidecar_type: Optional[str] = None  # "subtitle", "artwork", "metadata", "extra"
    primary_media_path: Optional[Path] = None
    tags: Dict[str, str] = field(default_factory=dict)


def is_file_locked(path: Path) -> bool:
    """Test whether a file is currently open/locked for writing by another process."""
    if not path.is_file():
        return False

    try:
        # On Windows, try opening with exclusive read/write sharing if possible
        if sys.platform == "win32":
            import msvcrt
            handle = open(path, "rb")
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                handle.close()
        else:
            import fcntl
            with open(path, "rb") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return False
    except (IOError, OSError, PermissionError):
        return True


class Scanner:
    def __init__(
        self,
        min_file_age_seconds: int = 300,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
    ):
        self.min_file_age_seconds = min_file_age_seconds
        self.include_patterns = include_patterns or ["*"]
        self.exclude_patterns = exclude_patterns or [
            ".*",
            "*.part",
            "*.crdownload",
            "*.!qB",
            "Thumbs.db",
            "desktop.ini",
            "@eaDir",
            "$RECYCLE.BIN",
            "*.txt",
        ]

    def _matches_filter(self, filename: str) -> bool:
        """Check whether filename matches includes and does not match excludes."""
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(filename, pattern):
                return False
            if fnmatch.fnmatch(filename.lower(), pattern.lower()):
                return False

        if not self.include_patterns or "*" in self.include_patterns:
            return True

        for pattern in self.include_patterns:
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(filename.lower(), pattern.lower()):
                return True

        return False

    def scan_directory(self, root_dir: Path | str) -> List[ScannedFile]:
        """Recursively scan a directory returning all qualifying files."""
        root = Path(root_dir).resolve()
        if not root.exists():
            logger.warning("Source directory does not exist", directory=str(root))
            return []

        now = time.time()
        discovered: List[ScannedFile] = []
        video_candidates: List[ScannedFile] = []
        potential_sidecars: List[ScannedFile] = []

        for entry_path in self._walk_safe(root):
            try:
                stat = entry_path.stat()
            except (OSError, PermissionError) as e:
                logger.warning("Skipping inaccessible file", path=str(entry_path), error=str(e))
                continue

            # Minimum file age check: ignore recently modified files (e.g. active downloads)
            file_age = now - stat.st_mtime
            if file_age < self.min_file_age_seconds:
                logger.debug(
                    "Skipping file: modified too recently",
                    path=str(entry_path),
                    age_seconds=int(file_age),
                    min_age_seconds=self.min_file_age_seconds,
                )
                continue

            # Check if locked
            if is_file_locked(entry_path):
                logger.debug("Skipping file: currently locked by another process", path=str(entry_path))
                continue

            ext = entry_path.suffix.lower()
            stem = entry_path.stem.lower()

            scanned = ScannedFile(
                path=entry_path,
                size=stat.st_size,
                mtime=stat.st_mtime,
            )

            # Classify sidecar vs primary candidate
            if ext in SUBTITLE_EXTS:
                scanned.is_sidecar = True
                scanned.sidecar_type = "subtitle"
                potential_sidecars.append(scanned)
            elif ext in ARTWORK_EXTS and any(stem == art or stem.startswith(f"{art}.") for art in ARTWORK_NAMES):
                scanned.is_sidecar = True
                scanned.sidecar_type = "artwork"
                potential_sidecars.append(scanned)
            elif ext in METADATA_EXTS:
                scanned.is_sidecar = True
                scanned.sidecar_type = "metadata"
                potential_sidecars.append(scanned)
            elif any(stem.endswith(tag) for tag in EXTRA_TAGS):
                scanned.is_sidecar = True
                scanned.sidecar_type = "extra"
                potential_sidecars.append(scanned)
            else:
                discovered.append(scanned)
                if ext in {".mp4", ".mkv", ".m4v", ".avi", ".mov", ".ts", ".webm"}:
                    video_candidates.append(scanned)

        # Pair sidecars with primary files in the same directory
        self._pair_sidecars(potential_sidecars, video_candidates, discovered)
        return discovered

    def _walk_safe(self, root: Path) -> Generator[Path, None, None]:
        """Safely traverse directories using os.scandir with cycle and permission handling."""
        visited_inodes: Set[Tuple[int, int]] = set()
        stack = [root]

        while stack:
            curr = stack.pop()
            try:
                with os.scandir(curr) as it:
                    for entry in it:
                        try:
                            # Avoid symlink loops
                            if entry.is_symlink():
                                continue

                            if entry.is_dir():
                                if not self._matches_filter(entry.name):
                                    continue
                                stat = entry.stat()
                                dev_ino = (stat.st_dev, stat.st_ino)
                                if dev_ino in visited_inodes:
                                    continue
                                visited_inodes.add(dev_ino)
                                stack.append(Path(entry.path))
                            elif entry.is_file():
                                if self._matches_filter(entry.name):
                                    yield Path(entry.path)
                        except (OSError, PermissionError) as e:
                            logger.debug("Failed reading entry", path=entry.path, error=str(e))
            except (OSError, PermissionError) as e:
                logger.warning("Failed traversing directory", path=str(curr), error=str(e))

    def _pair_sidecars(
        self,
        sidecars: List[ScannedFile],
        primaries: List[ScannedFile],
        all_discovered: List[ScannedFile],
    ) -> None:
        """Associate sidecar files (subtitles, artwork, nfo) with primary media files."""
        # Index primaries by parent dir and stem
        primaries_by_dir: Dict[Path, List[ScannedFile]] = {}
        for p in primaries:
            primaries_by_dir.setdefault(p.path.parent, []).append(p)

        for s in sidecars:
            parent = s.path.parent
            candidates = primaries_by_dir.get(parent, [])

            # Check if any primary file stem is a prefix of the sidecar stem
            matched_primary = None
            s_stem = s.path.stem.lower()

            for c in candidates:
                c_stem = c.path.stem.lower()
                if s_stem == c_stem or s_stem.startswith(c_stem):
                    matched_primary = c
                    break

            if matched_primary:
                s.primary_media_path = matched_primary.path

            all_discovered.append(s)
