"""Web dashboard and REST API service for Media Sorter.

Provides an interactive browser interface for organizing downloads into movies and shows,
managing .env settings, browsing file directories, resolving quarantined media, and executing
instant rollbacks.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
import re
import shutil
import sys
import time
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from .config import ActionType, Settings
from .db import get_db_session, init_db
from . import __version__
from .models import BatchRecord, Operation, QuarantineRecord, QuarantineStatus
from .quarantine import QuarantineManager
from .sorter import MediaSorterApp
from .tokenizer import FilenameTokenizer

logger = structlog.get_logger(__name__)


class RunRequest(BaseModel):
    dry_run: Optional[bool] = None


class RollbackRequest(BaseModel):
    batch_id: Optional[str] = None


class ResolveRequest(BaseModel):
    category: str
    target_path: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None


class BulkResolveRequest(BaseModel):
    category: str
    item_ids: Optional[List[int]] = None
    target_path: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None


class BulkUndoRequest(BaseModel):
    item_ids: Optional[List[int]] = None
    scope: str = "pending"  # "pending" or "resolved"



class ManualSortRequest(BaseModel):
    relative_path: str
    category: str
    title: str
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None


class SortShowRequest(BaseModel):
    show_name: str
    target_destination: Optional[str] = None
    relative_paths: Optional[List[str]] = None
    dry_run: bool = False


class SortGroupRequest(BaseModel):
    group_name: str
    group_type: str = "folder"
    category: Optional[str] = "tv"
    title: Optional[str] = None
    year: Optional[int] = None
    relative_paths: List[str]
    dry_run: bool = False


class SettingsUpdateRequest(BaseModel):
    downloads_dir: Optional[str] = None
    movies_dir: Optional[str] = None
    shows_dir: Optional[str] = None
    dry_run: Optional[bool] = None
    confidence_threshold: Optional[float] = None
    min_file_age_seconds: Optional[int] = None
    scan_interval_seconds: Optional[int] = None
    action: Optional[str] = None
    cleanup_empty_dirs: Optional[bool] = None
    rename_files: Optional[bool] = None
    movie_template: Optional[str] = None
    tv_template: Optional[str] = None


def format_bytes(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def list_files_in_dir(directory: Path) -> List[Dict[str, Any]]:
    items = []
    if not directory.exists():
        return items

    for root, _, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(".txt"):
                continue
            p = Path(root) / f
            try:
                st = p.stat()
                rel = p.relative_to(directory)
                items.append({
                    "name": f,
                    "relative_path": str(rel),
                    "size": format_bytes(st.st_size),
                    "size_bytes": st.st_size,
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                })
            except Exception:
                pass
    return sorted(items, key=lambda x: x["name"].lower())


def clean_detected_show_name(n: str) -> str:
    if not n:
        return ""
    m = re.match(r"^\s*\[([^\]]+)\]\s*(.+)$", n)
    if m and any(c.isalpha() for c in m.group(2)):
        n = m.group(2)
    n = re.sub(r"[\._]+", " ", n)
    n = re.sub(r"(?i)\b(complete|season\s*\d+|s\d+|batch|dual\s*audio|hevc|1080p|bdrip|webrip)\b.*", "", n)
    return n.strip(" -()[]")


POSTER_CACHE_FILE = Path("media_sorter_posters.json")
_POSTER_CACHE: Dict[str, Optional[str]] = {}


def load_poster_cache() -> None:
    global _POSTER_CACHE
    if POSTER_CACHE_FILE.exists():
        try:
            with open(POSTER_CACHE_FILE, "r", encoding="utf-8") as f:
                _POSTER_CACHE = json.load(f)
        except Exception:
            _POSTER_CACHE = {}


def save_poster_cache() -> None:
    try:
        with open(POSTER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_POSTER_CACHE, f)
    except Exception:
        pass


load_poster_cache()


def fetch_show_poster(
    show_name: str,
    directory: Optional[Path] = None,
    show_files: Optional[List[Dict[str, Any]]] = None,
    allow_network: bool = True,
) -> Optional[str]:
    """Retrieves a poster image URL for a show, checking local files first then TVmaze."""
    if not show_name:
        return None

    cache_key = show_name.strip().lower()
    if cache_key in _POSTER_CACHE:
        return _POSTER_CACHE[cache_key]

    # 1. Check for local artwork in the show's directory
    if directory and show_files:
        try:
            for sf in show_files[:5]:
                rel = sf.get("relative_path")
                if rel:
                    file_dir = directory / Path(rel).parent
                    if file_dir.exists() and file_dir.is_dir():
                        for img in file_dir.glob("*.*"):
                            if img.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                                stem = img.stem.lower()
                                if any(w in stem for w in ["poster", "cover", "folder", "banner", "front"]):
                                    local_url = f"/api/poster/local?path={urllib.parse.quote_plus(str(img.resolve()))}"
                                    _POSTER_CACHE[cache_key] = local_url
                                    save_poster_cache()
                                    return local_url
        except Exception:
            pass

    if not allow_network:
        return None

    # 2. Query TVmaze open API (no API key required)
    clean = clean_detected_show_name(show_name)
    headers = {"User-Agent": "MediaSorter/1.0"}

    # Try singlesearch first
    try:
        q = urllib.parse.quote_plus(clean)
        url = f"https://api.tvmaze.com/singlesearch/shows?q={q}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                img = data.get("image")
                if img and (img.get("medium") or img.get("original")):
                    poster = img.get("medium") or img.get("original")
                    _POSTER_CACHE[cache_key] = poster
                    save_poster_cache()
                    return poster
    except Exception:
        pass

    # Try search list
    try:
        q = urllib.parse.quote_plus(clean)
        url = f"https://api.tvmaze.com/search/shows?q={q}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            if resp.status == 200:
                items = json.loads(resp.read().decode())
                for item in items:
                    img = item.get("show", {}).get("image")
                    if img and (img.get("medium") or img.get("original")):
                        poster = img.get("medium") or img.get("original")
                        _POSTER_CACHE[cache_key] = poster
                        save_poster_cache()
                        return poster
    except Exception:
        pass

    # Cache None to avoid repeated slow network queries
    _POSTER_CACHE[cache_key] = None
    save_poster_cache()
    return None


def extract_clean_stem(name: str) -> str:
    """Extract a normalized stem from filename for clustering."""
    stem = Path(name).stem
    stem = re.sub(r"\[[^\]]+\]|\([^\)]+\)", "", stem).strip()
    stem = re.sub(
        r"(?i)\b(2160p|1080p|1080i|720p|576p|480p|4k|bluray|blu-ray|bdrip|webrip|web-dl|web|hdtv|dvdrip|dvd|x264|x265|hevc|avc|av1|h\.?264|h\.?265|dts|aac|ac3|truehd|atmos|flac|remux|repack|part\s*\d+|cd\s*\d+|disc\s*\d+|special\s*\d*)\b.*",
        "",
        stem,
    )
    stem = re.sub(r"(?i)\b(?:e|ep|episode)?\s*\d{1,4}\b.*$", "", stem)
    stem = re.sub(r"[\._-]+", " ", stem).strip()
    return stem


def common_prefix_words(s1: str, s2: str) -> str:
    w1 = s1.split()
    w2 = s2.split()
    common = []
    for a, b in zip(w1, w2):
        if a.lower() == b.lower():
            common.append(a)
        else:
            break
    if len(common) >= 2 or (len(common) == 1 and len(common[0]) >= 5):
        res = " ".join(common).strip(" -_:,")
        if len(res) >= 3:
            return res
    return ""


def cluster_unsure_files(
    unsure_files: List[Dict[str, Any]], settings: Settings
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Group unsure files by shared subfolder or common name/prefix into dropdown groups."""
    if not unsure_files:
        return [], []

    shows_base = settings.get_destination_path("tv")

    # 1. Group by parent folder
    folder_map: Dict[str, List[Dict[str, Any]]] = {}
    root_files: List[Dict[str, Any]] = []

    for f in unsure_files:
        rel_str = f.get("relative_path", f["name"])
        rel_parts = Path(rel_str).parts
        if len(rel_parts) > 1:
            folder_key = rel_parts[0]
            folder_map.setdefault(folder_key, []).append(f)
        else:
            root_files.append(f)

    unsure_groups: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []

    # Subfolders with >= 2 files form a folder group
    for folder_name, fl in folder_map.items():
        if len(fl) >= 2:
            clean_title = clean_detected_show_name(folder_name)
            unsure_groups.append({
                "group_id": f"folder_{abs(hash(folder_name)) % 10000000}",
                "group_name": folder_name,
                "group_type": "folder",
                "folder_name": folder_name,
                "suggested_title": clean_title,
                "believed_destination_folder": str(shows_base / clean_title),
                "count": len(fl),
                "files": sorted(fl, key=lambda x: x["name"].lower()),
            })
        else:
            candidates.extend(fl)

    candidates.extend(root_files)

    # 2. Group by exact normalized stem
    assigned = set()
    stem_dict: Dict[str, List[Dict[str, Any]]] = {}
    for f in candidates:
        st = extract_clean_stem(f["name"])
        if len(st) >= 3:
            stem_dict.setdefault(st.lower(), []).append(f)

    for st_lower, fl in stem_dict.items():
        if len(fl) >= 2:
            display_name = clean_detected_show_name(fl[0]["name"])
            if not display_name or len(display_name) < 2:
                display_name = st_lower.title()
            unsure_groups.append({
                "group_id": f"name_{abs(hash(st_lower)) % 10000000}",
                "group_name": display_name,
                "group_type": "name",
                "folder_name": None,
                "suggested_title": display_name,
                "believed_destination_folder": str(shows_base / display_name),
                "count": len(fl),
                "files": sorted(fl, key=lambda x: x["name"].lower()),
            })
            for f in fl:
                assigned.add(f.get("relative_path", f["name"]))

    remaining = [f for f in candidates if f.get("relative_path", f["name"]) not in assigned]

    # 3. Cluster remaining files by common word prefix
    while remaining:
        current = remaining.pop(0)
        cluster = [current]
        best_prefix = ""
        c_stem = extract_clean_stem(current["name"])
        i = 0
        while i < len(remaining):
            other = remaining[i]
            o_stem = extract_clean_stem(other["name"])
            pref = common_prefix_words(c_stem, o_stem)
            if pref and len(pref) >= 4:
                cluster.append(other)
                if not best_prefix or len(pref) > len(best_prefix):
                    best_prefix = pref
                remaining.pop(i)
            else:
                i += 1

        if len(cluster) >= 2:
            disp = clean_detected_show_name(best_prefix) if best_prefix else c_stem
            unsure_groups.append({
                "group_id": f"prefix_{abs(hash(disp)) % 10000000}",
                "group_name": disp,
                "group_type": "name",
                "folder_name": None,
                "suggested_title": disp,
                "believed_destination_folder": str(shows_base / disp),
                "count": len(cluster),
                "files": sorted(cluster, key=lambda x: x["name"].lower()),
            })

    # All files in unsure_groups
    all_grouped_paths = {f.get("relative_path", f["name"]) for g in unsure_groups for f in g["files"]}
    singles = [f for f in unsure_files if f.get("relative_path", f["name"]) not in all_grouped_paths]

    unsure_groups.sort(key=lambda g: (-g["count"], g["group_name"].lower()))
    singles.sort(key=lambda x: x["name"].lower())

    return unsure_groups, singles


def inspect_downloads_folder(
    directory: Path,
    settings: Settings,
    engine: Optional[Engine] = None,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """Inspects downloads folder, categorizing files into shows, unsure groups, and singles."""
    from .tokenizer import FilenameTokenizer

    tok = FilenameTokenizer()
    all_files: List[Dict[str, Any]] = []
    show_map: Dict[str, List[Dict[str, Any]]] = {}
    unsure_candidates: List[Dict[str, Any]] = []

    if not directory.exists():
        return {
            "path": str(directory),
            "files": [],
            "shows": [],
            "unsure_groups": [],
            "singles": [],
            "total_files": 0,
        }

    shows_base = settings.get_destination_path("tv")
    movies_base = settings.get_destination_path("movie")

    known_shows: List[Dict[str, Any]] = []
    if session is not None:
        try:
            from .library import get_known_shows
            known_shows = get_known_shows(session)
        except Exception:
            pass
    elif engine is not None:
        try:
            from .db import get_db_session
            from .library import get_known_shows
            with get_db_session(engine) as sess:
                known_shows = get_known_shows(sess)
        except Exception:
            pass

    for root, _, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(".txt"):
                continue
            p = Path(root) / f
            try:
                st = p.stat()
                rel = p.relative_to(directory)
                t = tok.tokenize(p)

                # Check if the file itself has a year or if any parent folder has a year
                movie_year = t.year
                movie_title = t.title
                if not movie_year and not t.is_episodic and not t.is_anime:
                    for part in reversed(rel.parts[:-1]):
                        part_tok = tok.tokenize(Path(part + p.suffix))
                        if part_tok.year and not part_tok.is_episodic and not part_tok.is_anime:
                            movie_year = part_tok.year
                            if not movie_title or movie_title == p.stem:
                                movie_title = part_tok.title
                            break

                show_name = None
                # A file is a show if it has explicit episodic/anime markers
                if (t.is_episodic or t.is_anime) and t.title:
                    cleaned = clean_detected_show_name(t.title)
                    if len(cleaned) >= 2:
                        show_name = cleaned

                # If no show title from filename, check if parent directory is an explicit Season folder
                if not show_name:
                    for idx, part in enumerate(rel.parts[:-1]):
                        if re.search(r"(?i)\bseason\s*\d+\b|\bs\d{1,2}\b|\bseries\s*\d+\b", part):
                            if idx > 0:
                                show_name = clean_detected_show_name(rel.parts[idx - 1])
                            else:
                                show_name = clean_detected_show_name(part)
                            if t.season is None:
                                s_match = re.search(r"(?i)\b(?:season|s|series)\s*(\d{1,2})\b", part)
                                if s_match:
                                    t.season = int(s_match.group(1))
                            break

                # If the file has a release year and NO episodic markers, it is definitely a MOVIE!
                if movie_year and not t.is_episodic and t.season is None and t.episode is None:
                    show_name = None

                # Show memory matching: check known library shows
                if not show_name and known_shows:
                    from .library import match_known_show
                    m_show = match_known_show(p.name, known_shows)
                    if not m_show and len(rel.parts) > 1:
                        m_show = match_known_show(rel.parts[0], known_shows)
                    if m_show:
                        show_name = m_show["title"]

                file_info: Dict[str, Any] = {
                    "name": f,
                    "relative_path": str(rel),
                    "size": format_bytes(st.st_size),
                    "size_bytes": st.st_size,
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                    "season": t.season,
                    "episode": t.episode,
                    "episode_title": t.episode_title,
                    "is_show": bool(show_name),
                    "believed_show": show_name,
                }
                all_files.append(file_info)

                if show_name:
                    show_map.setdefault(show_name, []).append(file_info)
                else:
                    detected_type = "other"
                    believed_title = f
                    dest = None
                    is_video = p.suffix.lower() in [".mkv", ".mp4", ".avi", ".mov", ".m4v", ".webm", ".ts", ".flv"]
                    if movie_year:
                        detected_type = "movie"
                        cleaned_movie = clean_detected_show_name(movie_title if movie_title else p.stem)
                        believed_title = f"{cleaned_movie} ({movie_year})"
                        dest = str(movies_base / believed_title)
                    elif is_video:
                        detected_type = "movie"
                        cleaned_movie = clean_detected_show_name(t.title if t.title else p.stem)
                        believed_title = cleaned_movie
                        dest = str(movies_base / believed_title)

                    file_info["detected_type"] = detected_type
                    file_info["believed_title"] = believed_title
                    file_info["believed_destination"] = dest
                    unsure_candidates.append(file_info)
            except Exception:
                pass

    shows_list = []
    for s_name, s_files in show_map.items():
        sorted_files = sorted(
            s_files,
            key=lambda x: (
                x.get("season") if x.get("season") is not None else 0,
                x.get("episode") if x.get("episode") is not None else 0,
                x["name"].lower(),
            ),
        )
        seasons = sorted(list({f["season"] for f in sorted_files if f.get("season") is not None}))
        season_summary = ", ".join(f"Season {s:02d}" for s in seasons) if seasons else "Episodic Series"
        dest_folder = str(shows_base / s_name)
        poster_url = fetch_show_poster(s_name, directory=directory, show_files=sorted_files, allow_network=False)
        shows_list.append({
            "show_name": s_name,
            "count": len(sorted_files),
            "seasons": seasons,
            "season_summary": season_summary,
            "believed_destination_folder": dest_folder,
            "poster_url": poster_url,
            "files": sorted_files,
        })

    shows_list.sort(key=lambda x: (-x["count"], x["show_name"].lower()))
    all_files.sort(key=lambda x: x["name"].lower())

    # Cluster non-show files into unsure dropdown groups and singles
    unsure_groups, singles = cluster_unsure_files(unsure_candidates, settings)

    # Automatically record detected shows in library catalog
    if session is not None:
        try:
            from .library import record_detected_item
            for show_item in shows_list:
                record_detected_item(
                    session,
                    settings,
                    show_item["show_name"],
                    "tv",
                    destination_folder=show_item["believed_destination_folder"],
                    poster_url=show_item.get("poster_url"),
                    delta_count=show_item["count"],
                )
        except Exception:
            pass
    elif engine is not None:
        try:
            from .db import get_db_session
            from .library import record_detected_item
            with get_db_session(engine) as sess:
                for show_item in shows_list:
                    record_detected_item(
                        sess,
                        settings,
                        show_item["show_name"],
                        "tv",
                        destination_folder=show_item["believed_destination_folder"],
                        poster_url=show_item.get("poster_url"),
                        delta_count=show_item["count"],
                    )
        except Exception:
            pass

    return {
        "path": str(directory),
        "total_files": len(all_files),
        "files": all_files,
        "shows": shows_list,
        "unsure_groups": unsure_groups,
        "singles": singles,
    }


def create_app(
    settings: Settings,
    engine: Optional[Engine] = None,
    env_path: Path | str = ".env",
) -> FastAPI:
    if engine is None:
        engine = init_db(db_path=settings.get_database_path())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker_task = None

        async def auto_sort_worker():
            while True:
                interval = settings.general.scan_interval_seconds
                if interval > 0:
                    try:
                        sorter = MediaSorterApp(settings, engine)
                        sorter.run()
                    except Exception as e:
                        logger.error("Auto-sort background task error", error=str(e))
                await asyncio.sleep(max(interval, 10) if interval > 0 else 10)

        # Initial disk library synchronization in background
        def initial_library_sync():
            try:
                from .library import sync_library_from_disk
                with get_db_session(engine) as session:
                    sync_library_from_disk(session, settings)
            except Exception as e:
                logger.error("Initial library sync error", error=str(e))

        asyncio.get_running_loop().run_in_executor(None, initial_library_sync)

        worker_task = asyncio.create_task(auto_sort_worker())
        try:
            yield
        finally:
            if worker_task:
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Media Sorter Management", version="0.1.0", lifespan=lifespan)

    @app.get("/api/status")
    def get_status():
        with get_db_session(engine) as session:
            total_batches = session.query(BatchRecord).count()
            total_quarantine = (
                session.query(QuarantineRecord)
                .filter_by(status=QuarantineStatus.PENDING.value)
                .count()
            )
            downloads_dir = settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")
            movies_dir = settings.get_destination_path("movie")
            shows_dir = settings.get_destination_path("tv")

            return {
                "version": __version__,
                "status": "online",
                "database": str(settings.get_database_path()),
                "dry_run": settings.general.dry_run,
                "confidence_threshold": settings.general.confidence_threshold,
                "min_file_age_seconds": settings.general.min_file_age_seconds,
                "scan_interval_seconds": settings.general.scan_interval_seconds,
                "action": settings.general.action.value,
                "downloads_dir": str(downloads_dir),
                "movies_dir": str(movies_dir),
                "shows_dir": str(shows_dir),
                "total_batches": total_batches,
                "pending_quarantine": total_quarantine,
            }

    @app.get("/api/batches")
    def get_batches(limit: int = 20):
        with get_db_session(engine) as session:
            batches = (
                session.query(BatchRecord)
                .order_by(BatchRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": b.id,
                    "created_at": b.created_at.strftime("%Y-%m-%d %H:%M:%S") if b.created_at else None,
                    "completed_at": b.completed_at.strftime("%Y-%m-%d %H:%M:%S") if b.completed_at else None,
                    "dry_run": b.dry_run,
                    "status": b.status,
                    "total_files": b.total_files,
                    "moved_files": b.moved_files,
                    "quarantined_files": b.quarantined_files,
                    "skipped_files": b.skipped_files,
                    "failed_files": b.failed_files,
                }
                for b in batches
            ]

    @app.get("/api/batches/{batch_id}")
    def get_batch_detail(batch_id: str):
        with get_db_session(engine) as session:
            batch = session.query(BatchRecord).filter_by(id=batch_id).first()
            if not batch:
                raise HTTPException(status_code=404, detail="Batch not found")
            ops = session.query(Operation).filter_by(batch_id=batch_id).all()
            return {
                "batch": {
                    "id": batch.id,
                    "status": batch.status,
                    "dry_run": batch.dry_run,
                    "created_at": batch.created_at.isoformat() if batch.created_at else None,
                },
                "operations": [
                    {
                        "id": op.id,
                        "src": op.src,
                        "dst": op.dst,
                        "action": op.action,
                        "status": op.status,
                        "category": op.category,
                        "confidence": op.confidence,
                        "details": op.details,
                    }
                    for op in ops
                ],
            }

    @app.post("/api/batches/clear")
    def clear_batches_and_history():
        """Clear all batch records and operation logs from the database."""
        with get_db_session(engine) as session:
            session.query(Operation).delete()
            session.query(BatchRecord).delete()
            session.commit()
            return {"status": "cleared", "message": "Activity and batch history successfully cleared"}

    @app.post("/api/run")
    def trigger_run(req: RunRequest):
        """Execute sorter run (dry-run or live)."""
        sorter = MediaSorterApp(settings, engine)
        is_dry = settings.general.dry_run if req.dry_run is None else req.dry_run
        report = sorter.run(dry_run=is_dry)
        return {
            "batch_id": report.batch_id,
            "dry_run": report.dry_run,
            "total_files": report.total_files,
            "moved_files": report.moved_files,
            "quarantined_files": report.quarantined_files,
            "skipped_files": report.skipped_files,
            "failed_files": report.failed_files,
            "operations": [
                {
                    "src": str(op.src.name),
                    "dst": str(op.dst),
                    "action": op.action.value,
                    "category": op.category,
                    "confidence": int(op.confidence * 100),
                    "quarantine": op.quarantine,
                    "quarantine_reason": op.quarantine_reason,
                }
                for op in report.operations
            ],
            "errors": report.errors,
        }

    @app.post("/api/rollback")
    def trigger_rollback(req: RollbackRequest):
        """Roll back last batch or specified batch ID."""
        sorter = MediaSorterApp(settings, engine)
        reverted = sorter.rollback(batch_id=req.batch_id)
        return {"status": "ok", "reverted_files": reverted}

    @app.post("/api/rollback/all")
    def trigger_rollback_all():
        """Roll back all past completed batches."""
        sorter = MediaSorterApp(settings, engine)
        reverted = sorter.rollback_all()
        return {"status": "ok", "reverted_files": reverted}


    @app.get("/api/files")
    def get_files():
        """List files currently in downloads, movies, and shows directories."""
        downloads_path = settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")
        movies_path = settings.get_destination_path("movie")
        shows_path = settings.get_destination_path("tv")

        return {
            "downloads": inspect_downloads_folder(downloads_path, settings, engine=engine),
            "movies": {
                "path": str(movies_path),
                "files": list_files_in_dir(movies_path),
            },
            "shows": {
                "path": str(shows_path),
                "files": list_files_in_dir(shows_path),
            },
        }

    @app.post("/api/files/test-sample")
    def generate_test_samples():
        """Create sample media files in the downloads folder for quick interactive testing."""
        downloads_path = settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")
        downloads_path.mkdir(parents=True, exist_ok=True)

        samples = [
            ("Inception.2010.1080p.BluRay.x264.mkv", b"\x1aE\xdf\xa3" + b"\x00" * 300),
            ("Inception.2010.1080p.BluRay.x264.en.srt", b"1\n00:00:01,000 --> 00:00:04,000\nDreams feel real.\n"),
            ("Breaking.Bad.S01E01.Pilot.1080p.mkv", b"\x1aE\xdf\xa3" + b"\x00" * 300),
            ("Stranger.Things.S04E01.Chapter.One.720p.mkv", b"\x1aE\xdf\xa3" + b"\x00" * 300),
            ("Interstellar.2014.2160p.UHD.mkv", b"\x1aE\xdf\xa3" + b"\x00" * 300),
            ("ambiguous_unlabeled_clip.bin", b"\x00\x01\x02\x03\x04\x05"),
        ]

        created = []
        for name, data in samples:
            p = downloads_path / name
            p.write_bytes(data)
            created.append(name)

        return {"status": "created", "files": created, "directory": str(downloads_path)}

    @app.delete("/api/files/download")
    def delete_download_file(name: str):
        downloads_path = (settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")).resolve()
        target = (downloads_path / name).resolve()
        if not target.is_relative_to(downloads_path) or not target.is_file():
            found = None
            for root, _, files in os.walk(downloads_path):
                if name in files:
                    found = Path(root) / name
                    break
            if found and found.is_relative_to(downloads_path) and found.is_file():
                target = found
            else:
                raise HTTPException(status_code=404, detail="File not found")
        target.unlink()
        # Delete companion .txt file if present
        companion_txt = target.with_suffix(".txt")
        if companion_txt.is_file() and companion_txt != target:
            try:
                companion_txt.unlink()
            except Exception:
                pass

        # Clean up empty parent directories up to downloads_path
        parent = target.parent
        while parent != downloads_path and parent.is_relative_to(downloads_path):
            try:
                # Clean up any .txt files in parent directory
                for item in list(parent.iterdir()):
                    if item.is_file() and item.name.lower().endswith(".txt"):
                        try:
                            item.unlink()
                        except Exception:
                            pass

                entries = [
                    e for e in parent.iterdir()
                    if e.name not in (".DS_Store", "Thumbs.db", "desktop.ini") and not e.name.lower().endswith(".txt")
                ]
                if not entries:
                    for junk in parent.iterdir():
                        try:
                            junk.unlink()
                        except Exception:
                            pass
                    parent.rmdir()
                    parent = parent.parent
                else:
                    break
            except Exception:
                break
        return {"status": "deleted", "name": name}

    @app.get("/api/quarantine")
    def list_quarantine():
        with get_db_session(engine) as session:
            qm = QuarantineManager(session)
            items = qm.list_pending()
            resolved = qm.list_resolved(limit=30)
            return {
                "pending": [
                    {
                        "id": q.id,
                        "src": q.src,
                        "filename": Path(q.src).name,
                        "suggested_category": q.suggested_category,
                        "confidence": int((q.confidence or 0) * 100),
                        "reason": q.reason,
                        "signals": q.signals,
                        "created_at": q.created_at.strftime("%Y-%m-%d %H:%M:%S") if q.created_at else None,
                        "status": q.status,
                    }
                    for q in items
                ],
                "resolved": [
                    {
                        "id": q.id,
                        "src": q.src,
                        "filename": Path(q.src).name,
                        "category": q.suggested_category,
                        "resolved_path": q.resolved_path,
                        "resolved_filename": Path(q.resolved_path).name if q.resolved_path else None,
                        "resolved_at": q.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if q.resolved_at else None,
                        "status": q.status,
                    }
                    for q in resolved
                ],
            }

    def _do_resolve_item(
        qm: QuarantineManager,
        rec: QuarantineRecord,
        category: str,
        title: Optional[str] = None,
        year: Optional[int] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        target_path: Optional[str] = None,
    ) -> tuple[bool, str]:
        cat = category.lower()
        src_path = Path(rec.src)
        if not src_path.exists():
            downloads_path = settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")
            for root, _, files in os.walk(downloads_path):
                if src_path.name in files:
                    src_path = Path(root) / src_path.name
                    break

        if not src_path.exists():
            return False, f"Source file not found: {rec.src}"

        # Determine destination based on manual inputs or defaults
        if target_path:
            final_dst = Path(target_path).resolve()
            final_dst.parent.mkdir(parents=True, exist_ok=True)
        elif cat == "movie":
            movies_base = settings.get_destination_path("movie")
            if title:
                movie_title = title.strip()
                y_m = re.search(r"\((19\d\d|20\d\d)\)", movie_title)
                if y_m and not year:
                    year = int(y_m.group(1))
                    movie_title = re.sub(r"\s*\(\d{4}\)", "", movie_title).strip()
                folder_name = f"{movie_title} ({year})" if year else movie_title
                file_name = f"{folder_name}{src_path.suffix}"
                dest_dir = movies_base / folder_name
            else:
                tok = FilenameTokenizer()
                t = tok.tokenize(src_path)
                if t.title and t.year:
                    folder_name = f"{t.title} ({t.year})"
                    dest_dir = movies_base / folder_name
                    file_name = f"{folder_name}{src_path.suffix}"
                elif t.title:
                    dest_dir = movies_base / t.title
                    file_name = f"{t.title}{src_path.suffix}"
                else:
                    dest_dir = movies_base
                    file_name = src_path.name
            dest_dir.mkdir(parents=True, exist_ok=True)
            final_dst = dest_dir / file_name

        elif cat == "tv":
            shows_base = settings.get_destination_path("tv")
            if title:
                show_name = title.strip()
                s_num = season if season is not None else 1
                e_num = episode if episode is not None else 1
                dest_dir = shows_base / show_name / f"Season {s_num:02d}"
                file_name = f"{show_name} - S{s_num:02d}E{e_num:02d}{src_path.suffix}"
            else:
                tok = FilenameTokenizer()
                t = tok.tokenize(src_path)
                show_name = t.title if t.title else src_path.stem
                s_num = t.season if t.season is not None else 1
                e_num = t.episode if t.episode is not None else 1
                dest_dir = shows_base / show_name / f"Season {s_num:02d}"
                file_name = f"{show_name} - S{s_num:02d}E{e_num:02d}{src_path.suffix}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            final_dst = dest_dir / file_name
        else:
            dest_dir = settings.get_destination_path(cat)
            dest_dir.mkdir(parents=True, exist_ok=True)
            final_dst = dest_dir / src_path.name

        # Avoid collision
        if final_dst.exists() and final_dst.resolve() != src_path.resolve():
            stem = final_dst.stem
            suffix = final_dst.suffix
            counter = 2
            while final_dst.exists():
                final_dst = final_dst.parent / f"{stem} ({counter}){suffix}"
                counter += 1

        shutil.move(src_path, final_dst)
        qm.resolve_item(rec.id, cat, target_path=final_dst)
        return True, str(final_dst)

    @app.post("/api/quarantine/{item_id}/resolve")
    def resolve_quarantine(item_id: int, req: ResolveRequest):
        with get_db_session(engine) as session:
            qm = QuarantineManager(session)
            rec = qm.get_by_id(item_id)
            if not rec:
                raise HTTPException(status_code=404, detail="Quarantine item not found")

            ok, res = _do_resolve_item(
                qm, rec,
                category=req.category,
                title=req.title,
                year=req.year,
                season=req.season,
                episode=req.episode,
                target_path=req.target_path,
            )
            if not ok:
                raise HTTPException(status_code=400, detail=res)

            return {
                "status": "resolved",
                "item_id": item_id,
                "category": req.category,
                "destination": res,
            }

    @app.post("/api/quarantine/bulk-resolve")
    def bulk_resolve_quarantine(req: BulkResolveRequest):
        with get_db_session(engine) as session:
            qm = QuarantineManager(session)
            if req.item_ids:
                records = [qm.get_by_id(i) for i in req.item_ids]
                records = [r for r in records if r and r.status == QuarantineStatus.PENDING.value]
            else:
                records = qm.list_pending()

            resolved_count = 0
            failed_count = 0
            errors = []
            for rec in records:
                ok, res = _do_resolve_item(
                    qm, rec,
                    category=req.category,
                    title=req.title,
                    year=req.year,
                    season=req.season,
                    episode=req.episode,
                    target_path=req.target_path,
                )
                if ok:
                    resolved_count += 1
                else:
                    failed_count += 1
                    errors.append(res)

            return {
                "status": "ok",
                "resolved_count": resolved_count,
                "failed_count": failed_count,
                "errors": errors[:10],
            }

    @app.post("/api/quarantine/{item_id}/undo")
    def undo_quarantine(item_id: int):
        with get_db_session(engine) as session:
            qm = QuarantineManager(session)
            success = qm.undo_item(item_id)
            if not success:
                raise HTTPException(status_code=404, detail="Quarantine item not found or could not be undone")
            return {"status": "undone", "item_id": item_id}

    @app.post("/api/quarantine/bulk-undo")
    def bulk_undo_quarantine(req: BulkUndoRequest):
        with get_db_session(engine) as session:
            qm = QuarantineManager(session)
            if req.item_ids:
                records = [qm.get_by_id(i) for i in req.item_ids]
                records = [r for r in records if r]
            elif req.scope == "resolved":
                records = qm.list_resolved(limit=1000)
            else:
                records = qm.list_pending()

            undone_count = 0
            for rec in records:
                if qm.undo_item(rec.id):
                    undone_count += 1

            return {"status": "ok", "undone_count": undone_count}

    @app.post("/api/files/manual-sort")
    def manual_sort_file(req: ManualSortRequest):
        downloads_path = (settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")).resolve()
        target = (downloads_path / req.relative_path).resolve()
        if not target.is_relative_to(downloads_path) or not target.is_file():
            found = None
            for root, _, files in os.walk(downloads_path):
                if req.relative_path in files or target.name in files:
                    found = Path(root) / (req.relative_path if req.relative_path in files else target.name)
                    break
            if found and found.is_file():
                target = found
            else:
                raise HTTPException(status_code=404, detail="File not found")

        category = req.category.lower()
        if category == "movie":
            movies_base = settings.get_destination_path("movie")
            movie_title = req.title.strip()
            year = req.year
            y_m = re.search(r"\((19\d\d|20\d\d)\)", movie_title)
            if y_m and not year:
                year = int(y_m.group(1))
                movie_title = re.sub(r"\s*\(\d{4}\)", "", movie_title).strip()
            folder_name = f"{movie_title} ({year})" if year else movie_title
            dest_dir = movies_base / folder_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            final_dst = dest_dir / f"{folder_name}{target.suffix}"
        elif category == "tv":
            shows_base = settings.get_destination_path("tv")
            show_name = req.title.strip()
            season = req.season if req.season is not None else 1
            episode = req.episode if req.episode is not None else 1
            dest_dir = shows_base / show_name / f"Season {season:02d}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            final_dst = dest_dir / f"{show_name} - S{season:02d}E{episode:02d}{target.suffix}"
        else:
            dest_dir = settings.get_destination_path(category)
            dest_dir.mkdir(parents=True, exist_ok=True)
            final_dst = dest_dir / target.name

        shutil.move(target, final_dst)
        with get_db_session(engine) as session:
            try:
                from .library import record_detected_item
                record_detected_item(
                    session,
                    settings,
                    req.title.strip(),
                    category,
                    destination_folder=str(dest_dir),
                    year=req.year,
                    delta_count=1,
                )
            except Exception as e:
                logger.error("Error updating library from manual sort", error=str(e))

        return {"status": "moved", "destination": str(final_dst)}

    @app.post("/api/files/sort-show")
    def sort_show_endpoint(req: SortShowRequest):
        downloads_path = (settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")).resolve()
        resolved_files: List[Path] = []
        if req.relative_paths:
            for rel in req.relative_paths:
                p = (downloads_path / rel).resolve()
                if p.is_file() and p.is_relative_to(downloads_path):
                    resolved_files.append(p)
                else:
                    for root, _, files in os.walk(downloads_path):
                        if rel in files or p.name in files:
                            found = Path(root) / (rel if rel in files else p.name)
                            if found.is_file():
                                resolved_files.append(found)
                                break
        else:
            inspection = inspect_downloads_folder(downloads_path, settings, engine=engine)
            for show in inspection.get("shows", []):
                if show.get("show_name", "").lower() == req.show_name.lower():
                    for f in show.get("files", []):
                        p = (downloads_path / f["relative_path"]).resolve()
                        if p.is_file():
                            resolved_files.append(p)
                    break

        if not resolved_files:
            raise HTTPException(status_code=404, detail=f"No files found for show '{req.show_name}'")

        sorter = MediaSorterApp(settings, engine)
        report = sorter.run(
            dry_run=req.dry_run,
            filter_paths=resolved_files,
            show_name_override=req.show_name,
        )

        with get_db_session(engine) as session:
            try:
                from .library import record_detected_item
                shows_base = settings.get_destination_path("tv")
                record_detected_item(
                    session,
                    settings,
                    req.show_name,
                    "tv",
                    destination_folder=str(shows_base / req.show_name),
                    delta_count=report.moved_files,
                )
            except Exception as e:
                logger.error("Error updating library from sort-show", error=str(e))

        return {
            "status": "ok",
            "show_name": req.show_name,
            "total_files": report.total_files,
            "moved_files": report.moved_files,
            "quarantined_files": report.quarantined_files,
            "failed_files": report.failed_files,
            "batch_id": report.batch_id,
            "operations": [
                {
                    "src": str(op.src.name),
                    "dst": str(op.dst),
                    "category": op.category,
                    "confidence": int(op.confidence * 100),
                }
                for op in report.operations
            ],
        }

    @app.post("/api/files/sort-group")
    def sort_group_endpoint(req: SortGroupRequest):
        """Sort an entire group of unsure files (shared subfolder or common name) together."""
        downloads_path = (settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")).resolve()
        resolved_files: List[Path] = []
        for rel in req.relative_paths:
            p = (downloads_path / rel).resolve()
            if p.is_file() and p.is_relative_to(downloads_path):
                resolved_files.append(p)
            else:
                for root, _, files in os.walk(downloads_path):
                    if rel in files or p.name in files:
                        found = Path(root) / (rel if rel in files else p.name)
                        if found.is_file():
                            resolved_files.append(found)
                            break

        if not resolved_files:
            raise HTTPException(status_code=404, detail=f"No files found for group '{req.group_name}'")

        cat = (req.category or "tv").lower()
        target_title = (req.title or req.group_name).strip()

        if cat == "tv":
            sorter = MediaSorterApp(settings, engine)
            report = sorter.run(
                dry_run=req.dry_run,
                filter_paths=resolved_files,
                show_name_override=target_title,
            )
            with get_db_session(engine) as session:
                try:
                    from .library import record_detected_item
                    shows_base = settings.get_destination_path("tv")
                    record_detected_item(
                        session,
                        settings,
                        target_title,
                        "tv",
                        destination_folder=str(shows_base / target_title),
                        delta_count=report.moved_files,
                    )
                except Exception as e:
                    logger.error("Error updating library from sort-group tv", error=str(e))

            return {
                "status": "ok",
                "group_name": req.group_name,
                "title": target_title,
                "category": "tv",
                "total_files": report.total_files,
                "moved_files": report.moved_files,
                "quarantined_files": report.quarantined_files,
                "failed_files": report.failed_files,
                "batch_id": report.batch_id,
                "operations": [
                    {
                        "src": str(op.src.name),
                        "dst": str(op.dst),
                        "category": op.category,
                        "confidence": int(op.confidence * 100),
                    }
                    for op in report.operations
                ],
            }
        else:
            movies_base = settings.get_destination_path("movie")
            folder_name = f"{target_title} ({req.year})" if req.year else target_title
            dest_dir = movies_base / folder_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            moved_count = 0
            for f in resolved_files:
                if not req.dry_run:
                    final_dst = dest_dir / f.name
                    shutil.move(f, final_dst)
                    moved_count += 1
            with get_db_session(engine) as session:
                try:
                    from .library import record_detected_item
                    record_detected_item(
                        session,
                        settings,
                        target_title,
                        "movie",
                        destination_folder=str(dest_dir),
                        year=req.year,
                        delta_count=moved_count,
                    )
                except Exception as e:
                    logger.error("Error updating library from sort-group movie", error=str(e))

            return {
                "status": "ok",
                "group_name": req.group_name,
                "title": target_title,
                "category": "movie",
                "total_files": len(resolved_files),
                "moved_files": moved_count,
                "quarantined_files": 0,
                "failed_files": 0,
                "batch_id": "manual_group_movie",
                "operations": [],
            }

    @app.get("/api/library")
    def get_library_catalog(category: Optional[str] = None, search: Optional[str] = None):
        """Retrieve indexed library shows and movies with live search and category filtering."""
        with get_db_session(engine) as session:
            from .library import list_library_items
            return list_library_items(session, category=category, search=search)

    @app.post("/api/library/rescan")
    def rescan_library_catalog():
        """Rescan movies and shows directories on disk and synchronize database."""
        with get_db_session(engine) as session:
            from .library import sync_library_from_disk
            res = sync_library_from_disk(session, settings)
            return {"status": "ok", **res}


    @app.get("/api/settings")
    def get_settings_view():
        return {
            "downloads_dir": settings.storage.source_dirs[0] if settings.storage.source_dirs else "./downloads",
            "movies_dir": settings.storage.destination_dirs.movies,
            "shows_dir": settings.storage.destination_dirs.tv,
            "dry_run": settings.general.dry_run,
            "confidence_threshold": settings.general.confidence_threshold,
            "min_file_age_seconds": settings.general.min_file_age_seconds,
            "scan_interval_seconds": settings.general.scan_interval_seconds,
            "cleanup_empty_dirs": settings.general.cleanup_empty_dirs,
            "rename_files": settings.general.rename_files,
            "movie_template": settings.templates.movie,
            "tv_template": settings.templates.tv,
            "action": settings.general.action.value,
            "server_host": settings.server.host,
            "server_port": settings.server.port,
        }

    @app.post("/api/settings")
    def update_settings(req: SettingsUpdateRequest):
        """Update settings and persist to .env file."""
        if req.downloads_dir:
            settings.storage.source_dirs = [req.downloads_dir]
            os.environ["DOWNLOADS_DIR"] = req.downloads_dir
            Path(req.downloads_dir).mkdir(parents=True, exist_ok=True)
        if req.movies_dir:
            settings.storage.destination_dirs.movies = req.movies_dir
            os.environ["MOVIES_DIR"] = req.movies_dir
            Path(req.movies_dir).mkdir(parents=True, exist_ok=True)
        if req.shows_dir:
            settings.storage.destination_dirs.tv = req.shows_dir
            if not os.getenv("ANIME_DIR"):
                settings.storage.destination_dirs.anime = req.shows_dir
            os.environ["SHOWS_DIR"] = req.shows_dir
            Path(req.shows_dir).mkdir(parents=True, exist_ok=True)
        if req.dry_run is not None:
            settings.general.dry_run = req.dry_run
            os.environ["DRY_RUN"] = "true" if req.dry_run else "false"
        if req.confidence_threshold is not None:
            settings.general.confidence_threshold = req.confidence_threshold
            os.environ["CONFIDENCE_THRESHOLD"] = str(req.confidence_threshold)
        if req.min_file_age_seconds is not None:
            settings.general.min_file_age_seconds = req.min_file_age_seconds
            os.environ["MIN_FILE_AGE_SECONDS"] = str(req.min_file_age_seconds)
        if req.scan_interval_seconds is not None:
            settings.general.scan_interval_seconds = req.scan_interval_seconds
            os.environ["SCAN_INTERVAL_SECONDS"] = str(req.scan_interval_seconds)
        if req.cleanup_empty_dirs is not None:
            settings.general.cleanup_empty_dirs = req.cleanup_empty_dirs
            os.environ["CLEANUP_EMPTY_DIRS"] = "true" if req.cleanup_empty_dirs else "false"
        if req.rename_files is not None:
            settings.general.rename_files = req.rename_files
            os.environ["RENAME_FILES"] = "true" if req.rename_files else "false"
        if req.movie_template is not None:
            tmpl = req.movie_template.strip()
            if tmpl:
                settings.templates.movie = tmpl
                os.environ["MOVIE_TEMPLATE"] = tmpl
        if req.tv_template is not None:
            tmpl = req.tv_template.strip()
            if tmpl:
                settings.templates.tv = tmpl
                os.environ["TV_TEMPLATE"] = tmpl
        if req.action:
            try:
                settings.general.action = ActionType(req.action.lower())
                os.environ["ACTION"] = req.action.lower()
            except ValueError:
                pass

        # Save to .env
        settings.save_to_env_file(env_path)
        return {"status": "saved", "message": f"Settings updated and saved to {env_path}"}

    @app.post("/api/restart")
    def trigger_server_restart(background_tasks: BackgroundTasks):
        """Trigger process restart (works with PM2 or standalone)."""
        def _deferred_restart():
            time.sleep(0.5)
            logger.info("Restarting Media Sorter server...")
            if "pm_id" in os.environ or "PM2_HOME" in os.environ or "PM2_USAGE" in os.environ:
                os._exit(0)
            else:
                try:
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                except Exception:
                    os._exit(0)

        background_tasks.add_task(_deferred_restart)
        return {"status": "restarting", "message": "Server restart initiated. Reconnecting in a few seconds..."}

    @app.get("/api/poster/local")
    def serve_local_poster(path: str):
        """Serve a local show artwork image securely."""
        p = Path(path).resolve()
        if not p.exists() or not p.is_file():
            raise HTTPException(status_code=404, detail="Poster file not found")
        if p.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            raise HTTPException(status_code=400, detail="Not an image file")
        return FileResponse(p)

    @app.get("/api/poster")
    def get_poster_endpoint(title: str):
        """Query or fetch show poster artwork URL."""
        poster = fetch_show_poster(title)
        return {"title": title, "poster_url": poster}

    # --- Updater Endpoints ---
    import subprocess, json, urllib.request
    GITHUB_OWNER = "jadonkortislolz-wq"
    GITHUB_REPO = "Media-sort"
    GITHUB_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/tags"
    GITHUB_TOKEN = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")

    def get_latest_tag() -> str:
        try:
            req = urllib.request.Request(GITHUB_API, headers={"User-Agent": "MediaSorter-Updater", "Authorization": f"token {GITHUB_TOKEN}"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.load(resp)
                    if isinstance(data, list) and data:
                        return data[0].get("name", "")
        except Exception as e:
            logger.error("Failed to fetch latest tag", error=str(e))
        return ""

    @app.get("/api/check_update")
    async def check_update():
        from .__init__ import __version__
        latest = get_latest_tag()
        return {"current_version": __version__, "latest_version": latest, "update_available": bool(latest and latest != __version__)}

    @app.post("/api/perform_update")
    async def perform_update(background: BackgroundTasks):
        def git_pull():
            repo_path = Path(__file__).resolve().parents[2]
            result = subprocess.run(["git", "pull", "origin", "main"], cwd=str(repo_path), capture_output=True, text=True)
            logger.info("Git pull result", stdout=result.stdout, stderr=result.stderr)
        background.add_task(git_pull)
        return {"status": "update_started"}
    # End of updater endpoints

    @app.get("/", response_class=HTMLResponse)
    def render_dashboard():
        """Serve the interactive modern Web Dashboard."""
        html = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Media Sorter Management</title>
  <script>
    (function() {
      try {
        var t = localStorage.getItem('ms-theme') || 'cyber-dark';
        document.documentElement.setAttribute('data-theme', t);
      } catch (e) {}
    })();
  </script>
  <style>
    /* 1. Cyber Dark (Default) */
    :root, [data-theme="cyber-dark"] {
      --bg: #090d16;
      --card-bg: #0f172a;
      --card-hover: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --text-title: #ffffff;
      --accent: #38bdf8;
      --accent-hover: #0284c7;
      --emerald: #10b981;
      --emerald-hover: #059669;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --indigo: #6366f1;
      --subbar-bg: rgba(0, 0, 0, 0.25);
      --badge-bg: #1e293b;
      --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --radius-card: 0.6rem;
      --radius-btn: 0.375rem;
      --radius-sm: 0.25rem;
      --radius-badge: 9999px;
      --radius-poster: 0.35rem;
      --card-border: 1px solid var(--border);
      --card-shadow: none;
      --btn-border: 1px solid transparent;
      --btn-shadow: none;
      --text-glow: none;
    }

    /* 2. Midnight OLED (True Black & Neon Pink) */
    [data-theme="oled-neon"] {
      --bg: #000000;
      --card-bg: #0b0b12;
      --card-hover: #141420;
      --border: #29283e;
      --text: #ffffff;
      --text-muted: #a1a1aa;
      --accent: #ec4899;
      --accent-hover: #db2777;
      --emerald: #06b6d4;
      --emerald-hover: #0891b2;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --indigo: #a855f7;
      --subbar-bg: rgba(11, 11, 18, 0.85);
      --badge-bg: #181826;
    }

    /* 3. Nord Arctic Frost */
    [data-theme="nord-frost"] {
      --bg: #242933;
      --card-bg: #2e3440;
      --card-hover: #3b4252;
      --border: #434c5e;
      --text: #eceff4;
      --text-muted: #d8dee9;
      --accent: #88c0d0;
      --accent-hover: #81a1c1;
      --emerald: #a3be8c;
      --emerald-hover: #8fad78;
      --amber: #ebcb8b;
      --rose: #bf616a;
      --indigo: #b48ead;
      --subbar-bg: rgba(36, 41, 51, 0.7);
      --badge-bg: #3b4252;
    }

    /* 4. Dracula Purple */
    [data-theme="dracula"] {
      --bg: #151320;
      --card-bg: #1f1d2e;
      --card-hover: #2a273f;
      --border: #393552;
      --text: #f8f8f2;
      --text-muted: #908caa;
      --accent: #c4a7e7;
      --accent-hover: #b48eed;
      --emerald: #9ccfd8;
      --emerald-hover: #7db9c4;
      --amber: #f6c177;
      --rose: #eb6f92;
      --indigo: #ea9a97;
      --subbar-bg: rgba(21, 19, 32, 0.75);
      --badge-bg: #2a273f;
    }

    /* 5. Emerald Matrix */
    [data-theme="emerald-matrix"] {
      --bg: #050c08;
      --card-bg: #0a1811;
      --card-hover: #11291d;
      --border: #1b3d2b;
      --text: #e6f7ef;
      --text-muted: #6ea388;
      --accent: #10b981;
      --accent-hover: #059669;
      --emerald: #34d399;
      --emerald-hover: #10b981;
      --amber: #fbbf24;
      --rose: #fb7185;
      --indigo: #2dd4bf;
      --subbar-bg: rgba(5, 12, 8, 0.8);
      --badge-bg: #11291d;
    }

    /* 6. Solar Sunset (Warm Charcoal & Radiant Amber) */
    [data-theme="solar-sunset"] {
      --bg: #100b0b;
      --card-bg: #1c1414;
      --card-hover: #291c1c;
      --border: #422a2a;
      --text: #fef2f2;
      --text-muted: #b89898;
      --accent: #f97316;
      --accent-hover: #ea580c;
      --emerald: #10b981;
      --emerald-hover: #059669;
      --amber: #fbbf24;
      --rose: #f43f5e;
      --indigo: #fb923c;
      --subbar-bg: rgba(16, 11, 11, 0.85);
      --badge-bg: #291c1c;
    }

    /* 7. Tokyo Night (Deep Indigo & Electric Cyan) */
    [data-theme="tokyo-night"] {
      --bg: #1a1b26;
      --card-bg: #24283b;
      --card-hover: #2f3549;
      --border: #414868;
      --text: #c0caf5;
      --text-muted: #7982a9;
      --accent: #7aa2f7;
      --accent-hover: #3d59a1;
      --emerald: #9ece6a;
      --emerald-hover: #73984e;
      --amber: #e0af68;
      --rose: #f7768e;
      --indigo: #bb9af7;
      --subbar-bg: rgba(26, 27, 38, 0.85);
      --badge-bg: #2f3549;
    }

    /* 8. Synthwave 80s (Retro Violet & Neon Pink) */
    [data-theme="synthwave"] {
      --bg: #140d22;
      --card-bg: #211538;
      --card-hover: #2d1c4d;
      --border: #4a2c7a;
      --text: #fdf4ff;
      --text-muted: #aa95cc;
      --accent: #d946ef;
      --accent-hover: #c026d3;
      --emerald: #06b6d4;
      --emerald-hover: #0891b2;
      --amber: #f59e0b;
      --rose: #ff007f;
      --indigo: #ec4899;
      --subbar-bg: rgba(20, 13, 34, 0.85);
      --badge-bg: #2d1c4d;
    }

    /* 9. Abyssal Ocean (Deep Marine & Aquamarine) */
    [data-theme="abyssal-ocean"] {
      --bg: #051018;
      --card-bg: #0c1b26;
      --card-hover: #132838;
      --border: #1a3c54;
      --text: #e0f2fe;
      --text-muted: #739bb8;
      --accent: #14b8a6;
      --accent-hover: #0d9488;
      --emerald: #2dd4bf;
      --emerald-hover: #14b8a6;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --indigo: #38bdf8;
      --subbar-bg: rgba(5, 16, 24, 0.85);
      --badge-bg: #132838;
    }

    /* 10. Monokai Pro (Dark Carbon & Vivid Gold) */
    [data-theme="monokai-pro"] {
      --bg: #1d1b1d;
      --card-bg: #282528;
      --card-hover: #363236;
      --border: #474347;
      --text: #fcfcfa;
      --text-muted: #9c999c;
      --accent: #ffd866;
      --accent-hover: #e6c152;
      --emerald: #a9dc76;
      --emerald-hover: #8fbc60;
      --amber: #fc9867;
      --rose: #ff6188;
      --indigo: #78dce8;
      --subbar-bg: rgba(29, 27, 29, 0.85);
      --badge-bg: #363236;
    }

    /* 11. Retro Matrix CRT (Monospace & Neon Phosphor) */
    [data-theme="terminal-crt"] {
      --bg: #020703;
      --card-bg: #051108;
      --card-hover: #0a200f;
      --border: #00ff66;
      --text: #5af78e;
      --text-muted: #1e824c;
      --text-title: #00ff66;
      --accent: #00ff66;
      --accent-hover: #33ff88;
      --emerald: #00ff66;
      --emerald-hover: #33ff88;
      --amber: #ffcc00;
      --rose: #ff3333;
      --indigo: #00e5ff;
      --subbar-bg: rgba(0, 20, 5, 0.9);
      --badge-bg: #041407;
      --font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', Courier, monospace;
      --radius-card: 0px;
      --radius-btn: 0px;
      --radius-sm: 0px;
      --radius-badge: 0px;
      --radius-poster: 0px;
      --card-border: 1px solid #00ff66;
      --card-shadow: 0 0 12px rgba(0, 255, 102, 0.15), inset 0 0 6px rgba(0, 255, 102, 0.05);
      --btn-border: 1px solid #00ff66;
      --btn-shadow: 0 0 8px rgba(0, 255, 102, 0.25);
      --text-glow: 0 0 6px rgba(0, 255, 102, 0.5);
    }
    [data-theme="terminal-crt"] body {
      background: radial-gradient(circle at 50% 50%, #061509 0%, #020703 100%);
    }
    [data-theme="terminal-crt"] .top-bar-area {
      border-bottom: 1px solid #00ff66;
      box-shadow: 0 2px 10px rgba(0, 255, 102, 0.15);
    }
    [data-theme="terminal-crt"] .brand-title {
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    [data-theme="terminal-crt"] .btn {
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    [data-theme="terminal-crt"] .btn-accent {
      background: #00ff66;
      color: #020703;
      font-weight: 700;
    }
    [data-theme="terminal-crt"] .btn-accent:hover {
      background: #33ff88;
      color: #020703;
      box-shadow: 0 0 12px #00ff66;
    }
    [data-theme="terminal-crt"] .btn-emerald {
      background: #032b13;
      color: #00ff66;
      border: 1px solid #00ff66;
    }
    [data-theme="terminal-crt"] .btn-emerald:hover {
      background: #00ff66;
      color: #020703;
    }
    [data-theme="terminal-crt"] .nav-tab.active {
      color: #00ff66;
      border-bottom: 2px solid #00ff66;
      text-shadow: 0 0 8px #00ff66;
    }
    [data-theme="terminal-crt"] .theme-card {
      background: #041407;
      border: 1px solid #00ff66;
      border-radius: 0px;
    }
    [data-theme="terminal-crt"] .theme-card.active {
      border-color: #00ff66;
      background: rgba(0, 255, 102, 0.15);
      box-shadow: 0 0 10px rgba(0, 255, 102, 0.3);
    }

    /* 12. Paper Light (Clean Studio / Pure Light Mode) */
    [data-theme="paper-light"] {
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --card-hover: #f1f5f9;
      --border: #e2e8f0;
      --text: #1e293b;
      --text-muted: #64748b;
      --text-title: #0f172a;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --emerald: #059669;
      --emerald-hover: #047857;
      --amber: #d97706;
      --rose: #e11d48;
      --indigo: #4f46e5;
      --subbar-bg: #f8fafc;
      --badge-bg: #e2e8f0;
      --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --radius-card: 0.75rem;
      --radius-btn: 0.5rem;
      --radius-sm: 0.35rem;
      --radius-badge: 9999px;
      --radius-poster: 0.4rem;
      --card-border: 1px solid #e2e8f0;
      --card-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.06), 0 2px 4px -2px rgba(0, 0, 0, 0.04);
      --btn-border: 1px solid transparent;
      --btn-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
      --text-glow: none;
    }
    [data-theme="paper-light"] .top-bar-area {
      background: #ffffff;
      border-bottom: 1px solid #e2e8f0;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
    }
    [data-theme="paper-light"] .show-dropdown-header {
      background: #ffffff;
    }
    [data-theme="paper-light"] .show-dropdown-header:hover {
      background: #f8fafc;
    }
    [data-theme="paper-light"] .show-dropdown-body {
      background: #fafafa;
    }
    [data-theme="paper-light"] table thead th {
      background: #f8fafc;
    }
    [data-theme="paper-light"] tr:hover td {
      background: rgba(0, 0, 0, 0.02);
    }
    [data-theme="paper-light"] .modal-content {
      background: #ffffff;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
    }
    [data-theme="paper-light"] .theme-card {
      background: #f8fafc;
      border-color: #cbd5e1;
    }
    [data-theme="paper-light"] .btn-accent {
      background: #2563eb;
      color: #ffffff;
    }
    [data-theme="paper-light"] .btn-accent:hover {
      background: #1d4ed8;
      color: #ffffff;
    }
    [data-theme="paper-light"] .brand-icon {
      background: rgba(37, 99, 235, 0.1);
    }

    /* 13. Neo-Brutalism Pop */
    [data-theme="neo-brutalism"] {
      --bg: #fffdf5;
      --card-bg: #ffffff;
      --card-hover: #fef08a;
      --border: #000000;
      --text: #000000;
      --text-muted: #4b5563;
      --text-title: #000000;
      --accent: #ffd12d;
      --accent-hover: #fcc419;
      --emerald: #2fe084;
      --emerald-hover: #22c55e;
      --amber: #ff922b;
      --rose: #ff6b6b;
      --indigo: #748ffc;
      --subbar-bg: #fff3bf;
      --badge-bg: #fff3bf;
      --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --radius-card: 0.5rem;
      --radius-btn: 0.35rem;
      --radius-sm: 0.25rem;
      --radius-badge: 0.25rem;
      --radius-poster: 0.25rem;
      --card-border: 2.5px solid #000000;
      --card-shadow: 4px 4px 0px #000000;
      --btn-border: 2px solid #000000;
      --btn-shadow: 3px 3px 0px #000000;
      --text-glow: none;
    }
    [data-theme="neo-brutalism"] .top-bar-area {
      background: #fffdf5;
      border-bottom: 2.5px solid #000000;
    }
    [data-theme="neo-brutalism"] .btn {
      border: 2px solid #000000 !important;
      box-shadow: 3px 3px 0px #000000;
      font-weight: 700;
      color: #000000 !important;
    }
    [data-theme="neo-brutalism"] .btn:hover {
      transform: translate(-1px, -1px);
      box-shadow: 4px 4px 0px #000000;
    }
    [data-theme="neo-brutalism"] .btn:active {
      transform: translate(2px, 2px);
      box-shadow: 1px 1px 0px #000000;
    }
    [data-theme="neo-brutalism"] .stat-card,
    [data-theme="neo-brutalism"] .panel,
    [data-theme="neo-brutalism"] .show-dropdown,
    [data-theme="neo-brutalism"] .modal-content {
      border: 2.5px solid #000000;
      box-shadow: 4px 4px 0px #000000;
    }
    [data-theme="neo-brutalism"] .tag {
      border: 1.5px solid #000000;
      font-weight: 700;
      color: #000000 !important;
    }
    [data-theme="neo-brutalism"] .show-dropdown-header {
      background: #fffdf5;
      border-bottom: 2px solid #000000;
    }
    [data-theme="neo-brutalism"] .show-dropdown-body {
      background: #ffffff;
    }
    [data-theme="neo-brutalism"] table thead th {
      background: #fff3bf;
      color: #000000;
      border-bottom: 2px solid #000000;
    }
    [data-theme="neo-brutalism"] table td {
      border-bottom: 1.5px solid #000000;
    }
    [data-theme="neo-brutalism"] tr:hover td {
      background: rgba(0, 0, 0, 0.03);
    }
    [data-theme="neo-brutalism"] .theme-card {
      border: 2px solid #000000;
      box-shadow: 3px 3px 0px #000000;
      background: #ffffff;
    }
    [data-theme="neo-brutalism"] .brand-icon {
      border: 2px solid #000000;
      box-shadow: 2px 2px 0px #000000;
      background: #ffd12d;
      color: #000000;
    }
    [data-theme="neo-brutalism"] .nav-tab.active {
      color: #000000;
      border-bottom: 3px solid #000000;
      font-weight: 800;
    }

    /* 14. Frosted Aurora Glassmorphism */
    [data-theme="aurora-glass"] {
      --bg: #0c0f1d;
      --card-bg: rgba(22, 27, 46, 0.65);
      --card-hover: rgba(30, 38, 64, 0.75);
      --border: rgba(255, 255, 255, 0.14);
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --text-title: #ffffff;
      --accent: #a855f7;
      --accent-hover: #9333ea;
      --emerald: #06b6d4;
      --emerald-hover: #0891b2;
      --amber: #f59e0b;
      --rose: #ec4899;
      --indigo: #6366f1;
      --subbar-bg: rgba(14, 18, 34, 0.7);
      --badge-bg: rgba(255, 255, 255, 0.08);
      --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --radius-card: 1rem;
      --radius-btn: 0.65rem;
      --radius-sm: 0.45rem;
      --radius-badge: 9999px;
      --radius-poster: 0.5rem;
      --card-border: 1px solid rgba(255, 255, 255, 0.14);
      --card-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
      --btn-border: 1px solid rgba(255, 255, 255, 0.16);
      --btn-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
      --text-glow: 0 0 12px rgba(168, 85, 247, 0.35);
    }
    [data-theme="aurora-glass"] body {
      background: radial-gradient(circle at 15% 15%, rgba(99, 102, 241, 0.28) 0%, transparent 45%),
                  radial-gradient(circle at 85% 25%, rgba(236, 72, 153, 0.22) 0%, transparent 45%),
                  radial-gradient(circle at 50% 85%, rgba(6, 182, 212, 0.2) 0%, transparent 50%),
                  #090c17;
      background-attachment: fixed;
    }
    [data-theme="aurora-glass"] .top-bar-area {
      background: rgba(12, 15, 29, 0.75);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }
    [data-theme="aurora-glass"] .stat-card,
    [data-theme="aurora-glass"] .panel,
    [data-theme="aurora-glass"] .show-dropdown,
    [data-theme="aurora-glass"] .modal-content {
      background: rgba(22, 27, 46, 0.65);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.14);
      box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.35);
    }
    [data-theme="aurora-glass"] .btn {
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
    }
    [data-theme="aurora-glass"] .show-dropdown-header {
      background: rgba(255, 255, 255, 0.03);
    }

    /* 15. Catppuccin Mocha (Warm Pastel & Rosewater) */
    [data-theme="catppuccin-mocha"] {
      --bg: #1e1e2e;
      --card-bg: #302d41;
      --card-hover: #3e3a50;
      --border: #45475a;
      --text: #cdd6f4;
      --text-muted: #a6adc8;
      --text-title: #f5e0dc;
      --accent: #f5c2e7;
      --accent-hover: #f38ba8;
      --emerald: #a6e3a1;
      --emerald-hover: #94e2d5;
      --amber: #f9e2af;
      --rose: #f38ba8;
      --indigo: #cba6f7;
      --subbar-bg: rgba(30, 30, 46, 0.85);
      --badge-bg: #3e3a50;
    }

    /* 16. Rosé Pine (Muted Rose & Twilight) */
    [data-theme="rose-pine"] {
      --bg: #191724;
      --card-bg: #1f1d2e;
      --card-hover: #26233a;
      --border: #403d52;
      --text: #e0def4;
      --text-muted: #908caa;
      --text-title: #ebbcba;
      --accent: #ebbcba;
      --accent-hover: #eb6f92;
      --emerald: #9ccfd8;
      --emerald-hover: #31748f;
      --amber: #f6c177;
      --rose: #eb6f92;
      --indigo: #c4a7e7;
      --subbar-bg: rgba(25, 23, 36, 0.85);
      --badge-bg: #26233a;
    }

    /* 17. Gruvbox Dark (Earthy Retro & Warm Orange) */
    [data-theme="gruvbox-dark"] {
      --bg: #1d2021;
      --card-bg: #282828;
      --card-hover: #3c3836;
      --border: #504945;
      --text: #ebdbb2;
      --text-muted: #a89984;
      --text-title: #fbf1c7;
      --accent: #fe8019;
      --accent-hover: #d65d0e;
      --emerald: #b8bb26;
      --emerald-hover: #98971a;
      --amber: #fabd2f;
      --rose: #fb4934;
      --indigo: #d3869b;
      --subbar-bg: rgba(29, 32, 33, 0.85);
      --badge-bg: #3c3836;
    }

    /* 18. Solarized Dark (Scientific Blue & Yellow) */
    [data-theme="solarized-dark"] {
      --bg: #002b36;
      --card-bg: #073642;
      --card-hover: #0a4555;
      --border: #586e75;
      --text: #93a1a1;
      --text-muted: #657b83;
      --text-title: #fdf6e3;
      --accent: #268bd2;
      --accent-hover: #2176ad;
      --emerald: #859900;
      --emerald-hover: #6d7e00;
      --amber: #b58900;
      --rose: #dc322f;
      --indigo: #6c71c4;
      --subbar-bg: rgba(0, 43, 54, 0.9);
      --badge-bg: #0a4555;
    }

    /* 19. Nightowl (Deep Navy & Coral) */
    [data-theme="nightowl"] {
      --bg: #011627;
      --card-bg: #0b2942;
      --card-hover: #13385b;
      --border: #1d3b53;
      --text: #d6deeb;
      --text-muted: #7fdbca;
      --text-title: #ffffff;
      --accent: #c792ea;
      --accent-hover: #b46ddf;
      --emerald: #22da6e;
      --emerald-hover: #addb67;
      --amber: #ecc48d;
      --rose: #ef5350;
      --indigo: #82aaff;
      --subbar-bg: rgba(1, 22, 39, 0.9);
      --badge-bg: #13385b;
    }

    /* 20. Vesper (Warm Noir & Copper) */
    [data-theme="vesper"] {
      --bg: #101010;
      --card-bg: #1a1a1a;
      --card-hover: #232323;
      --border: #333333;
      --text: #d4d4d4;
      --text-muted: #6a6a6a;
      --text-title: #ffffff;
      --accent: #d4976c;
      --accent-hover: #c78555;
      --emerald: #78b892;
      --emerald-hover: #5e9c78;
      --amber: #e6c07b;
      --rose: #e06c75;
      --indigo: #c792ea;
      --subbar-bg: rgba(16, 16, 16, 0.9);
      --badge-bg: #232323;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    
    /* Scrollable app viewport - list scrolls without moving website header */
    html, body {
      height: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
    }
    body {
      font-family: var(--font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    .app-layout {
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }
    .top-bar-area {
      flex-shrink: 0;
      background: var(--bg);
      border-bottom: var(--card-border, 1px solid var(--border));
      padding: 1.15rem 2rem 0 2rem;
      z-index: 100;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 1rem;
      flex-wrap: wrap;
      gap: 1rem;
    }
    .brand { display: flex; align-items: center; gap: 0.75rem; }
    .brand-icon {
      font-size: 1.5rem;
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      width: 42px;
      height: 42px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: var(--radius-btn, 0.5rem);
    }
    .brand-title { font-size: 1.5rem; font-weight: 700; color: var(--text-title, #fff); letter-spacing: -0.025em; text-shadow: var(--text-glow, none); }
    .brand-subtitle { font-size: 0.8rem; color: var(--text-muted); }
    .header-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }

    .btn {
      padding: 0.5rem 1rem;
      border-radius: var(--radius-btn, 0.375rem);
      font-size: 0.875rem;
      font-weight: 600;
      cursor: pointer;
      border: var(--btn-border, 1px solid transparent);
      box-shadow: var(--btn-shadow, none);
      font-family: inherit;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      transition: all 0.15s ease;
    }
    .btn-emerald { background: var(--emerald); color: #fff; }
    .btn-emerald:hover { background: var(--emerald-hover); }
    .btn-accent { background: var(--accent); color: #090d16; }
    .btn-accent:hover { background: var(--accent-hover); color: #fff; }
    .btn-amber { background: rgba(245, 158, 11, 0.2); color: var(--amber); border-color: rgba(245, 158, 11, 0.4); }
    .btn-amber:hover { background: var(--amber); color: #000; }
    .btn-outline { background: transparent; border-color: var(--border); color: var(--text); }
    .btn-outline:hover { background: var(--card-hover); }
    .btn-sm { padding: 0.25rem 0.6rem; font-size: 0.75rem; border-radius: var(--radius-sm, 0.25rem); }

    .nav-tabs {
      display: flex;
      gap: 0.5rem;
      border-bottom: none;
      margin-bottom: 0;
    }
    .nav-tab {
      padding: 0.75rem 1.25rem;
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--text-muted);
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: all 0.15s;
    }
    .nav-tab:hover { color: var(--text); }
    .nav-tab.active { color: var(--accent); border-bottom-color: var(--accent); }

    /* Main Scrollable Viewport */
    .main-scroll-viewport {
      flex: 1;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 1.5rem 2rem 3rem 2rem;
      scroll-behavior: smooth;
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }
    .stat-card {
      background: var(--card-bg);
      border: var(--card-border, 1px solid var(--border));
      border-radius: var(--radius-card, 0.6rem);
      box-shadow: var(--card-shadow, none);
      padding: 1.25rem;
    }
    .stat-label { font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; margin-bottom: 0.35rem; }
    .stat-val { font-size: 1.75rem; font-weight: 700; color: var(--text-title, #fff); text-shadow: var(--text-glow, none); }

    .panel {
      background: var(--card-bg);
      border: var(--card-border, 1px solid var(--border));
      border-radius: var(--radius-card, 0.6rem);
      box-shadow: var(--card-shadow, none);
      padding: 1.25rem;
      margin-bottom: 1.5rem;
    }
    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
    }
    .panel-title { font-size: 1.1rem; font-weight: 600; color: var(--text-title, #fff); text-shadow: var(--text-glow, none); }

    table { width: 100%; border-collapse: collapse; text-align: left; }
    th { padding: 0.65rem 0.75rem; color: var(--text-muted); font-size: 0.8rem; font-weight: 600; border-bottom: 1px solid var(--border); background: var(--card-bg); }
    td { padding: 0.65rem 0.75rem; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
    tr:hover td { background: rgba(255, 255, 255, 0.02); }

    .tag {
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: var(--radius-sm, 0.25rem);
      font-size: 0.75rem;
      font-weight: 600;
    }
    .tag-movie { background: rgba(56, 189, 248, 0.2); color: var(--accent); }
    .tag-show { background: rgba(16, 185, 129, 0.2); color: var(--emerald); }
    .tag-quarantine { background: rgba(244, 63, 94, 0.2); color: var(--rose); }
    .tag-dry { background: #374151; color: #d1d5db; }
    .tag-live { background: rgba(16, 185, 129, 0.2); color: var(--emerald); }

    .form-group { margin-bottom: 1.25rem; }
    .form-label { display: block; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.35rem; color: var(--text); }
    .form-control {
      width: 100%;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm, 0.375rem);
      padding: 0.6rem 0.75rem;
      color: var(--text);
      font-family: inherit;
      font-size: 0.875rem;
    }
    .form-control:focus { outline: none; border-color: var(--accent); }

    .toast {
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      background: var(--card-bg);
      border: 1px solid var(--accent);
      color: #fff;
      padding: 0.75rem 1.25rem;
      border-radius: 0.5rem;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      display: none;
      z-index: 3000;
    }

    /* Scrollable Show Table Wrapper with Sticky Header */
    .show-table-wrapper {
      max-height: 460px;
      overflow-y: auto;
      overflow-x: auto;
      position: relative;
      border-bottom: 1px solid var(--border);
    }
    .show-table-wrapper table thead th {
      position: sticky;
      top: 0;
      background: var(--card-bg);
      z-index: 5;
      box-shadow: 0 1px 0 var(--border);
    }

    /* Show Dropdowns & Downloads Explorer */
    .show-dropdown {
      background: var(--card-bg);
      border: var(--card-border, 1px solid var(--border));
      border-radius: var(--radius-card, 0.6rem);
      box-shadow: var(--card-shadow, none);
      margin-bottom: 0.85rem;
      overflow: hidden;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .show-dropdown:hover {
      border-color: rgba(56, 189, 248, 0.4);
    }
    .show-dropdown-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.85rem 1.25rem;
      cursor: pointer;
      background: rgba(255, 255, 255, 0.02);
      user-select: none;
      transition: background 0.15s;
    }
    .show-dropdown-header:hover {
      background: rgba(255, 255, 255, 0.05);
    }
    .show-dropdown-left {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
    }
    .show-dropdown-chevron {
      font-size: 0.8rem;
      color: var(--accent);
      transition: transform 0.2s ease-in-out;
      display: inline-block;
      width: 14px;
      text-align: center;
    }
    .show-dropdown-chevron.open {
      transform: rotate(90deg);
    }
    .show-dropdown-title {
      font-size: 1rem;
      font-weight: 600;
      color: var(--text-title, #fff);
      text-shadow: var(--text-glow, none);
    }
    .show-dropdown-badge {
      font-size: 0.75rem;
      background: var(--badge-bg);
      color: var(--text-muted);
      padding: 0.15rem 0.5rem;
      border-radius: var(--radius-badge, 9999px);
      border: 1px solid var(--border);
    }
    .show-dropdown-side {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      flex-shrink: 0;
    }
    .believed-show-label {
      font-size: 0.8rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.03em;
      font-weight: 600;
    }
    .believed-show-val {
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: var(--emerald);
      padding: 0.25rem 0.65rem 0.25rem 0.4rem;
      border-radius: 0.375rem;
      font-weight: 600;
      font-size: 0.85rem;
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
    }
    .believed-poster-img {
      width: 26px;
      height: 38px;
      object-fit: cover;
      border-radius: 0.25rem;
      border: 1px solid rgba(16, 185, 129, 0.6);
      box-shadow: 0 2px 5px rgba(0, 0, 0, 0.4);
      flex-shrink: 0;
      background: rgba(0, 0, 0, 0.4);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .believed-poster-img:hover {
      transform: scale(1.65);
      box-shadow: 0 6px 16px rgba(0, 0, 0, 0.85);
      z-index: 30;
    }
    .show-left-poster {
      width: 42px;
      height: 60px;
      object-fit: cover;
      border-radius: 0.35rem;
      border: 1px solid var(--border);
      box-shadow: 0 3px 8px rgba(0, 0, 0, 0.35);
      flex-shrink: 0;
      background: rgba(0, 0, 0, 0.3);
      transition: transform 0.2s ease;
    }
    .show-left-poster:hover {
      transform: scale(1.08);
    }
    .show-subbar-poster {
      width: 48px;
      height: 68px;
      object-fit: cover;
      border-radius: 0.35rem;
      border: 1px solid var(--border);
      box-shadow: 0 4px 10px rgba(0, 0, 0, 0.4);
      flex-shrink: 0;
      background: rgba(0, 0, 0, 0.3);
    }
    .show-dropdown-body {
      display: none;
      border-top: 1px solid var(--border);
      background: rgba(11, 17, 32, 0.5);
    }
    .show-dropdown-subbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.6rem 1.25rem;
      background: var(--subbar-bg);
      border-bottom: 1px solid var(--border);
      font-size: 0.8rem;
      color: var(--text-muted);
      flex-wrap: wrap;
      gap: 0.5rem;
    }

    /* Modal Backdrop & Content */
    .modal-backdrop {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(5px);
      z-index: 2000;
      display: none;
      align-items: center;
      justify-content: center;
    }
    .modal-content {
      background: var(--card-bg);
      border: var(--card-border, 1px solid var(--border));
      border-radius: var(--radius-card, 0.75rem);
      width: 92%;
      max-width: 620px;
      max-height: 88vh;
      overflow-y: auto;
      box-shadow: var(--card-shadow, 0 25px 50px -12px rgba(0, 0, 0, 0.7));
      padding: 1.5rem;
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.85rem;
      margin-bottom: 1.25rem;
    }
    .modal-title { font-size: 1.2rem; font-weight: 700; color: var(--text-title, #fff); text-shadow: var(--text-glow, none); }
    .modal-close {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 1.5rem;
      cursor: pointer;
      line-height: 1;
    }
    .modal-close:hover { color: var(--text-title, #fff); }

    /* Theme Cards Grid */
    .theme-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .theme-card {
      border: 2px solid var(--border);
      background: rgba(0, 0, 0, 0.2);
      border-radius: var(--radius-card, 0.5rem);
      padding: 0.65rem;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      position: relative;
      transition: all 0.15s ease;
    }
    .theme-card:hover {
      border-color: var(--accent);
      transform: translateY(-2px);
    }
    .theme-card.active {
      border-color: var(--accent);
      background: rgba(56, 189, 248, 0.1);
    }
    .theme-swatch {
      width: 38px;
      height: 38px;
      border-radius: 50%;
      margin-bottom: 0.5rem;
      border: 2px solid rgba(255, 255, 255, 0.2);
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.4);
    }
    .theme-title {
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--text-title, #fff);
    }
    .theme-desc {
      font-size: 0.68rem;
      color: var(--text-muted);
      margin-top: 0.15rem;
    }
    .theme-check {
      position: absolute;
      top: 6px;
      right: 8px;
      color: var(--emerald);
      font-weight: 700;
      font-size: 0.85rem;
      display: none;
    }
    .theme-card.active .theme-check {
      display: block;
    }

    /* Custom Sleek Scrollbar */
    ::-webkit-scrollbar {
      width: 7px;
      height: 7px;
    }
    ::-webkit-scrollbar-track {
      background: rgba(0, 0, 0, 0.15);
    }
    ::-webkit-scrollbar-thumb {
      background: var(--border);
      border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
      background: var(--accent);
    }

    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    .loading-spinner {
      display: inline-block;
      width: 0.85rem;
      height: 0.85rem;
      border: 2px solid rgba(255, 255, 255, 0.3);
      border-top-color: currentColor;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      vertical-align: middle;
      margin-right: 0.35rem;
    }
  </style>
</head>
<body>
  <div class="app-layout">
    <div class="top-bar-area">
      <div class="header">
        <div class="brand">
          <div class="brand-icon">📂</div>
          <div>
            <div class="brand-title" style="display: flex; align-items: center; gap: 0.5rem;">Media Sorter <span style="font-size: 0.72rem; font-weight: 600; vertical-align: middle; background: rgba(56, 189, 248, 0.18); color: var(--accent); border: 1px solid rgba(56, 189, 248, 0.4); padding: 0.12rem 0.5rem; border-radius: 9999px;">__VERSION_PLACEHOLDER__</span></div>
            <div class="brand-subtitle">Automated Downloads Organizer (Movies & Shows)</div>
          </div>
        </div>
        <div class="header-actions">
          <label style="display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.82rem; color: var(--text-muted); cursor: pointer; padding: 0 0.5rem;">
            <input type="checkbox" id="auto-refresh-chk" onchange="toggleAutoRefresh(this.checked)"> Auto-refresh (5s)
          </label>
          <button class="btn btn-emerald" id="btn-sort-live-dashboard" onclick="triggerRun(false)">⚡ Run Sort Now (Live)</button>
          <button class="btn btn-accent" onclick="triggerRun(true)">🔍 Preview Sort (Dry-Run)</button>
          <button class="btn btn-amber" onclick="triggerRollback()" title="Undo latest sorted batch">⏮ Undo Changes</button>
          <button class="btn btn-outline" style="border-color: var(--amber); color: var(--amber);" onclick="triggerRollbackAll()" title="Undo all sorted changes">⏪ Undo All Changes</button>
          <button class="btn btn-outline" onclick="addSampleDownloads()">🧪 Add Test Samples</button>
          <button class="btn btn-outline" style="border-color: var(--accent); color: var(--accent); font-weight: 700;" onclick="switchTab('settings')">⚙️ Settings & .env</button>
          <button class="btn btn-outline" onclick="handleUpdate()">🔄 Update</button>
        </div>
      </div>

      <div class="nav-tabs">
        <div class="nav-tab active" id="nav-dashboard" onclick="switchTab('dashboard')">Dashboard & Activity</div>
        <div class="nav-tab" id="nav-files" onclick="switchTab('files')">Folder Explorer</div>
        <div class="nav-tab" id="nav-library" onclick="switchTab('library')">📚 Library</div>
        <div class="nav-tab" id="nav-quarantine" onclick="switchTab('quarantine')">Quarantine Review <span id="quar-badge" class="tag tag-quarantine" style="display:none; margin-left:4px;">0</span></div>
        <div class="nav-tab" id="nav-settings" onclick="switchTab('settings')">Settings & .env</div>
      </div>
    </div>

    <!-- MAIN SCROLLABLE VIEWPORT (Content scrolls without moving top header) -->
    <div class="main-scroll-viewport">

  <!-- TAB 1: DASHBOARD -->
  <div id="tab-dashboard">
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Downloads Folder</div>
        <div class="stat-val" style="font-size: 1.1rem; color: var(--accent);" id="stat-downloads">-</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Movies Destination</div>
        <div class="stat-val" style="font-size: 1.1rem; color: var(--emerald);" id="stat-movies">-</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Shows Destination</div>
        <div class="stat-val" style="font-size: 1.1rem; color: var(--indigo);" id="stat-shows">-</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Default Mode</div>
        <div class="stat-val" id="stat-mode">-</div>
      </div>
    </div>

    <!-- Live Execution Results Preview -->
    <div id="panel-run-results" class="panel" style="display: none; border-color: var(--accent); margin-bottom: 2rem;">
      <div class="panel-header">
        <div class="panel-title" id="run-results-title">⚡ Run Execution Plan</div>
        <span id="run-results-summary" style="font-size: 0.85rem; color: var(--text-muted);"></span>
      </div>
      <div class="show-table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Source File</th>
              <th>Type</th>
              <th>Confidence</th>
              <th>Destination Path</th>
            </tr>
          </thead>
          <tbody id="run-results-tbody"></tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Activity & Batch History</div>
        <div style="display: flex; gap: 0.5rem; align-items: center;">
          <button class="btn btn-outline btn-sm" style="color: var(--amber); border-color: var(--amber);" onclick="triggerRollbackAll()">⏪ Undo All Changes</button>
          <button class="btn btn-outline btn-sm" style="color: var(--rose); border-color: var(--rose);" onclick="clearBatchHistory()">🗑️ Clear History</button>
          <button class="btn btn-outline btn-sm" onclick="loadDashboard()">Refresh</button>
        </div>
      </div>
      <div class="show-table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Batch ID</th>
              <th>Date & Time</th>
              <th>Type</th>
              <th>Status</th>
              <th>Total Files</th>
              <th>Organized</th>
              <th>Quarantined</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="batches-tbody">
            <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Loading history...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 2: FOLDER EXPLORER (DOWNLOADS) -->
  <div id="tab-files" style="display: none;">
    <div class="panel">
      <div class="panel-header" style="flex-wrap: wrap; gap: 0.75rem;">
        <div>
          <div class="panel-title" style="display: flex; align-items: center; gap: 0.65rem;">
            <span>📥 Downloads Folder</span>
            <span id="downloads-total-badge" class="tag tag-movie" style="font-size: 0.8rem;">0 files</span>
            <span id="shows-detected-badge" class="tag tag-show" style="font-size: 0.8rem; display: none;">0 shows</span>
          </div>
          <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.3rem;" id="path-downloads"></p>
        </div>
        <div style="display: flex; gap: 0.5rem; align-items: center;">
          <button class="btn btn-outline btn-sm" onclick="loadFiles()">🔄 Refresh</button>
          <button class="btn btn-accent btn-sm" onclick="triggerRun(true)">🔍 Preview Sort</button>
          <button class="btn btn-emerald btn-sm" id="btn-sort-all-files" onclick="triggerRun(false)">⚡ Sort All Files</button>
        </div>
      </div>

      <!-- Shows toolbar: Expand / Collapse All -->
      <div id="shows-toolbar" style="display: none; justify-content: space-between; align-items: center; margin: 0.75rem 0 1rem 0; padding: 0.5rem 0.85rem; background: rgba(255,255,255,0.02); border-radius: 0.375rem; border: 1px solid var(--border);">
        <span style="font-size: 0.82rem; color: var(--text-muted);">
          📁 Shows categorized in downloads: <strong id="toolbar-show-count" style="color: var(--text-title, #fff);">0</strong>
        </span>
        <div style="display: flex; gap: 0.4rem;">
          <button class="btn btn-outline btn-sm" style="font-size: 0.75rem; padding: 0.2rem 0.6rem;" onclick="toggleAllShowDropdowns(true)">Expand All</button>
          <button class="btn btn-outline btn-sm" style="font-size: 0.75rem; padding: 0.2rem 0.6rem;" onclick="toggleAllShowDropdowns(false)">Collapse All</button>
        </div>
      </div>

      <!-- Container for Detected Show Dropdowns -->
      <div id="downloads-shows-container">
        <!-- Injected dynamically -->
      </div>

      <!-- Container for Unsure Groups (Shared Subfolders & Common Name Prefixes) -->
      <div id="downloads-unsure-container" style="display: none; margin-top: 1.5rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem; flex-wrap: wrap; gap: 0.5rem;">
          <h4 style="font-size: 0.95rem; font-weight: 600; color: var(--text-title, #fff); margin: 0; display: flex; align-items: center; gap: 0.5rem;">
            <span>📁 Unsure Groups (Shared Subfolders & Matching Names)</span>
            <span id="unsure-groups-count-badge" class="tag tag-amber">0 groups</span>
          </h4>
          <span style="font-size: 0.78rem; color: var(--text-muted);">
            Grouped by shared folder or name. Expand any group to sort or set show/movie details.
          </span>
        </div>
        <div id="downloads-unsure-list">
          <!-- Injected dynamically -->
        </div>
      </div>

      <!-- Container for Other / Standalone Files -->
      <div id="downloads-singles-container" style="display: none; margin-top: 1.5rem;">
        <h4 style="font-size: 0.95rem; font-weight: 600; color: var(--text-title, #fff); margin-bottom: 0.65rem; display: flex; align-items: center; gap: 0.5rem;">
          <span>📄 Other Downloads (Movies & Standalone Files)</span>
          <span id="singles-count-badge" class="tag tag-dry">0</span>
        </h4>
        <div class="show-table-wrapper">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Detected Type</th>
                <th>Believed Title</th>
                <th>Size</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="downloads-singles-tbody"></tbody>
          </table>
        </div>
      </div>

      <!-- Empty state -->
      <div id="downloads-empty" style="display: none; text-align: center; padding: 3rem 1rem; color: var(--text-muted);">
        <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">📂</div>
        <div style="font-size: 1.05rem; font-weight: 500; color: var(--text-title, #fff);">No files in Downloads folder</div>
        <p style="font-size: 0.85rem; margin-top: 0.25rem;">New downloaded media will appear here ready to be categorized and organized.</p>
        <button class="btn btn-outline btn-sm" style="margin-top: 0.75rem;" onclick="addSampleDownloads()">Add Test Samples</button>
      </div>
    </div>
  </div>

  <!-- TAB: LIBRARY CATALOG -->
  <div id="tab-library" style="display: none;">
    <div class="panel">
      <div class="panel-header" style="flex-wrap: wrap; gap: 0.75rem;">
        <div>
          <div class="panel-title" style="display: flex; align-items: center; gap: 0.65rem;">
            <span>📚 Media Library</span>
            <span id="lib-badge-shows" class="tag tag-show">0 Shows</span>
            <span id="lib-badge-movies" class="tag tag-movie">0 Movies</span>
          </div>
          <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.3rem;">
            Shows and movies in your library catalog. When new incoming downloads match a known show, they are automatically routed into that show's folder.
          </p>
        </div>
        <div style="display: flex; gap: 0.5rem; align-items: center;">
          <button class="btn btn-outline btn-sm" id="btn-library-rescan" onclick="rescanLibraryDisk()">🔄 Rescan Disk Library</button>
        </div>
      </div>

      <!-- Filter toolbar with Shows/Movies selector & Search -->
      <div style="display: flex; gap: 0.75rem; align-items: center; justify-content: space-between; margin: 1rem 0; flex-wrap: wrap;">
        <div style="display: flex; gap: 0.5rem;" id="library-type-selectors">
          <button type="button" id="lib-filter-all" class="btn btn-outline btn-sm" onclick="setLibraryFilter('all')">📂 All (<span id="lib-cnt-all">0</span>)</button>
          <button type="button" id="lib-filter-tv" class="btn btn-emerald btn-sm" onclick="setLibraryFilter('tv')">📺 Shows (<span id="lib-cnt-tv">0</span>)</button>
          <button type="button" id="lib-filter-movie" class="btn btn-outline btn-sm" onclick="setLibraryFilter('movie')">🎬 Movies (<span id="lib-cnt-movie">0</span>)</button>
        </div>
        <div style="min-width: 260px; flex: 1; max-width: 380px;">
          <input type="text" id="lib-search-input" class="form-control" placeholder="🔍 Search library titles..." oninput="onLibrarySearchChange(this.value)">
        </div>
      </div>

      <!-- Library Grid / List -->
      <div id="library-items-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem;">
        <!-- Injected dynamically -->
      </div>

      <!-- Library Empty State -->
      <div id="library-empty" style="display: none; text-align: center; padding: 3rem 1rem; color: var(--text-muted);">
        <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">📚</div>
        <div style="font-size: 1.05rem; font-weight: 500; color: var(--text-title, #fff);">No library items found</div>
        <p style="font-size: 0.85rem; margin-top: 0.25rem;">Click "Rescan Disk Library" above to scan your drives and discover existing shows and movies.</p>
      </div>
    </div>
  </div>

  <!-- TAB 3: QUARANTINE REVIEW -->
  <div id="tab-quarantine" style="display: none;">
    <div class="panel">
      <div class="panel-header" style="flex-wrap: wrap; gap: 0.75rem;">
        <div>
          <div class="panel-title" style="display: flex; align-items: center; gap: 0.65rem;">
            <span>🛡️ Review & Quarantine Queue</span>
            <span id="quar-pending-count-badge" class="tag tag-quarantine" style="font-size: 0.8rem; display: none;">0</span>
          </div>
          <p style="font-size: 0.82rem; color: var(--text-muted); margin-top: 0.3rem;">
            Files with confidence lower than your threshold are held safely here. Perform manual actions individually or using top buttons.
          </p>
        </div>
        <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
          <button class="btn btn-outline btn-sm" onclick="loadQuarantine()">🔄 Refresh</button>
          <button class="btn btn-accent btn-sm" id="quar-btn-top-movie" onclick="handleTopQuarantineAction('movie')" title="Quick move selected (or all) quarantined files to Movies">🎬 Move to Movies</button>
          <button class="btn btn-emerald btn-sm" id="quar-btn-top-tv" onclick="handleTopQuarantineAction('tv')" title="Quick move selected (or all) quarantined files to TV Shows">📺 Move to Shows</button>
          <button class="btn btn-outline btn-sm" id="quar-btn-top-manual" onclick="handleTopQuarantineManual()" title="Manually specify title, season, or movie details">✏️ Set Show/Movie</button>
          <button class="btn btn-outline btn-sm" id="quar-btn-top-unflag" style="color: var(--amber); border-color: var(--amber);" onclick="handleTopQuarantineUnflag()" title="Unflag selected (or all) items from quarantine">↩️ Unflag</button>
          <button class="btn btn-outline btn-sm" id="quar-btn-top-undo-all" style="color: var(--rose); border-color: var(--rose); display: none;" onclick="undoAllResolvedQuarantine()" title="Undo all resolved items and restore files to source">↩️ Undo All Resolved</button>
        </div>
      </div>

      <!-- Batch Selection Toolbar -->
      <div id="quar-selection-bar" style="display: none; justify-content: space-between; align-items: center; margin: 0 0 1rem 0; padding: 0.5rem 0.85rem; background: rgba(255,255,255,0.03); border-radius: 0.375rem; border: 1px solid var(--border); flex-wrap: wrap; gap: 0.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem;">
          <label style="display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; cursor: pointer; color: var(--text-title, #fff);">
            <input type="checkbox" id="quar-select-all" onchange="toggleSelectAllQuarantine(this.checked)" style="accent-color: var(--accent); cursor: pointer;">
            <span>Select All (<span id="quar-total-count-text">0</span>)</span>
          </label>
          <span id="quar-selected-badge" class="tag tag-movie" style="font-size: 0.75rem; display: none;">0 selected</span>
        </div>
        <div style="display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;">
          <span style="font-size: 0.75rem; color: var(--text-muted); margin-right: 0.2rem;">Batch Actions:</span>
          <button class="btn btn-accent btn-sm" style="font-size: 0.75rem; padding: 0.25rem 0.65rem;" onclick="handleTopQuarantineAction('movie')">🎬 Move to Movies</button>
          <button class="btn btn-emerald btn-sm" style="font-size: 0.75rem; padding: 0.25rem 0.65rem;" onclick="handleTopQuarantineAction('tv')">📺 Move to Shows</button>
          <button class="btn btn-outline btn-sm" style="font-size: 0.75rem; padding: 0.25rem 0.65rem;" onclick="handleTopQuarantineManual()">✏️ Set Show/Movie</button>
          <button class="btn btn-outline btn-sm" style="font-size: 0.75rem; padding: 0.25rem 0.65rem; color: var(--amber); border-color: var(--amber);" onclick="handleTopQuarantineUnflag()">↩️ Unflag</button>
        </div>
      </div>

      <div class="show-table-wrapper">
        <table>
          <thead>
            <tr>
              <th style="width: 38px; text-align: center;">
                <input type="checkbox" id="quar-th-checkbox" onchange="toggleSelectAllQuarantine(this.checked)" style="accent-color: var(--accent); cursor: pointer;" title="Select / Deselect all">
              </th>
              <th>File Name</th>
              <th>Reason</th>
              <th>Confidence</th>
              <th>Date Added</th>
              <th>Manual Action</th>
            </tr>
          </thead>
          <tbody id="quarantine-tbody">
            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Quarantine queue is empty. Flagged files will appear here without being moved.</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Recently Resolved Files Section with Undo All -->
      <div id="quarantine-resolved-section" style="margin-top: 2rem; display: none;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem; flex-wrap: wrap; gap: 0.5rem;">
          <h4 style="font-size: 0.95rem; font-weight: 600; color: var(--text-title, #fff); margin: 0; display: flex; align-items: center; gap: 0.5rem;">
            <span>✅ Recently Resolved Files</span>
            <span id="resolved-count-badge" class="tag tag-live">0</span>
          </h4>
          <button class="btn btn-amber btn-sm" onclick="undoAllResolvedQuarantine()" title="Undo all resolved items and move them back to their original source folders">↩️ Undo All Resolved</button>
        </div>
        <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.75rem;">
          Need to revert a resolved item? Click "Undo" on an individual item or "Undo All Resolved" above to restore files back to their source locations.
        </p>
        <div class="show-table-wrapper">
          <table>
            <thead>
              <tr>
                <th>File Name</th>
                <th>Category</th>
                <th>Destination</th>
                <th>Resolved Date</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="quarantine-resolved-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 4: SETTINGS & .ENV -->
  <div id="tab-settings" style="display: none;">
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1.5rem; max-width: 1200px;">
      
      <!-- Panel 1: Theme & Interface Preferences -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">🎨 Appearance & Themes</div>
          <span class="tag tag-movie" id="tab-active-theme-tag">Cyber Dark</span>
        </div>
        <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1rem;">
          Select a custom visual theme for your Media Sorter dashboard.
        </p>
        <div class="theme-grid">
          <div class="theme-card active" data-theme-id="cyber-dark" onclick="setTheme('cyber-dark')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #090d16 50%, #38bdf8 50%);"></div>
            <div class="theme-title">Cyber Dark</div>
            <div class="theme-desc">Midnight & Sky Cyan</div>
            <div class="theme-check" id="tab-check-cyber-dark">✓</div>
          </div>
          <div class="theme-card" data-theme-id="oled-neon" onclick="setTheme('oled-neon')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #000000 50%, #ec4899 50%);"></div>
            <div class="theme-title">Midnight OLED</div>
            <div class="theme-desc">True Black & Neon Pink</div>
            <div class="theme-check" id="tab-check-oled-neon">✓</div>
          </div>
          <div class="theme-card" data-theme-id="nord-frost" onclick="setTheme('nord-frost')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #242933 50%, #88c0d0 50%);"></div>
            <div class="theme-title">Nord Arctic</div>
            <div class="theme-desc">Nordic Frost & Slate</div>
            <div class="theme-check" id="tab-check-nord-frost">✓</div>
          </div>
          <div class="theme-card" data-theme-id="dracula" onclick="setTheme('dracula')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #151320 50%, #c4a7e7 50%);"></div>
            <div class="theme-title">Dracula Purple</div>
            <div class="theme-desc">Twilight Violet & Pastel</div>
            <div class="theme-check" id="tab-check-dracula">✓</div>
          </div>
          <div class="theme-card" data-theme-id="emerald-matrix" onclick="setTheme('emerald-matrix')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #050c08 50%, #10b981 50%);"></div>
            <div class="theme-title">Emerald Matrix</div>
            <div class="theme-desc">Obsidian & Vivid Green</div>
            <div class="theme-check" id="tab-check-emerald-matrix">✓</div>
          </div>
          <div class="theme-card" data-theme-id="solar-sunset" onclick="setTheme('solar-sunset')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #100b0b 50%, #f97316 50%);"></div>
            <div class="theme-title">Solar Sunset</div>
            <div class="theme-desc">Warm Charcoal & Amber</div>
            <div class="theme-check" id="tab-check-solar-sunset">✓</div>
          </div>
          <div class="theme-card" data-theme-id="tokyo-night" onclick="setTheme('tokyo-night')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #1a1b26 50%, #7aa2f7 50%);"></div>
            <div class="theme-title">Tokyo Night</div>
            <div class="theme-desc">Deep Indigo & Cyan</div>
            <div class="theme-check" id="tab-check-tokyo-night">✓</div>
          </div>
          <div class="theme-card" data-theme-id="synthwave" onclick="setTheme('synthwave')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #140d22 50%, #d946ef 50%);"></div>
            <div class="theme-title">Synthwave 80s</div>
            <div class="theme-desc">Retro Violet & Pink</div>
            <div class="theme-check" id="tab-check-synthwave">✓</div>
          </div>
          <div class="theme-card" data-theme-id="abyssal-ocean" onclick="setTheme('abyssal-ocean')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #051018 50%, #14b8a6 50%);"></div>
            <div class="theme-title">Abyssal Ocean</div>
            <div class="theme-desc">Deep Marine & Teal</div>
            <div class="theme-check" id="tab-check-abyssal-ocean">✓</div>
          </div>
          <div class="theme-card" data-theme-id="monokai-pro" onclick="setTheme('monokai-pro')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #1d1b1d 50%, #ffd866 50%);"></div>
            <div class="theme-title">Monokai Pro</div>
            <div class="theme-desc">Dark Carbon & Gold</div>
            <div class="theme-check" id="tab-check-monokai-pro">✓</div>
          </div>
          <div class="theme-card" data-theme-id="terminal-crt" onclick="setTheme('terminal-crt')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #020703 50%, #00ff66 50%); border-color: #00ff66;"></div>
            <div class="theme-title">Terminal CRT</div>
            <div class="theme-desc">Retro Monospace & Green CRT</div>
            <div class="theme-check" id="tab-check-terminal-crt">✓</div>
          </div>
          <div class="theme-card" data-theme-id="paper-light" onclick="setTheme('paper-light')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #f8fafc 50%, #2563eb 50%); border-color: #cbd5e1;"></div>
            <div class="theme-title">Paper Light</div>
            <div class="theme-desc">Clean Studio & Pure Light</div>
            <div class="theme-check" id="tab-check-paper-light">✓</div>
          </div>
          <div class="theme-card" data-theme-id="neo-brutalism" onclick="setTheme('neo-brutalism')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #fffdf5 50%, #ffd12d 50%); border: 2px solid #000;"></div>
            <div class="theme-title">Neo-Brutalism</div>
            <div class="theme-desc">High Contrast & Pop Borders</div>
            <div class="theme-check" id="tab-check-neo-brutalism">✓</div>
          </div>
          <div class="theme-card" data-theme-id="aurora-glass" onclick="setTheme('aurora-glass')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #0c0f1d 50%, #a855f7 50%); border-color: rgba(255, 255, 255, 0.3);"></div>
            <div class="theme-title">Aurora Glass</div>
            <div class="theme-desc">Frosted Mesh & Glassmorphism</div>
            <div class="theme-check" id="tab-check-aurora-glass">✓</div>
          </div>
        </div>

        <div style="border-top: 1px solid var(--border); padding-top: 1.25rem; margin-top: 1.5rem;">
          <h4 style="font-size: 0.95rem; font-weight: 600; color: var(--text-title, #fff); margin-bottom: 0.5rem;">⚡ Server Process Control</h4>
          <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.75rem;">
            Restart the server process to reload your environment and PM2 instance cleanly.
          </p>
          <button type="button" class="btn btn-amber" style="width: 100%; justify-content: center;" onclick="triggerServerRestart()">
            🔄 Restart Media Sorter Server
          </button>
        </div>

        <div style="border-top: 1px solid var(--border); padding-top: 1.25rem; margin-top: 1.25rem;">
          <h4 style="font-size: 0.95rem; font-weight: 600; color: var(--text-title, #fff); margin-bottom: 0.5rem;">⏪ Undo All Changes (Rollback All)</h4>
          <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.75rem;">
            Restores all previously organized files across all batches back to their original source locations in downloads.
          </p>
          <button type="button" class="btn btn-outline" style="width: 100%; justify-content: center; color: var(--amber); border-color: var(--amber);" onclick="triggerRollbackAll()">
            ⏪ Undo All Changes Now
          </button>
        </div>

        <div style="border-top: 1px solid var(--border); padding-top: 1.25rem; margin-top: 1.25rem;">
          <h4 style="font-size: 0.95rem; font-weight: 600; color: var(--text-title, #fff); margin-bottom: 0.5rem;">🗃️ Clear Activity & History</h4>
          <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.75rem;">
            Wipes all past batch execution records and operation logs from the local database.
          </p>
          <button type="button" class="btn btn-outline" style="width: 100%; justify-content: center; color: var(--rose); border-color: var(--rose);" onclick="clearBatchHistory()">
            🗑️ Clear History Now
          </button>
        </div>
      </div>

      <!-- Panel 2: .env Configuration Form -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">Configuration (.env)</div>
          <span class="tag tag-show">Active</span>
        </div>
        <form id="settings-form" onsubmit="saveSettings(event)">
          <div class="form-group">
            <label class="form-label">Downloads Folder (Source)</label>
            <input type="text" class="form-control" id="cfg-downloads" required>
          </div>
          <div class="form-group">
            <label class="form-label">Movies Folder (Destination)</label>
            <input type="text" class="form-control" id="cfg-movies" required>
          </div>
          <div class="form-group">
            <label class="form-label">Shows Folder (Destination)</label>
            <input type="text" class="form-control" id="cfg-shows" required>
          </div>
          <div class="form-group">
            <label class="form-label">Safety Mode</label>
            <select class="form-control" id="cfg-dryrun">
              <option value="false">Live Mode (Immediately move/sort files)</option>
              <option value="true">Dry-Run Mode (Preview only, don't move files)</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Confidence Threshold (0.50 - 0.95)</label>
            <input type="number" step="0.05" min="0.5" max="1.0" class="form-control" id="cfg-threshold">
          </div>
          <div class="form-group">
            <label class="form-label">Action Type</label>
            <select class="form-control" id="cfg-action">
              <option value="move">Move</option>
              <option value="copy">Copy</option>
              <option value="link">Symlink</option>
              <option value="hardlink">Hardlink</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Auto-Sort Interval (seconds, 0 = manual only)</label>
            <input type="number" step="10" min="0" max="86400" class="form-control" id="cfg-interval" placeholder="0 = manual, 60 = every minute, 300 = every 5 mins">
          </div>
          <div class="form-group">
            <label class="form-label" style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer;">
              <input type="checkbox" id="cfg-cleanup" checked style="width: 1.1rem; height: 1.1rem; accent-color: var(--accent); cursor: pointer;">
              <span>🧹 Clean up empty folders after moving files</span>
            </label>
            <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem; margin-left: 1.6rem;">
              Automatically removes empty directories left behind in the downloads folder after files are organized.
            </p>
          </div>
          <div class="form-group">
            <label class="form-label" style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer;">
              <input type="checkbox" id="cfg-rename" checked style="width: 1.1rem; height: 1.1rem; accent-color: var(--accent); cursor: pointer;" onchange="document.getElementById('rename-patterns-box').style.display = this.checked ? 'block' : 'none'">
              <span>🏷️ Rename files when organizing</span>
            </label>
            <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem; margin-left: 1.6rem;">
              When enabled, organizes and renames files using your custom patterns. When disabled, original filenames are preserved.
            </p>
          </div>
          <div id="rename-patterns-box" style="border: 1px solid var(--border); border-radius: var(--radius-md); padding: 1rem; margin-bottom: 1.25rem; background: rgba(0,0,0,0.15);">
            <div class="form-group" style="margin-bottom: 1rem;">
              <label class="form-label">TV Show Renaming Pattern</label>
              <input type="text" class="form-control" id="cfg-tv-template" placeholder="{title}/Season {season:02d}/{show_name}_{season_episode}.{ext}">
              <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.35rem;">
                Default: <code>&lt;SHOW_NAME&gt;_&lt;SEASON_EPISODE&gt;</code> (e.g. <code>{title}/Season {season:02d}/{show_name}_{season_episode}.{ext}</code>)<br>
                Available tags: <code>&lt;SHOW_NAME&gt;</code>, <code>&lt;SEASON_EPISODE&gt;</code>, <code>{show_name}</code>, <code>{season_episode}</code>, <code>{title}</code>, <code>{season:02d}</code>, <code>{episode:02d}</code>, <code>{episode_title}</code>, <code>{ext}</code>
              </p>
            </div>
            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label">Movie Renaming Pattern</label>
              <input type="text" class="form-control" id="cfg-movie-template" placeholder="{title} ({year})/{movie_name}.{ext}">
              <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.35rem;">
                Default: <code>&lt;MOVIE_NAME&gt;</code> (e.g. <code>{title} ({year})/{movie_name}.{ext}</code>)<br>
                Available tags: <code>&lt;MOVIE_NAME&gt;</code>, <code>{movie_name}</code>, <code>{title}</code>, <code>{year}</code>, <code>{resolution}</code>, <code>{codec}</code>, <code>{ext}</code>
              </p>
            </div>
          </div>
          <div style="display: flex; gap: 0.75rem; align-items: center; margin-top: 1.5rem;">
            <button type="submit" class="btn btn-emerald">💾 Save to .env</button>
          </div>
        </form>
      </div>

    </div>
  </div>

    </div> <!-- End .main-scroll-viewport -->
  </div> <!-- End .app-layout -->

  <!-- SETTINGS & THEMES MODAL -->
  <div id="modal-settings" class="modal-backdrop" style="display: none;" onclick="if(event.target===this) closeSettingsModal()">
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-title" style="display: flex; align-items: center; gap: 0.5rem;">
          <span>⚙️ Preferences & Settings</span>
        </div>
        <button class="modal-close" onclick="closeSettingsModal()">&times;</button>
      </div>

      <!-- 1. THEMES SECTION -->
      <div class="form-group">
        <label class="form-label" for="theme-select" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem;">
          <span>🎨 Color Theme</span>
          <span style="font-size: 0.75rem; color: var(--text-muted);" id="active-theme-label">Cyber Dark</span>
        </label>
        <select id="theme-select" class="form-control" onchange="setTheme(this.value)" style="padding: 0.65rem 0.85rem; font-size: 0.9rem; font-weight: 500; cursor: pointer; border-radius: var(--radius-sm, 0.375rem);">
          <option value="cyber-dark">Cyber Dark — Midnight & Sky Cyan</option>
          <option value="oled-neon">Midnight OLED — True Black & Neon Pink</option>
          <option value="nord-frost">Nord Arctic — Nordic Frost & Slate</option>
          <option value="dracula">Dracula Purple — Twilight Violet & Pastel</option>
          <option value="emerald-matrix">Emerald Matrix — Obsidian & Vivid Green</option>
          <option value="solar-sunset">Solar Sunset — Warm Charcoal & Amber</option>
          <option value="tokyo-night">Tokyo Night — Deep Indigo & Cyan</option>
          <option value="synthwave">Synthwave 80s — Retro Violet & Pink</option>
          <option value="abyssal-ocean">Abyssal Ocean — Deep Marine & Teal</option>
          <option value="monokai-pro">Monokai Pro — Dark Carbon & Gold</option>
          <option value="terminal-crt">Terminal CRT — Retro Monospace & Green CRT</option>
          <option value="paper-light">Paper Light — Clean Studio & Pure Light</option>
          <option value="neo-brutalism">Neo-Brutalism — High Contrast & Pop Borders</option>
          <option value="aurora-glass">Aurora Glass — Frosted Mesh & Glassmorphism</option>
          <option value="catppuccin-mocha">Catppuccin Mocha — Warm Pastel & Rosewater</option>
          <option value="rose-pine">Rosé Pine — Muted Rose & Twilight</option>
          <option value="gruvbox-dark">Gruvbox Dark — Earthy Retro & Warm Orange</option>
          <option value="solarized-dark">Solarized Dark — Scientific Blue & Yellow</option>
          <option value="nightowl">Nightowl — Deep Navy & Coral</option>
          <option value="vesper">Vesper — Warm Noir & Copper</option>
        </select>
      </div>

      <!-- 2. SERVER CONTROL SECTION -->
      <div class="form-group" style="border-top: 1px solid var(--border); padding-top: 1.25rem;">
        <label class="form-label">⚡ Server Lifecycle & Process</label>
        <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.75rem;">
          Gracefully terminates the server process. PM2 will immediately restart the process with any updated settings or code.
        </p>
        <button type="button" class="btn btn-amber" style="width: 100%; justify-content: center;" onclick="closeSettingsModal(); triggerServerRestart();">
          🔄 Restart Media Sorter Server
        </button>
      </div>

      <!-- 3. HISTORY & DATABASE SECTION -->
      <div class="form-group" style="border-top: 1px solid var(--border); padding-top: 1.25rem;">
        <label class="form-label">🗃️ Activity & Batch History</label>
        <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.75rem;">
          Clear recorded batch entries and operation logs from SQLite WAL database.
        </p>
        <button type="button" class="btn btn-outline" style="width: 100%; justify-content: center; color: var(--rose); border-color: var(--rose);" onclick="clearBatchHistory()">
          🗑️ Clear Batch & Activity History
        </button>
      </div>

      <!-- 4. FOOTER -->
      <div style="border-top: 1px solid var(--border); padding-top: 1rem; display: flex; justify-content: space-between; align-items: center;">
        <button type="button" class="btn btn-outline btn-sm" onclick="closeSettingsModal(); switchTab('settings');">
          ⚙️ Edit Full .env Settings
        </button>
        <button type="button" class="btn btn-accent btn-sm" onclick="closeSettingsModal()">Close</button>
      </div>
    </div>
  </div>

  <!-- MANUAL SORT / CATEGORIZE MODAL -->
  <div id="modal-manual-sort" class="modal-backdrop" style="display: none;" onclick="if(event.target===this) closeManualModal()">
    <div class="modal-content" style="max-width: 540px;">
      <div class="modal-header">
        <div class="modal-title" style="display: flex; align-items: center; gap: 0.5rem;">
          <span>✏️ Manually Set Show / Movie</span>
        </div>
        <button class="modal-close" onclick="closeManualModal()">&times;</button>
      </div>

      <div id="manual-modal-file-select-container" style="display: none; margin-bottom: 1.25rem;">
        <label class="form-label" style="margin-bottom: 0.25rem; font-size: 0.75rem;">Select Quarantined File</label>
        <select id="manual-modal-file-select" class="form-control" onchange="onManualModalFileSelectChange(this.value)"></select>
      </div>

      <div id="manual-modal-single-file-container" style="margin-bottom: 1.25rem;">
        <label class="form-label" style="margin-bottom: 0.25rem; font-size: 0.75rem;">Selected File</label>
        <div id="manual-modal-filename" style="font-family: monospace; font-size: 0.85rem; padding: 0.6rem 0.85rem; background: rgba(0,0,0,0.3); border-radius: var(--radius-sm); word-break: break-all; border: 1px solid var(--border);"></div>
      </div>

      <div style="margin-bottom: 1.25rem;">
        <label class="form-label" style="margin-bottom: 0.4rem; font-size: 0.8rem;">Select Media Type</label>
        <div style="display: flex; gap: 0.75rem;">
          <button type="button" id="manual-btn-movie" class="btn btn-accent" style="flex: 1; justify-content: center; font-weight: 600;" onclick="toggleManualCat('movie')">🎬 Movie</button>
          <button type="button" id="manual-btn-tv" class="btn btn-outline" style="flex: 1; justify-content: center; font-weight: 600;" onclick="toggleManualCat('tv')">📺 TV Show</button>
        </div>
      </div>

      <div class="form-group" style="margin-bottom: 1rem;">
        <label class="form-label" id="manual-title-label">Movie Title <span style="color: var(--rose);">*</span></label>
        <input type="text" class="form-control" id="manual-input-title" placeholder="e.g. Inception or The Dark Knight" oninput="updateManualPreview()">
      </div>

      <div id="manual-fields-movie" style="margin-bottom: 1rem;">
        <div class="form-group" style="margin-bottom: 0;">
          <label class="form-label">Release Year (Optional)</label>
          <input type="number" class="form-control" id="manual-input-year" placeholder="e.g. 2010" min="1900" max="2099" oninput="updateManualPreview()">
        </div>
      </div>

      <div id="manual-fields-tv" style="display: none; margin-bottom: 1rem;">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Season Number</label>
            <input type="number" class="form-control" id="manual-input-season" placeholder="1" min="1" max="999" value="1" oninput="updateManualPreview()">
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Episode Number</label>
            <input type="number" class="form-control" id="manual-input-episode" placeholder="1" min="1" max="999" value="1" oninput="updateManualPreview()">
          </div>
        </div>
      </div>

      <div style="margin-bottom: 1.25rem;">
        <label class="form-label" style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.25rem;">Destination Preview</label>
        <div id="manual-modal-preview" style="font-family: monospace; font-size: 0.8rem; color: var(--emerald); padding: 0.6rem 0.85rem; background: rgba(0,0,0,0.3); border-radius: var(--radius-sm); word-break: break-all; border: 1px dashed var(--border);">
          Enter title above to preview destination...
        </div>
      </div>

      <div style="display: flex; gap: 0.75rem; justify-content: flex-end; border-top: 1px solid var(--border); padding-top: 1rem;">
        <button type="button" class="btn btn-outline btn-sm" onclick="closeManualModal()">Cancel</button>
        <button type="button" class="btn btn-emerald btn-sm" id="manual-submit-btn" onclick="submitManualResolution()">⚡ Organize File</button>
      </div>
    </div>
  </div>

  <div id="toast" class="toast"></div>

  <script>
    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 3500);
    }

    const THEMES = [
      { id: 'cyber-dark', name: 'Cyber Dark', desc: 'Midnight & Sky Cyan' },
      { id: 'oled-neon', name: 'Midnight OLED', desc: 'True Black & Neon Pink' },
      { id: 'nord-frost', name: 'Nord Arctic', desc: 'Nordic Frost & Slate' },
      { id: 'dracula', name: 'Dracula Purple', desc: 'Twilight Violet & Pastel' },
      { id: 'emerald-matrix', name: 'Emerald Matrix', desc: 'Obsidian & Vivid Green' },
      { id: 'solar-sunset', name: 'Solar Sunset', desc: 'Warm Charcoal & Amber' },
      { id: 'tokyo-night', name: 'Tokyo Night', desc: 'Deep Indigo & Cyan' },
      { id: 'synthwave', name: 'Synthwave 80s', desc: 'Retro Violet & Pink' },
      { id: 'abyssal-ocean', name: 'Abyssal Ocean', desc: 'Deep Marine & Teal' },
      { id: 'monokai-pro', name: 'Monokai Pro', desc: 'Dark Carbon & Gold' },
      { id: 'terminal-crt', name: 'Terminal CRT', desc: 'Retro Monospace & Green CRT' },
      { id: 'paper-light', name: 'Paper Light', desc: 'Clean Studio & Pure Light' },
      { id: 'neo-brutalism', name: 'Neo-Brutalism', desc: 'High Contrast & Pop Borders' },
      { id: 'aurora-glass', name: 'Aurora Glass', desc: 'Frosted Mesh & Glassmorphism' },
      { id: 'catppuccin-mocha', name: 'Catppuccin Mocha', desc: 'Warm Pastel & Rosewater' },
      { id: 'rose-pine', name: 'Rosé Pine', desc: 'Muted Rose & Twilight' },
      { id: 'gruvbox-dark', name: 'Gruvbox Dark', desc: 'Earthy Retro & Warm Orange' },
      { id: 'solarized-dark', name: 'Solarized Dark', desc: 'Scientific Blue & Yellow' },
      { id: 'nightowl', name: 'Nightowl', desc: 'Deep Navy & Coral' },
      { id: 'vesper', name: 'Vesper', desc: 'Warm Noir & Copper' },
    ];

    function setTheme(themeId) {
      const found = THEMES.find(t => t.id === themeId);
      if (!found) themeId = 'cyber-dark';
      document.documentElement.setAttribute('data-theme', themeId);
      document.body.setAttribute('data-theme', themeId);
      try {
        localStorage.setItem('ms-theme', themeId);
      } catch (e) {}

      const activeThemeObj = THEMES.find(t => t.id === themeId) || THEMES[0];
      const modalLabel = document.getElementById('active-theme-label');
      if (modalLabel) modalLabel.textContent = activeThemeObj.name;
      const tabTag = document.getElementById('tab-active-theme-tag');
      if (tabTag) tabTag.textContent = activeThemeObj.name;

      document.querySelectorAll('.theme-card').forEach(card => {
        const tid = card.getAttribute('data-theme-id');
        if (tid === themeId) {
          card.classList.add('active');
        } else {
          card.classList.remove('active');
        }
      });

      document.querySelectorAll('.theme-check').forEach(chk => {
        chk.style.display = 'none';
      });
      const tChk = document.getElementById(`tab-check-${themeId}`);
      if (tChk) tChk.style.display = 'block';
      const themeSelect = document.getElementById('theme-select');
      if (themeSelect) themeSelect.value = themeId;
    }

    function openSettingsModal() {
      switchTab('settings');
    }

    function closeSettingsModal() {
      const modal = document.getElementById('modal-settings');
      if (modal) modal.style.display = 'none';
    }

    async function clearBatchHistory() {
      if (!confirm('Are you sure you want to clear all activity and batch history?')) return;
      try {
        const res = await fetch('/api/batches/clear', { method: 'POST' });
        const data = await res.json();
        showToast(data.message || 'Activity and batch history cleared.');
        loadDashboard();
      } catch (e) {
        showToast('Error clearing history: ' + e);
      }
    }

    function switchTab(tab) {
      document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
      const d = document.getElementById('tab-dashboard'); if (d) d.style.display = 'none';
      const f = document.getElementById('tab-files'); if (f) f.style.display = 'none';
      const l = document.getElementById('tab-library'); if (l) l.style.display = 'none';
      const q = document.getElementById('tab-quarantine'); if (q) q.style.display = 'none';
      const s = document.getElementById('tab-settings'); if (s) s.style.display = 'none';

      const target = document.getElementById('tab-' + tab);
      if (target) target.style.display = 'block';
      const nav = document.getElementById('nav-' + tab);
      if (nav) nav.classList.add('active');

      if (tab === 'dashboard') loadDashboard();
      if (tab === 'files') loadFiles();
      if (tab === 'library') loadLibrary();
      if (tab === 'quarantine') loadQuarantine();
      if (tab === 'settings') loadSettings();
    }

    async function loadDashboard() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        document.getElementById('stat-downloads').textContent = data.downloads_dir;
        document.getElementById('stat-movies').textContent = data.movies_dir;
        document.getElementById('stat-shows').textContent = data.shows_dir;
        document.getElementById('stat-mode').innerHTML = data.dry_run 
          ? '<span class="tag tag-dry">Dry-Run Preview</span>' 
          : '<span class="tag tag-live">Live Sorting</span>';

        if (data.pending_quarantine > 0) {
          const b = document.getElementById('quar-badge');
          b.textContent = data.pending_quarantine;
          b.style.display = 'inline-block';
        } else {
          document.getElementById('quar-badge').style.display = 'none';
        }

        const bRes = await fetch('/api/batches');
        const batches = await bRes.json();
        const tbody = document.getElementById('batches-tbody');
        tbody.innerHTML = '';
        if (batches.length === 0) {
          tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No batches recorded yet.</td></tr>';
        } else {
          batches.forEach(b => {
            const tr = document.createElement('tr');
            let actionHtml = '<span style="color: var(--text-muted); font-size: 0.8rem;">-</span>';
            if (!b.dry_run && b.status === 'COMPLETED') {
              actionHtml = `<button class="btn btn-amber btn-sm" onclick="triggerRollbackBatch('${b.id}')">↩ Rollback</button>`;
            } else if (b.status === 'ROLLED_BACK') {
              actionHtml = '<span style="color: var(--emerald); font-size: 0.8rem;">✓ Reverted</span>';
            } else if (b.dry_run) {
              actionHtml = '<span style="color: var(--text-muted); font-size: 0.8rem;">Preview</span>';
            }
            tr.innerHTML = `
              <td><code>${b.id.substring(0,8)}</code></td>
              <td>${b.created_at || '-'}</td>
              <td><span class="tag ${b.dry_run ? 'tag-dry' : 'tag-live'}">${b.dry_run ? 'Dry-Run' : 'Live'}</span></td>
              <td><span class="tag ${b.status === 'COMPLETED' ? 'tag-live' : (b.status === 'ROLLED_BACK' ? 'tag-dry' : 'tag-quarantine')}">${b.status}</span></td>
              <td>${b.total_files}</td>
              <td>${b.moved_files}</td>
              <td>${b.quarantined_files}</td>
              <td>${actionHtml}</td>
            `;
            tbody.appendChild(tr);
          });
        }
      } catch (e) {
        console.error(e);
      }
    }

    async function triggerRun(dryRun) {
      const btnAll = document.getElementById('btn-sort-all-files');
      const btnDash = document.getElementById('btn-sort-live-dashboard');
      const origAllText = btnAll ? btnAll.innerHTML : '';
      const origDashText = btnDash ? btnDash.innerHTML : '';

      if (btnAll) {
        btnAll.disabled = true;
        btnAll.innerHTML = `<span class="loading-spinner"></span> Sorting...`;
      }
      if (btnDash) {
        btnDash.disabled = true;
        btnDash.innerHTML = `<span class="loading-spinner"></span> Sorting...`;
      }

      showToast(dryRun ? 'Running Dry-Run Preview...' : 'Executing Live Sorting...');
      try {
        const res = await fetch('/api/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dry_run: dryRun })
        });
        const data = await res.json();
        showToast(dryRun ? `Preview complete: ${data.total_files} files scanned` : `Live sort finished: ${data.moved_files} files organized`);

        // Show results panel
        const panel = document.getElementById('panel-run-results');
        if (panel) {
          panel.style.display = 'block';
          document.getElementById('run-results-title').textContent = dryRun ? '🔍 Dry-Run Preview Results' : '⚡ Live Execution Results';
          document.getElementById('run-results-summary').textContent = `Total: ${data.total_files} | Moved: ${data.moved_files} | Quarantined: ${data.quarantined_files} | Skipped: ${data.skipped_files}`;

          const tbody = document.getElementById('run-results-tbody');
          tbody.innerHTML = '';
          if (data.operations.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="color: var(--text-muted); text-align: center;">No files found in downloads folder to sort.</td></tr>';
          } else {
            data.operations.forEach(op => {
              const tr = document.createElement('tr');
              const catTag = op.category === 'movie' ? 'tag-movie' : (op.category === 'tv' ? 'tag-show' : 'tag-quarantine');
              tr.innerHTML = `
                <td><code>${op.src}</code></td>
                <td><span class="tag ${catTag}">${op.category.toUpperCase()}</span></td>
                <td>${op.confidence}%</td>
                <td style="font-size: 0.8rem; color: var(--text-muted);">${op.dst}</td>
              `;
              tbody.appendChild(tr);
            });
          }
        }

        await Promise.all([loadDashboard(), loadFiles(), loadQuarantine()]);
      } catch (e) {
        showToast('Error executing run: ' + e);
      } finally {
        if (btnAll) {
          btnAll.disabled = false;
          btnAll.innerHTML = origAllText;
        }
        if (btnDash) {
          btnDash.disabled = false;
          btnDash.innerHTML = origDashText;
        }
      }
    }

    async function triggerRollback() {
      if (!confirm('Roll back the last batch and restore files to downloads?')) return;
      try {
        const res = await fetch('/api/rollback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        const data = await res.json();
        showToast(`Rollback complete: ${data.reverted_files} files restored to source!`);
        loadDashboard();
        loadFiles();
        loadQuarantine();
      } catch (e) {
        showToast('Error executing rollback: ' + e);
      }
    }

    async function triggerRollbackBatch(batchId) {
      if (!confirm(`Roll back batch ${batchId.substring(0,8)} and restore files to downloads?`)) return;
      try {
        const res = await fetch('/api/rollback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ batch_id: batchId })
        });
        const data = await res.json();
        showToast(`Rollback complete: ${data.reverted_files} files restored!`);
        loadDashboard();
        loadFiles();
        loadQuarantine();
      } catch (e) {
        showToast('Error executing rollback: ' + e);
      }
    }

    async function triggerRollbackAll() {
      if (!confirm('Roll back ALL sorted batches and restore all organized files back to downloads?')) return;
      try {
        const res = await fetch('/api/rollback/all', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        showToast(`Rollback all complete: ${data.reverted_files} files restored to source!`);
        loadDashboard();
        loadFiles();
        loadQuarantine();
      } catch (e) {
        showToast('Error executing rollback all: ' + e);
      }
    }

    async function deleteDownloadFile(filename) {
      if (!confirm(`Permanently delete "${filename}" from downloads?`)) return;
      try {
        const res = await fetch(`/api/files/download?name=${encodeURIComponent(filename)}`, { method: 'DELETE' });
        if (res.ok) {
          showToast(`Deleted ${filename}`);
          loadFiles();
        } else {
          showToast('Failed to delete file');
        }
      } catch (e) {
        showToast('Error deleting file: ' + e);
      }
    }

    let autoRefreshTimer = null;
    function toggleAutoRefresh(enabled) {
      if (autoRefreshTimer) clearInterval(autoRefreshTimer);
      if (enabled) {
        autoRefreshTimer = setInterval(() => {
          const activeTab = document.querySelector('.nav-tab.active');
          if (activeTab) {
            const text = activeTab.textContent.toLowerCase();
            if (text.includes('dashboard')) loadDashboard();
            else if (text.includes('explorer')) loadFiles();
            else if (text.includes('quarantine')) loadQuarantine();
          }
        }, 5000);
      }
    }

    async function addSampleDownloads() {
      try {
        const res = await fetch('/api/files/test-sample', { method: 'POST' });
        const data = await res.json();
        showToast(`Created ${data.files.length} sample downloads for testing!`);
        loadDashboard();
        loadFiles();
      } catch (e) {
        showToast('Error adding samples: ' + e);
      }
    }

    function escapeHtml(str) {
      if (str === null || str === undefined) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function escapeJs(str) {
      if (str === null || str === undefined) return '';
      return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    }

    function toggleShowDropdown(idx) {
      const body = document.getElementById(`body-${idx}`);
      const chevron = document.getElementById(`chevron-${idx}`);
      if (!body || !chevron) return;
      const isOpen = body.style.display === 'block';
      body.style.display = isOpen ? 'none' : 'block';
      if (isOpen) {
        chevron.classList.remove('open');
      } else {
        chevron.classList.add('open');
      }
    }

    function toggleAllShowDropdowns(open) {
      const bodies = document.querySelectorAll('.show-dropdown-body');
      const chevrons = document.querySelectorAll('.show-dropdown-chevron');
      bodies.forEach(b => b.style.display = open ? 'block' : 'none');
      chevrons.forEach(c => {
        if (open) c.classList.add('open');
        else c.classList.remove('open');
      });
    }

    let currentManualContext = null;
    let manualCategory = 'movie';
    let currentQuarantinePending = [];
    let currentExplorerSingles = [];
    let currentExplorerShows = [];
    let currentExplorerUnsureGroups = [];
    let currentLibraryFilter = 'all';
    let currentLibrarySearch = '';
    let currentLibraryData = { shows: [], movies: [] };

    function openManualModalByIndex(type, idx, fIdx) {
      if (type === 'quarantine') {
        const item = currentQuarantinePending[idx];
        if (item) openManualModal('quarantine', item);
      } else if (type === 'singles') {
        const item = currentExplorerSingles[idx];
        if (item) openManualModal('files', item);
      } else if (type === 'unsure_item') {
        if (currentExplorerUnsureGroups && currentExplorerUnsureGroups[idx] && currentExplorerUnsureGroups[idx].files[fIdx]) {
          const file = currentExplorerUnsureGroups[idx].files[fIdx];
          openManualModal('files', file);
        }
      } else if (type === 'show') {
        const show = currentExplorerShows[idx];
        if (show && show.files && show.files[fIdx]) {
          const f = show.files[fIdx];
          openManualModal('files', {
            relative_path: f.relative_path || f.name,
            name: f.name,
            detected_type: 'tv',
            believed_title: show.show_name,
            season: f.season !== null && f.season !== undefined ? f.season : 1,
            episode: f.episode !== null && f.episode !== undefined ? f.episode : 1,
          });
        }
      }
    }

    function openManualModal(contextType, data) {
      currentManualContext = { type: contextType, data: data };
      const modal = document.getElementById('modal-manual-sort');
      const filenameElem = document.getElementById('manual-modal-filename');
      const titleInput = document.getElementById('manual-input-title');
      const yearInput = document.getElementById('manual-input-year');
      const seasonInput = document.getElementById('manual-input-season');
      const episodeInput = document.getElementById('manual-input-episode');

      let fileName = 'Unknown File';
      if (contextType === 'unsure_group') {
        fileName = `📁 Unsure Group: ${data.group_name} (${data.count} files)`;
      } else {
        fileName = data.filename || data.name || (data.relative_path ? data.relative_path.split('/').pop() : 'Unknown File');
      }
      if (filenameElem) filenameElem.textContent = fileName;

      const fileSelectContainer = document.getElementById('manual-modal-file-select-container');
      const fileSingleContainer = document.getElementById('manual-modal-single-file-container');
      const fileSelect = document.getElementById('manual-modal-file-select');

      if (contextType === 'quarantine' && currentQuarantinePending && currentQuarantinePending.length > 1) {
        if (fileSelectContainer) fileSelectContainer.style.display = 'block';
        if (fileSingleContainer) fileSingleContainer.style.display = 'none';
        if (fileSelect) {
          fileSelect.innerHTML = currentQuarantinePending.map((p, i) =>
            `<option value="${i}" ${p.id === data.id ? 'selected' : ''}>${escapeHtml(p.filename)}</option>`
          ).join('');
        }
      } else {
        if (fileSelectContainer) fileSelectContainer.style.display = 'none';
        if (fileSingleContainer) fileSingleContainer.style.display = 'block';
      }

      const initialCat = (data.suggested_category || data.detected_type || 'tv').toLowerCase();
      toggleManualCat(initialCat === 'movie' ? 'movie' : 'tv');

      let initTitle = data.suggested_title || data.believed_title || '';
      if (!initTitle && fileName && contextType !== 'unsure_group') {
        initTitle = fileName.replace(/\.[^/.]+$/, '').replace(/[._]/g, ' ').trim();
      } else if (!initTitle && data.group_name) {
        initTitle = data.group_name;
      }
      if (titleInput) titleInput.value = initTitle;
      if (yearInput) yearInput.value = data.year || '';
      if (seasonInput) seasonInput.value = data.season !== undefined && data.season !== null ? data.season : 1;
      if (episodeInput) episodeInput.value = data.episode !== undefined && data.episode !== null ? data.episode : 1;

      updateManualPreview();
      if (modal) modal.style.display = 'flex';
      setTimeout(() => { if (titleInput) titleInput.focus(); }, 80);
    }

    function onManualModalFileSelectChange(idxStr) {
      const idx = parseInt(idxStr, 10);
      if (!isNaN(idx) && currentQuarantinePending && currentQuarantinePending[idx]) {
        openManualModal('quarantine', currentQuarantinePending[idx]);
      }
    }

    function closeManualModal() {
      const modal = document.getElementById('modal-manual-sort');
      if (modal) modal.style.display = 'none';
      currentManualContext = null;
    }

    function toggleManualCat(cat) {
      manualCategory = cat;
      const movieBtn = document.getElementById('manual-btn-movie');
      const tvBtn = document.getElementById('manual-btn-tv');
      const movieFields = document.getElementById('manual-fields-movie');
      const tvFields = document.getElementById('manual-fields-tv');
      const titleLabel = document.getElementById('manual-title-label');

      if (cat === 'movie') {
        if (movieBtn) { movieBtn.className = 'btn btn-accent'; }
        if (tvBtn) { tvBtn.className = 'btn btn-outline'; }
        if (movieFields) movieFields.style.display = 'block';
        if (tvFields) tvFields.style.display = 'none';
        if (titleLabel) titleLabel.innerHTML = 'Movie Title <span style="color: var(--rose);">*</span>';
      } else {
        if (movieBtn) { movieBtn.className = 'btn btn-outline'; }
        if (tvBtn) { tvBtn.className = 'btn btn-emerald'; }
        if (movieFields) movieFields.style.display = 'none';
        if (tvFields) tvFields.style.display = 'block';
        if (titleLabel) titleLabel.innerHTML = 'TV Show / Series Name <span style="color: var(--rose);">*</span>';
      }
      updateManualPreview();
    }

    function updateManualPreview() {
      const previewElem = document.getElementById('manual-modal-preview');
      if (!previewElem || !currentManualContext) return;

      const title = (document.getElementById('manual-input-title').value || '').trim();
      const fileName = currentManualContext.data.filename || currentManualContext.data.name || (currentManualContext.data.relative_path ? currentManualContext.data.relative_path.split('/').pop() : 'file.mkv');
      const ext = fileName.includes('.') ? '.' + fileName.split('.').pop() : '';

      if (!title) {
        previewElem.textContent = 'Enter title above to preview destination...';
        return;
      }

      if (manualCategory === 'movie') {
        const year = document.getElementById('manual-input-year').value.trim();
        const folder = year ? `${title} (${year})` : title;
        previewElem.textContent = `Movies / ${folder} / ${folder}${ext}`;
      } else {
        const season = parseInt(document.getElementById('manual-input-season').value, 10) || 1;
        const episode = parseInt(document.getElementById('manual-input-episode').value, 10) || 1;
        const sStr = String(season).padStart(2, '0');
        const eStr = String(episode).padStart(2, '0');
        previewElem.textContent = `TV Shows / ${title} / Season ${sStr} / ${title} - S${sStr}E${eStr}${ext}`;
      }
    }

    async function submitManualResolution() {
      if (!currentManualContext) return;
      const title = (document.getElementById('manual-input-title').value || '').trim();
      if (!title) {
        alert('Please enter a title or show name.');
        return;
      }

      const submitBtn = document.getElementById('manual-submit-btn');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Organizing...';
      }

      const payload = {
        category: manualCategory,
        title: title,
        year: manualCategory === 'movie' ? (parseInt(document.getElementById('manual-input-year').value, 10) || null) : null,
        season: manualCategory === 'tv' ? (parseInt(document.getElementById('manual-input-season').value, 10) || 1) : null,
        episode: manualCategory === 'tv' ? (parseInt(document.getElementById('manual-input-episode').value, 10) || 1) : null,
      };

      try {
        if (currentManualContext.type === 'quarantine') {
          const res = await fetch(`/api/quarantine/${currentManualContext.data.id}/resolve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Resolution failed');
          showToast(`Moved to ${data.destination || (manualCategory === 'movie' ? 'Movies' : 'TV Shows')}!`);
          closeManualModal();
          loadQuarantine();
          loadFiles();
          loadDashboard();
        } else if (currentManualContext.type === 'files') {
          payload.relative_path = currentManualContext.data.relative_path || currentManualContext.data.name;
          const res = await fetch('/api/files/manual-sort', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Manual sort failed');
          showToast(`Organized: ${data.destination}!`);
          closeManualModal();
          loadFiles();
          loadDashboard();
          loadLibrary();
        } else if (currentManualContext.type === 'unsure_group') {
          const group = currentManualContext.data;
          const groupPayload = {
            group_name: group.group_name,
            group_type: group.group_type,
            category: manualCategory,
            title: title,
            year: manualCategory === 'movie' ? (parseInt(document.getElementById('manual-input-year').value, 10) || null) : null,
            relative_paths: group.files.map(f => f.relative_path || f.name)
          };
          const res = await fetch('/api/files/sort-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(groupPayload)
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Group sorting failed');
          showToast(`✓ Organized ${data.moved_files} files for '${title}'!`);
          closeManualModal();
          await Promise.all([loadFiles(), loadDashboard(), loadQuarantine()]);
          loadLibrary();
        }
      } catch (err) {
        showToast('Error: ' + err.message);
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = '⚡ Organize File';
        }
      }
    }

    async function sortShowByIndex(idx, btn) {
      if (!currentExplorerShows || !currentExplorerShows[idx]) return;
      const show = currentExplorerShows[idx];
      const origHtml = btn ? btn.innerHTML : '⚡ Sort Now';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="loading-spinner"></span> Sorting...`;
      }
      showToast(`⚡ Sorting ${show.files.length} episodes for ${show.show_name}...`);

      try {
        const res = await fetch('/api/files/sort-show', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            show_name: show.show_name,
            target_destination: show.believed_destination_folder,
            relative_paths: show.files.map(f => f.relative_path || f.name)
          })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Sorting failed');
        }
        showToast(`✓ Successfully organized ${data.moved_files} files for ${show.show_name}!`);
        await Promise.all([loadFiles(), loadDashboard(), loadQuarantine()]);
        loadLibrary();
      } catch (e) {
        showToast('Error sorting show: ' + (e.message || e));
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = origHtml;
        }
      }
    }

    function toggleUnsureDropdown(idx) {
      const body = document.getElementById(`unsure-body-${idx}`);
      const chev = document.getElementById(`unsure-chevron-${idx}`);
      if (!body) return;
      const isShown = body.style.display === 'block';
      body.style.display = isShown ? 'none' : 'block';
      if (chev) {
        chev.textContent = isShown ? '▶' : '▼';
        chev.classList.toggle('expanded', !isShown);
      }
    }

    function openManualModalForGroup(idx) {
      if (!currentExplorerUnsureGroups || !currentExplorerUnsureGroups[idx]) return;
      const group = currentExplorerUnsureGroups[idx];
      openManualModal('unsure_group', {
        ...group,
        name: group.group_name,
        believed_title: group.suggested_title || group.group_name,
        count: group.count,
      });
    }

    async function sortUnsureGroupByIndex(idx, btn) {
      if (!currentExplorerUnsureGroups || !currentExplorerUnsureGroups[idx]) return;
      const group = currentExplorerUnsureGroups[idx];
      const origHtml = btn ? btn.innerHTML : '⚡ Sort Group';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="loading-spinner"></span> Sorting...`;
      }
      showToast(`⚡ Sorting ${group.files.length} files in group '${group.group_name}'...`);

      try {
        const res = await fetch('/api/files/sort-group', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            group_name: group.group_name,
            group_type: group.group_type,
            category: 'tv',
            title: group.suggested_title || group.group_name,
            relative_paths: group.files.map(f => f.relative_path || f.name)
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Sorting group failed');
        showToast(`✓ Successfully organized ${data.moved_files} files for '${group.group_name}'!`);
        await Promise.all([loadFiles(), loadDashboard(), loadQuarantine()]);
        loadLibrary();
      } catch (e) {
        showToast('Error sorting group: ' + (e.message || e));
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = origHtml;
        }
      }
    }

    function renderDownloadsExplorer(downloads) {
      const pathElem = document.getElementById('path-downloads');
      if (pathElem) pathElem.textContent = downloads.path || '';

      const allFiles = (downloads.files || []).filter(f => !f.name.toLowerCase().endsWith('.txt'));
      const totalFiles = downloads.total_files !== undefined ? downloads.total_files : allFiles.length;
      const shows = (downloads.shows || []).map(s => {
        const filteredFiles = (s.files || []).filter(f => !f.name.toLowerCase().endsWith('.txt'));
        return { ...s, files: filteredFiles, count: filteredFiles.length };
      }).filter(s => s.count > 0);
      const singles = (downloads.singles || []).filter(f => !f.name.toLowerCase().endsWith('.txt'));

      currentExplorerShows = shows;
      currentExplorerSingles = singles;

      const totalBadge = document.getElementById('downloads-total-badge');
      if (totalBadge) totalBadge.textContent = `${totalFiles} file${totalFiles === 1 ? '' : 's'}`;

      const showsBadge = document.getElementById('shows-detected-badge');
      if (showsBadge) {
        showsBadge.textContent = `${shows.length} show${shows.length === 1 ? '' : 's'} detected`;
        showsBadge.style.display = shows.length > 0 ? 'inline-block' : 'none';
      }

      const emptyElem = document.getElementById('downloads-empty');
      const toolbarElem = document.getElementById('shows-toolbar');
      const showsContainer = document.getElementById('downloads-shows-container');
      const singlesContainer = document.getElementById('downloads-singles-container');
      const singlesTbody = document.getElementById('downloads-singles-tbody');

      if (totalFiles === 0) {
        if (emptyElem) emptyElem.style.display = 'block';
        if (toolbarElem) toolbarElem.style.display = 'none';
        if (showsContainer) showsContainer.innerHTML = '';
        if (singlesContainer) singlesContainer.style.display = 'none';
        return;
      }

      if (emptyElem) emptyElem.style.display = 'none';
      if (toolbarElem) {
        toolbarElem.style.display = shows.length > 0 ? 'flex' : 'none';
        const cnt = document.getElementById('toolbar-show-count');
        if (cnt) cnt.textContent = `${shows.length} show${shows.length === 1 ? '' : 's'} (${shows.reduce((acc, s) => acc + s.count, 0)} files)`;
      }

      // Render Shows Dropdowns
      if (showsContainer) {
        showsContainer.innerHTML = '';
        shows.forEach((show, idx) => {
          const card = document.createElement('div');
          card.className = 'show-dropdown';
          card.id = `show-card-${idx}`;

          const showNameEsc = escapeHtml(show.show_name);
          const seasonSummaryEsc = escapeHtml(show.season_summary || 'Episodic Series');
          const destFolderEsc = escapeHtml(show.believed_destination_folder || '');
          const posterUrl = show.poster_url;

          const posterThumbHtml = posterUrl
            ? `<img class="believed-poster-img" src="${escapeHtml(posterUrl)}" alt="${showNameEsc}" onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='inline';" /><span style="display:none;">📺</span>`
            : `<span>📺</span>`;

          const leftPosterHtml = posterUrl
            ? `<img class="show-left-poster" src="${escapeHtml(posterUrl)}" alt="${showNameEsc}" onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='inline-block';" /><span style="font-size: 1.5rem; display:none;">📺</span>`
            : `<span style="font-size: 1.5rem;">📺</span>`;

          const subbarPosterHtml = posterUrl
            ? `<img class="show-subbar-poster" src="${escapeHtml(posterUrl)}" alt="${showNameEsc}" onerror="this.style.display='none';" />`
            : '';

          card.innerHTML = `
            <div class="show-dropdown-header" onclick="toggleShowDropdown(${idx})">
              <div class="show-dropdown-left">
                <span class="show-dropdown-chevron" id="chevron-${idx}">▶</span>
                ${leftPosterHtml}
                <div>
                  <div class="show-dropdown-title">${showNameEsc}</div>
                  <div style="font-size: 0.75rem; color: var(--text-muted);">${seasonSummaryEsc}</div>
                </div>
                <span class="show-dropdown-badge">${show.count} file${show.count === 1 ? '' : 's'}</span>
              </div>
              <div class="show-dropdown-side">
                <span class="believed-show-label">Believed Show:</span>
                <span class="believed-show-val" title="Target destination: ${destFolderEsc}">
                  ${posterThumbHtml}
                  <span>${showNameEsc}</span>
                </span>
              </div>
            </div>
            <div class="show-dropdown-body" id="body-${idx}">
              <div class="show-dropdown-subbar">
                <div style="display: flex; align-items: center; gap: 0.85rem;">
                  ${subbarPosterHtml}
                  <div>
                    <div style="font-size: 0.95rem; font-weight: 600; color: var(--text-title, #fff); margin-bottom: 0.2rem;">${showNameEsc}</div>
                    <div>
                      <span>Target Destination: </span>
                      <code style="color: var(--emerald); font-size: 0.8rem;">${destFolderEsc}</code>
                    </div>
                  </div>
                </div>
                <button class="btn btn-emerald btn-sm" id="btn-sort-show-${idx}" onclick="sortShowByIndex(${idx}, this)">⚡ Sort Now</button>
              </div>
              <div class="show-table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>File</th>
                      <th>Season / Episode</th>
                      <th>Size</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody id="tbody-show-${idx}"></tbody>
                </table>
              </div>
            </div>
          `;
          showsContainer.appendChild(card);

          // Populate file rows
          const tbody = card.querySelector(`#tbody-show-${idx}`);
          show.files.forEach((f, fIdx) => {
            const tr = document.createElement('tr');
            let seText = '-';
            if (f.season !== null && f.season !== undefined && f.episode !== null && f.episode !== undefined) {
              seText = `S${String(f.season).padStart(2, '0')}E${String(f.episode).padStart(2, '0')}`;
            } else if (f.episode !== null && f.episode !== undefined) {
              seText = `Ep ${f.episode}`;
            }
            const seBadge = seText !== '-' ? `<span class="tag tag-movie">${seText}</span>` : `<span style="color:var(--text-muted);">-</span>`;
            const epTitle = f.episode_title ? `<div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(f.episode_title)}</div>` : '';
            const delTarget = f.relative_path || f.name;

            tr.innerHTML = `
              <td>
                <code>${escapeHtml(f.name)}</code>
                ${epTitle}
                <div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(f.relative_path)}</div>
              </td>
              <td>${seBadge}</td>
              <td>${escapeHtml(f.size)}</td>
              <td>
                <div style="display: flex; gap: 0.35rem;">
                  <button class="btn btn-outline btn-sm" title="Manually set show or movie details" onclick="openManualModalByIndex('show', ${idx}, ${fIdx})">✏️ Set Show/Movie</button>
                  <button class="btn btn-outline btn-sm" style="color: var(--rose); border-color: var(--rose);" title="Delete from downloads" onclick="deleteDownloadFile('${escapeJs(delTarget)}')">🗑️</button>
                </div>
              </td>
            `;
            tbody.appendChild(tr);
          });
        });
      }

      // Render Unsure Groups Dropdowns (Shared Subfolders & Common Name Prefixes)
      const unsureContainer = document.getElementById('downloads-unsure-container');
      const unsureList = document.getElementById('downloads-unsure-list');
      const unsureBadge = document.getElementById('unsure-groups-count-badge');
      const rawUnsureGroups = downloads.unsure_groups || [];
      const unsureGroups = rawUnsureGroups.map(g => {
        const filtered = (g.files || []).filter(f => !f.name.toLowerCase().endsWith('.txt'));
        return { ...g, files: filtered, count: filtered.length };
      }).filter(g => g.count > 0);
      currentExplorerUnsureGroups = unsureGroups;

      if (unsureContainer && unsureList) {
        if (unsureGroups.length > 0) {
          unsureContainer.style.display = 'block';
          if (unsureBadge) {
            const totalGroupFiles = unsureGroups.reduce((acc, g) => acc + g.count, 0);
            unsureBadge.textContent = `${unsureGroups.length} group${unsureGroups.length === 1 ? '' : 's'} (${totalGroupFiles} files)`;
          }
          unsureList.innerHTML = '';
          unsureGroups.forEach((group, idx) => {
            const card = document.createElement('div');
            card.className = 'show-dropdown';
            card.id = `unsure-card-${idx}`;
            card.style.borderLeft = '3px solid var(--amber)';

            const groupNameEsc = escapeHtml(group.group_name);
            const sugTitleEsc = escapeHtml(group.suggested_title || group.group_name);
            const typeLabel = group.group_type === 'folder' ? '📁 Shared Subfolder' : '🏷️ Matching Name Prefix';

            card.innerHTML = `
              <div class="show-dropdown-header" onclick="toggleUnsureDropdown(${idx})">
                <div class="show-dropdown-left">
                  <span class="show-dropdown-chevron" id="unsure-chevron-${idx}">▶</span>
                  <span style="font-size: 1.4rem;">${group.group_type === 'folder' ? '📁' : '🏷️'}</span>
                  <div>
                    <div class="show-dropdown-title">${groupNameEsc}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">${typeLabel} • Suggested: <strong style="color: var(--text);">${sugTitleEsc}</strong></div>
                  </div>
                  <span class="show-dropdown-badge" style="background: rgba(245, 158, 11, 0.2); color: var(--amber);">${group.count} file${group.count === 1 ? '' : 's'}</span>
                </div>
                <div class="show-dropdown-side">
                  <span class="tag tag-amber" style="font-size: 0.72rem;">Unsure Group</span>
                </div>
              </div>
              <div class="show-dropdown-body" id="unsure-body-${idx}">
                <div class="show-dropdown-subbar" style="background: rgba(245, 158, 11, 0.05); border-bottom: 1px solid rgba(245, 158, 11, 0.15);">
                  <div>
                    <div style="font-size: 0.92rem; font-weight: 600; color: var(--text-title, #fff);">${groupNameEsc}</div>
                    <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 0.15rem;">
                      Suggested Show: <code style="color: var(--emerald);">${sugTitleEsc}</code>
                    </div>
                  </div>
                  <div style="display: flex; gap: 0.45rem;">
                    <button class="btn btn-outline btn-sm" onclick="openManualModalForGroup(${idx})">✏️ Set Show/Movie for Group</button>
                    <button class="btn btn-amber btn-sm" id="btn-sort-unsure-${idx}" onclick="sortUnsureGroupByIndex(${idx}, this)">⚡ Sort Group</button>
                  </div>
                </div>
                <div class="show-table-wrapper">
                  <table>
                    <thead>
                      <tr>
                        <th>File</th>
                        <th>Type</th>
                        <th>Size</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody id="tbody-unsure-${idx}"></tbody>
                  </table>
                </div>
              </div>
            `;
            unsureList.appendChild(card);

            const tbody = card.querySelector(`#tbody-unsure-${idx}`);
            group.files.forEach((f, fIdx) => {
              const tr = document.createElement('tr');
              const delTarget = f.relative_path || f.name;
              tr.innerHTML = `
                <td>
                  <code>${escapeHtml(f.name)}</code>
                  <div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(f.relative_path)}</div>
                </td>
                <td><span class="tag tag-dry">${escapeHtml(f.detected_type || 'unsure').toUpperCase()}</span></td>
                <td>${escapeHtml(f.size)}</td>
                <td>
                  <div style="display: flex; gap: 0.35rem;">
                    <button class="btn btn-outline btn-sm" title="Set show or movie details" onclick="openManualModalByIndex('unsure_item', ${idx}, ${fIdx})">✏️ Set Show/Movie</button>
                    <button class="btn btn-outline btn-sm" style="color: var(--rose); border-color: var(--rose);" title="Delete from downloads" onclick="deleteDownloadFile('${escapeJs(delTarget)}')">🗑️</button>
                  </div>
                </td>
              `;
              tbody.appendChild(tr);
            });
          });
        } else {
          unsureContainer.style.display = 'none';
        }
      }

      // Render Singles / Other Media
      if (singlesContainer && singlesTbody) {
        if (singles.length > 0) {
          singlesContainer.style.display = 'block';
          const singlesBadge = document.getElementById('singles-count-badge');
          if (singlesBadge) singlesBadge.textContent = `${singles.length} file${singles.length === 1 ? '' : 's'}`;
          singlesTbody.innerHTML = '';
          singles.forEach((f, idx) => {
            const tr = document.createElement('tr');
            const typeTag = f.detected_type === 'movie' ? '<span class="tag tag-movie">MOVIE</span>' : '<span class="tag tag-dry">FILE</span>';
            const delTarget = f.relative_path || f.name;
            tr.innerHTML = `
              <td>
                <code>${escapeHtml(f.name)}</code>
                <div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(f.relative_path)}</div>
              </td>
              <td>${typeTag}</td>
              <td><strong style="color: var(--text-title, #fff);">${escapeHtml(f.believed_title || f.name)}</strong></td>
              <td>${escapeHtml(f.size)}</td>
              <td>
                <div style="display: flex; gap: 0.35rem;">
                  <button class="btn btn-outline btn-sm" title="Manually set show or movie details" onclick="openManualModalByIndex('singles', ${idx})">✏️ Set Show/Movie</button>
                  <button class="btn btn-outline btn-sm" style="color: var(--rose); border-color: var(--rose);" title="Delete from downloads" onclick="deleteDownloadFile('${escapeJs(delTarget)}')">🗑️</button>
                </div>
              </td>
            `;
            singlesTbody.appendChild(tr);
          });
        } else {
          singlesContainer.style.display = 'none';
        }
      }
    }

    async function loadFiles() {
      try {
        const res = await fetch('/api/files');
        const data = await res.json();
        renderDownloadsExplorer(data.downloads);
      } catch (e) {
        console.error(e);
      }
    }

    async function loadLibrary() {
      try {
        const cat = currentLibraryFilter || 'all';
        const search = currentLibrarySearch || '';
        const url = `/api/library?category=${cat}&search=${encodeURIComponent(search)}`;
        const res = await fetch(url);
        const data = await res.json();
        currentLibraryData = data;
        renderLibrary(data);
      } catch (e) {
        console.error('Error loading library:', e);
      }
    }

    function setLibraryFilter(filter) {
      currentLibraryFilter = filter;
      ['all', 'tv', 'movie'].forEach(f => {
        const btn = document.getElementById(`lib-filter-${f}`);
        if (btn) {
          if (f === filter) {
            btn.className = f === 'tv' ? 'btn btn-emerald btn-sm' : (f === 'movie' ? 'btn btn-accent btn-sm' : 'btn btn-accent btn-sm');
          } else {
            btn.className = 'btn btn-outline btn-sm';
          }
        }
      });
      loadLibrary();
    }

    let searchDebounce = null;
    function onLibrarySearchChange(val) {
      currentLibrarySearch = (val || '').trim();
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        loadLibrary();
      }, 250);
    }

    async function rescanLibraryDisk() {
      const btn = document.getElementById('btn-library-rescan');
      const orig = btn ? btn.innerHTML : '🔄 Rescan Disk Library';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="loading-spinner"></span> Scanning disk...`;
      }
      showToast('🔍 Scanning library storage disks for shows and movies...');
      try {
        const res = await fetch('/api/library/rescan', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Rescan failed');
        showToast(`✓ Library synced: ${data.shows_synced} shows, ${data.movies_synced} movies discovered!`);
        await loadLibrary();
      } catch (e) {
        showToast('Error rescanning library: ' + (e.message || e));
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = orig;
        }
      }
    }

    function renderLibrary(data) {
      const totalShows = data.total_shows || 0;
      const totalMovies = data.total_movies || 0;
      const totalAll = totalShows + totalMovies;

      const badgeShows = document.getElementById('lib-badge-shows');
      const badgeMovies = document.getElementById('lib-badge-movies');
      const cntAll = document.getElementById('lib-cnt-all');
      const cntTv = document.getElementById('lib-cnt-tv');
      const cntMovie = document.getElementById('lib-cnt-movie');

      if (badgeShows) badgeShows.textContent = `${totalShows} Shows`;
      if (badgeMovies) badgeMovies.textContent = `${totalMovies} Movies`;
      if (cntAll) cntAll.textContent = totalAll;
      if (cntTv) cntTv.textContent = totalShows;
      if (cntMovie) cntMovie.textContent = totalMovies;

      const grid = document.getElementById('library-items-grid');
      const empty = document.getElementById('library-empty');
      if (!grid) return;

      const items = [];
      if (currentLibraryFilter === 'all' || currentLibraryFilter === 'tv') {
        (data.shows || []).forEach(s => items.push({ ...s, is_tv: true }));
      }
      if (currentLibraryFilter === 'all' || currentLibraryFilter === 'movie') {
        (data.movies || []).forEach(m => items.push({ ...m, is_tv: false }));
      }

      items.sort((a, b) => a.title.localeCompare(b.title));

      if (items.length === 0) {
        grid.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
      }
      if (empty) empty.style.display = 'none';

      grid.innerHTML = items.map(item => {
        const isTv = item.is_tv;
        const catBadge = isTv ? '<span class="tag tag-show">TV SHOW</span>' : '<span class="tag tag-movie">MOVIE</span>';
        const yearHtml = item.year ? `<span style="font-size: 0.75rem; color: var(--text-muted);">(${item.year})</span>` : '';
        const statsHtml = isTv
          ? `${item.item_count} episode${item.item_count === 1 ? '' : 's'} • ${item.seasons_count || 1} season${item.seasons_count === 1 ? '' : 's'}`
          : `${item.item_count} file${item.item_count === 1 ? '' : 's'}`;
        const icon = isTv ? '📺' : '🎬';
        const posterImg = item.poster_url
          ? `<img src="${escapeHtml(item.poster_url)}" alt="${escapeHtml(item.title)}" style="width: 100%; height: 100%; object-fit: cover;" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" /><div style="display:none; width: 100%; height: 100%; align-items: center; justify-content: center; font-size: 1.5rem;">${icon}</div>`
          : `<div style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 1.5rem;">${icon}</div>`;

        return `
          <div class="library-card" style="background: var(--surface-light); border: 1px solid var(--border); border-radius: var(--radius); padding: 0.85rem; display: flex; flex-direction: column; gap: 0.6rem;">
            <div style="display: flex; gap: 0.75rem; align-items: flex-start;">
              <div style="width: 50px; height: 75px; flex-shrink: 0; background: rgba(0,0,0,0.3); border-radius: var(--radius-sm); overflow: hidden; border: 1px solid var(--border);">
                ${posterImg}
              </div>
              <div style="flex: 1; min-width: 0;">
                <div style="font-weight: 600; font-size: 0.95rem; color: var(--text-title, #fff); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(item.title)}">
                  ${escapeHtml(item.title)}
                </div>
                <div style="display: flex; gap: 0.4rem; align-items: center; margin-top: 0.25rem; flex-wrap: wrap;">
                  ${catBadge}
                  ${yearHtml}
                </div>
                <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.35rem;">
                  ${statsHtml}
                </div>
              </div>
            </div>
            <div style="font-size: 0.7rem; color: var(--text-muted); word-break: break-all; background: rgba(0,0,0,0.25); padding: 0.35rem 0.5rem; border-radius: var(--radius-sm); border: 1px solid var(--border); font-family: monospace;">
              📁 ${escapeHtml(item.destination_folder)}
            </div>
          </div>
        `;
      }).join('');
    }

    async function loadQuarantine() {
      try {
        const res = await fetch('/api/quarantine');
        const data = await res.json();
        const pending = Array.isArray(data) ? data : (data.pending || []);
        const resolved = data.resolved || [];
        currentQuarantinePending = pending;

        const tbody = document.getElementById('quarantine-tbody');
        tbody.innerHTML = '';
        const quarBadge = document.getElementById('quar-badge');
        const quarPendingBadge = document.getElementById('quar-pending-count-badge');
        const quarSelectionBar = document.getElementById('quar-selection-bar');
        const quarTotalCountText = document.getElementById('quar-total-count-text');
        const topUndoAllBtn = document.getElementById('quar-btn-top-undo-all');

        if (quarTotalCountText) quarTotalCountText.textContent = pending.length;

        if (pending.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Quarantine queue is empty. Flagged files will appear here without being moved.</td></tr>';
          if (quarBadge) quarBadge.style.display = 'none';
          if (quarPendingBadge) quarPendingBadge.style.display = 'none';
          if (quarSelectionBar) quarSelectionBar.style.display = 'none';
        } else {
          if (quarBadge) {
            quarBadge.textContent = pending.length;
            quarBadge.style.display = 'inline-block';
          }
          if (quarPendingBadge) {
            quarPendingBadge.textContent = `${pending.length} pending`;
            quarPendingBadge.style.display = 'inline-block';
          }
          if (quarSelectionBar) {
            quarSelectionBar.style.display = 'flex';
          }

          pending.forEach((q, idx) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td style="text-align: center;">
                <input type="checkbox" class="quar-item-checkbox" value="${q.id}" data-idx="${idx}" onchange="updateQuarantineSelection()" style="accent-color: var(--accent); cursor: pointer;">
              </td>
              <td>
                <code>${escapeHtml(q.filename)}</code>
                <div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(q.src)}</div>
              </td>
              <td style="color: var(--rose); font-weight: 500;">${escapeHtml(q.reason)}</td>
              <td><span class="tag ${q.confidence >= 70 ? 'tag-movie' : 'tag-dry'}">${q.confidence}%</span></td>
              <td style="font-size: 0.8rem; color: var(--text-muted);">${q.created_at || '-'}</td>
              <td>
                <div style="display: flex; gap: 0.35rem; flex-wrap: wrap;">
                  <button class="btn btn-accent btn-sm" onclick="resolveItem(${q.id}, 'movie')" title="Quick move to Movies">🎬 Movie</button>
                  <button class="btn btn-emerald btn-sm" onclick="resolveItem(${q.id}, 'tv')" title="Quick move to TV Shows">📺 Show</button>
                  <button class="btn btn-outline btn-sm" onclick="openManualModalByIndex('quarantine', ${idx})" title="Customize title, season, episode">✏️ Set Show/Movie</button>
                  <button class="btn btn-outline btn-sm" style="color: var(--amber); border-color: var(--amber);" onclick="undoQuarantine(${q.id})" title="Unflag / dismiss from quarantine">↩️ Unflag</button>
                </div>
              </td>
            `;
            tbody.appendChild(tr);
          });
        }

        updateQuarantineSelection();

        // Render Resolved Section & Top Undo All Button
        const resolvedSection = document.getElementById('quarantine-resolved-section');
        const resolvedTbody = document.getElementById('quarantine-resolved-tbody');
        const resolvedBadge = document.getElementById('resolved-count-badge');

        if (topUndoAllBtn) {
          topUndoAllBtn.style.display = resolved.length > 0 ? 'inline-flex' : 'none';
        }

        if (resolvedTbody) {
          resolvedTbody.innerHTML = '';
          if (resolved.length > 0) {
            if (resolvedSection) resolvedSection.style.display = 'block';
            if (resolvedBadge) resolvedBadge.textContent = `${resolved.length} resolved`;
            resolved.forEach(r => {
              const tr = document.createElement('tr');
              const catTag = r.category === 'tv' ? '<span class="tag tag-show">TV SHOW</span>' : '<span class="tag tag-movie">MOVIE</span>';
              tr.innerHTML = `
                <td>
                  <code>${escapeHtml(r.resolved_filename || r.filename)}</code>
                  <div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(r.src)}</div>
                </td>
                <td>${catTag}</td>
                <td><code style="font-size:0.75rem; color:var(--emerald); word-break:break-all;">${escapeHtml(r.resolved_path || '-')}</code></td>
                <td style="font-size:0.8rem; color:var(--text-muted);">${r.resolved_at || '-'}</td>
                <td>
                  <button class="btn btn-amber btn-sm" onclick="undoQuarantine(${r.id})" title="Restore file back to original source folder and re-flag in review queue">↩ Undo</button>
                </td>
              `;
              resolvedTbody.appendChild(tr);
            });
          } else {
            if (resolvedSection) resolvedSection.style.display = 'none';
          }
        }
      } catch (e) {
        console.error(e);
      }
    }

    function getSelectedQuarantineIds() {
      const cbs = document.querySelectorAll('.quar-item-checkbox:checked');
      return Array.from(cbs).map(cb => parseInt(cb.value, 10));
    }

    function updateQuarantineSelection() {
      const selected = getSelectedQuarantineIds();
      const total = currentQuarantinePending ? currentQuarantinePending.length : 0;
      const badge = document.getElementById('quar-selected-badge');
      const countText = document.getElementById('quar-total-count-text');
      const selectAll = document.getElementById('quar-select-all');
      const thCheckbox = document.getElementById('quar-th-checkbox');

      if (countText) countText.textContent = total;

      if (badge) {
        if (selected.length > 0) {
          badge.textContent = `${selected.length} selected`;
          badge.style.display = 'inline-block';
        } else {
          badge.style.display = 'none';
        }
      }

      if (selectAll) selectAll.checked = total > 0 && selected.length === total;
      if (thCheckbox) thCheckbox.checked = total > 0 && selected.length === total;

      const movieBtn = document.getElementById('quar-btn-top-movie');
      const tvBtn = document.getElementById('quar-btn-top-tv');
      const unflagBtn = document.getElementById('quar-btn-top-unflag');
      if (selected.length > 0) {
        if (movieBtn) movieBtn.textContent = `🎬 Move to Movies (${selected.length})`;
        if (tvBtn) tvBtn.textContent = `📺 Move to Shows (${selected.length})`;
        if (unflagBtn) unflagBtn.textContent = `↩️ Unflag (${selected.length})`;
      } else {
        if (movieBtn) movieBtn.textContent = '🎬 Move to Movies';
        if (tvBtn) tvBtn.textContent = '📺 Move to Shows';
        if (unflagBtn) unflagBtn.textContent = '↩️ Unflag';
      }
    }

    function toggleSelectAllQuarantine(checked) {
      const cbs = document.querySelectorAll('.quar-item-checkbox');
      cbs.forEach(cb => { cb.checked = checked; });
      const selectAll = document.getElementById('quar-select-all');
      const thCheckbox = document.getElementById('quar-th-checkbox');
      if (selectAll) selectAll.checked = checked;
      if (thCheckbox) thCheckbox.checked = checked;
      updateQuarantineSelection();
    }

    async function handleTopQuarantineAction(category) {
      if (!currentQuarantinePending || currentQuarantinePending.length === 0) {
        showToast('Quarantine queue is empty.');
        return;
      }

      const selectedIds = getSelectedQuarantineIds();
      const catName = category === 'movie' ? 'Movies' : 'TV Shows';
      let idsToSend = null;

      if (selectedIds.length > 0) {
        idsToSend = selectedIds;
      } else {
        const msg = currentQuarantinePending.length === 1
          ? `Move "${currentQuarantinePending[0].filename}" to ${catName}?`
          : `Move all ${currentQuarantinePending.length} pending quarantine files to ${catName}?`;
        if (!confirm(msg)) return;
      }

      try {
        const res = await fetch('/api/quarantine/bulk-resolve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            item_ids: idsToSend,
            category: category
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Resolution failed');
        showToast(`Moved ${data.resolved_count} file(s) to ${catName}!`);
        loadQuarantine();
        loadFiles();
        loadDashboard();
      } catch (e) {
        showToast('Error: ' + e.message);
      }
    }

    async function handleTopQuarantineUnflag() {
      if (!currentQuarantinePending || currentQuarantinePending.length === 0) {
        showToast('Quarantine queue is empty.');
        return;
      }

      const selectedIds = getSelectedQuarantineIds();
      let idsToSend = null;

      if (selectedIds.length > 0) {
        if (!confirm(`Unflag ${selectedIds.length} selected item(s) from quarantine?`)) return;
        idsToSend = selectedIds;
      } else {
        const msg = currentQuarantinePending.length === 1
          ? `Unflag "${currentQuarantinePending[0].filename}" from quarantine?`
          : `Unflag all ${currentQuarantinePending.length} pending items from quarantine?`;
        if (!confirm(msg)) return;
      }

      try {
        const res = await fetch('/api/quarantine/bulk-undo', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            item_ids: idsToSend,
            scope: 'pending'
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Unflag failed');
        showToast(`Unflagged ${data.undone_count} item(s)!`);
        loadQuarantine();
        loadFiles();
        loadDashboard();
      } catch (e) {
        showToast('Error: ' + e.message);
      }
    }

    function handleTopQuarantineManual() {
      if (!currentQuarantinePending || currentQuarantinePending.length === 0) {
        showToast('No pending quarantine items to configure.');
        return;
      }
      const checked = document.querySelectorAll('.quar-item-checkbox:checked');
      if (checked.length > 0) {
        const idx = parseInt(checked[0].getAttribute('data-idx'), 10);
        openManualModalByIndex('quarantine', idx);
      } else {
        openManualModalByIndex('quarantine', 0);
      }
    }

    async function undoAllResolvedQuarantine() {
      if (!confirm('Undo all resolved quarantine items and restore files back to their source folders?')) return;
      try {
        const res = await fetch('/api/quarantine/bulk-undo', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scope: 'resolved'
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Undo failed');
        showToast(`Reverted ${data.undone_count} resolved file(s) back to source folders!`);
        loadQuarantine();
        loadFiles();
        loadDashboard();
      } catch (e) {
        showToast('Error: ' + e.message);
      }
    }

    async function undoQuarantine(id) {
      if (!confirm('Revert this quarantine item? If resolved, the file will be moved back to its source location.')) return;
      try {
        const res = await fetch(`/api/quarantine/${id}/undo`, {
          method: 'POST'
        });
        if (res.ok) {
          showToast('Quarantine item reverted successfully!');
          loadQuarantine();
          loadFiles();
          loadDashboard();
        } else {
          const err = await res.json();
          showToast('Failed to undo: ' + (err.detail || 'Unknown error'));
        }
      } catch (e) {
        showToast('Error: ' + e);
      }
    }

    async function resolveItem(id, category) {
      try {
        await fetch(`/api/quarantine/${id}/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ category })
        });
        showToast(`Moved to ${category === 'movie' ? 'Movies' : 'Shows'} folder!`);
        loadQuarantine();
        loadFiles();
        loadDashboard();
      } catch (e) {
        showToast('Error: ' + e);
      }
    }

    async function loadSettings() {
      try {
        const res = await fetch('/api/settings');
        const s = await res.json();
        document.getElementById('cfg-downloads').value = s.downloads_dir;
        document.getElementById('cfg-movies').value = s.movies_dir;
        document.getElementById('cfg-shows').value = s.shows_dir;
        document.getElementById('cfg-dryrun').value = s.dry_run ? 'true' : 'false';
        document.getElementById('cfg-threshold').value = s.confidence_threshold;
        document.getElementById('cfg-action').value = s.action;
        document.getElementById('cfg-interval').value = s.scan_interval_seconds || 0;
        document.getElementById('cfg-cleanup').checked = s.cleanup_empty_dirs !== false;
        const renameEnabled = s.rename_files !== false;
        document.getElementById('cfg-rename').checked = renameEnabled;
        document.getElementById('rename-patterns-box').style.display = renameEnabled ? 'block' : 'none';
        document.getElementById('cfg-movie-template').value = s.movie_template || '';
        document.getElementById('cfg-tv-template').value = s.tv_template || '';
      } catch (e) {
        console.error(e);
      }
    }

    async function saveSettings(e) {
      e.preventDefault();
      const payload = {
        downloads_dir: document.getElementById('cfg-downloads').value,
        movies_dir: document.getElementById('cfg-movies').value,
        shows_dir: document.getElementById('cfg-shows').value,
        dry_run: document.getElementById('cfg-dryrun').value === 'true',
        confidence_threshold: parseFloat(document.getElementById('cfg-threshold').value),
        action: document.getElementById('cfg-action').value,
        scan_interval_seconds: parseInt(document.getElementById('cfg-interval').value, 10) || 0,
        cleanup_empty_dirs: document.getElementById('cfg-cleanup').checked,
        rename_files: document.getElementById('cfg-rename').checked,
        movie_template: document.getElementById('cfg-movie-template').value,
        tv_template: document.getElementById('cfg-tv-template').value,
      };
      try {
        const res = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        showToast(data.message);
        loadDashboard();
      } catch (err) {
        showToast('Error saving settings: ' + err);
      }
    }

    async function triggerServerRestart() {
      if (!confirm('Are you sure you want to restart the Media Sorter server?')) return;
      showToast('Restarting server... Reconnecting in a moment...');

      try {
        await fetch('/api/restart', { method: 'POST' });
      } catch (e) {
        // Expected if connection terminates immediately
      }

      let overlay = document.getElementById('restart-overlay');
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'restart-overlay';
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(9,13,22,0.92);backdrop-filter:blur(6px);z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;';
        overlay.innerHTML = `
          <div style="font-size: 2.5rem; margin-bottom: 1rem; animation: spin 1.5s linear infinite;">🔄</div>
          <h2 style="margin-bottom: 0.5rem; font-weight: 600;">Restarting Media Sorter</h2>
          <p style="color: var(--text-muted); font-size: 0.95rem;" id="restart-msg">Reloading configuration and services...</p>
        `;
        document.body.appendChild(overlay);
      } else {
        overlay.style.display = 'flex';
      }

      let attempts = 0;
      const pollInterval = setInterval(async () => {
        attempts++;
        try {
          const res = await fetch('/api/status', { cache: 'no-store' });
          if (res.ok) {
            clearInterval(pollInterval);
            document.getElementById('restart-msg').textContent = 'Connected! Reloading dashboard...';
            setTimeout(() => { window.location.reload(); }, 600);
          }
        } catch (err) {
          if (attempts >= 25) {
            clearInterval(pollInterval);
            document.getElementById('restart-msg').textContent = 'Server restart took longer than usual. Please refresh manually.';
          }
        }
      }, 1000);
    }

    try {
      const savedTheme = localStorage.getItem('ms-theme') || 'cyber-dark';
      setTheme(savedTheme);
    } catch (e) {}

    async function handleUpdate() {
      try {
        showToast('Checking for updates…');
        const res = await fetch('/api/check_update');
        const data = await res.json();
        if (!data.update_available) {
          showToast('You are on the latest version (' + data.current_version + ')');
          return;
        }
        if (confirm('Update available: ' + data.latest_version + ' (current: ' + data.current_version + '). Update now?')) {
          showToast('Updating…');
          const upRes = await fetch('/api/perform_update', { method: 'POST' });
          const upData = await upRes.json();
          if (upData.status === 'update_started') {
            showToast('Update started. The server will restart shortly.');
          } else {
            showToast('Update response: ' + JSON.stringify(upData));
          }
        }
      } catch (e) {
        showToast('Update check failed: ' + e.message);
      }
    }

    loadDashboard();
  </script>
</body>
</html>
"""
        return html.replace("__VERSION_PLACEHOLDER__", __version__)

    return app
