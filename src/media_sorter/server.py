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
from .models import BatchRecord, Operation, QuarantineRecord, QuarantineStatus
from .quarantine import QuarantineManager
from .sorter import MediaSorterApp

logger = structlog.get_logger(__name__)


class RunRequest(BaseModel):
    dry_run: Optional[bool] = None


class RollbackRequest(BaseModel):
    batch_id: Optional[str] = None


class ResolveRequest(BaseModel):
    category: str
    target_path: Optional[str] = None


class SettingsUpdateRequest(BaseModel):
    downloads_dir: Optional[str] = None
    movies_dir: Optional[str] = None
    shows_dir: Optional[str] = None
    dry_run: Optional[bool] = None
    confidence_threshold: Optional[float] = None
    min_file_age_seconds: Optional[int] = None
    scan_interval_seconds: Optional[int] = None
    action: Optional[str] = None


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


def inspect_downloads_folder(directory: Path, settings: Settings) -> Dict[str, Any]:
    """Inspects downloads folder, categorizing files from the same show with believed show names."""
    from .tokenizer import FilenameTokenizer

    tok = FilenameTokenizer()
    all_files: List[Dict[str, Any]] = []
    show_map: Dict[str, List[Dict[str, Any]]] = {}
    singles: List[Dict[str, Any]] = []

    if not directory.exists():
        return {"path": str(directory), "files": [], "shows": [], "singles": [], "total_files": 0}

    shows_base = settings.get_destination_path("tv")
    movies_base = settings.get_destination_path("movie")

    for root, _, files in os.walk(directory):
        for f in files:
            p = Path(root) / f
            try:
                st = p.stat()
                rel = p.relative_to(directory)
                t = tok.tokenize(p)

                show_name = None
                if (t.is_episodic or t.is_anime) and t.title:
                    cleaned = clean_detected_show_name(t.title)
                    if len(cleaned) >= 2:
                        show_name = cleaned

                # If no show title from filename, check folder hierarchy
                if not show_name:
                    for part in rel.parts[:-1]:
                        part_tok = tok.tokenize(Path(part + p.suffix))
                        cleaned = clean_detected_show_name(part_tok.title if part_tok.title else part)
                        if len(cleaned) >= 2:
                            show_name = cleaned
                            break

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
                    if t.year and t.title:
                        detected_type = "movie"
                        cleaned_movie = clean_detected_show_name(t.title)
                        believed_title = f"{cleaned_movie} ({t.year})"
                        dest = str(movies_base / believed_title)
                    file_info["detected_type"] = detected_type
                    file_info["believed_title"] = believed_title
                    file_info["believed_destination"] = dest
                    singles.append(file_info)
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
        poster_url = fetch_show_poster(s_name, directory=directory, show_files=sorted_files)
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
    singles.sort(key=lambda x: x["name"].lower())
    all_files.sort(key=lambda x: x["name"].lower())

    return {
        "path": str(directory),
        "total_files": len(all_files),
        "files": all_files,
        "shows": shows_list,
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
                "version": "1.0.0",
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

    @app.get("/api/files")
    def get_files():
        """List files currently in downloads, movies, and shows directories."""
        downloads_path = settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")
        movies_path = settings.get_destination_path("movie")
        shows_path = settings.get_destination_path("tv")

        return {
            "downloads": inspect_downloads_folder(downloads_path, settings),
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
        return {"status": "deleted", "name": name}

    @app.get("/api/quarantine")
    def list_quarantine():
        with get_db_session(engine) as session:
            qm = QuarantineManager(session)
            items = qm.list_pending()
            return [
                {
                    "id": q.id,
                    "src": q.src,
                    "filename": Path(q.src).name,
                    "suggested_category": q.suggested_category,
                    "confidence": int((q.confidence or 0) * 100),
                    "reason": q.reason,
                    "signals": q.signals,
                    "created_at": q.created_at.strftime("%Y-%m-%d %H:%M:%S") if q.created_at else None,
                }
                for q in items
            ]

    @app.post("/api/quarantine/{item_id}/resolve")
    def resolve_quarantine(item_id: int, req: ResolveRequest):
        with get_db_session(engine) as session:
            qm = QuarantineManager(session)
            rec = qm.get_by_id(item_id)
            if not rec:
                raise HTTPException(status_code=404, detail="Quarantine item not found")

            # Determine destination based on chosen category
            category = req.category.lower()
            dest_dir = settings.get_destination_path("movie" if category == "movie" else "tv")
            src_path = Path(rec.src)

            # Move file to the designated library
            if src_path.exists():
                dest_dir.mkdir(parents=True, exist_ok=True)
                final_dst = dest_dir / src_path.name
                shutil.move(src_path, final_dst)
                qm.resolve_item(item_id, category, target_path=final_dst)
            else:
                qm.resolve_item(item_id, category)

            return {"status": "resolved", "item_id": item_id, "category": category}

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

    @app.get("/", response_class=HTMLResponse)
    def render_dashboard():
        """Serve the interactive modern Web Dashboard."""
        return r"""<!DOCTYPE html>
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
      --accent: #38bdf8;
      --accent-hover: #0284c7;
      --emerald: #10b981;
      --emerald-hover: #059669;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --indigo: #6366f1;
      --subbar-bg: rgba(0, 0, 0, 0.25);
      --badge-bg: #1e293b;
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

    * { box-sizing: border-box; margin: 0; padding: 0; }
    
    /* Scrollable app viewport - list scrolls without moving website header */
    html, body {
      height: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
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
      border-bottom: 1px solid var(--border);
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
      border-radius: 0.5rem;
    }
    .brand-title { font-size: 1.5rem; font-weight: 700; color: #fff; letter-spacing: -0.025em; }
    .brand-subtitle { font-size: 0.8rem; color: var(--text-muted); }
    .header-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }

    .btn {
      padding: 0.5rem 1rem;
      border-radius: 0.375rem;
      font-size: 0.875rem;
      font-weight: 600;
      cursor: pointer;
      border: 1px solid transparent;
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
    .btn-sm { padding: 0.25rem 0.6rem; font-size: 0.75rem; }

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
      border: 1px solid var(--border);
      border-radius: 0.6rem;
      padding: 1.25rem;
    }
    .stat-label { font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; margin-bottom: 0.35rem; }
    .stat-val { font-size: 1.75rem; font-weight: 700; color: #fff; }

    .panel {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 0.6rem;
      padding: 1.25rem;
      margin-bottom: 1.5rem;
    }
    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
    }
    .panel-title { font-size: 1.1rem; font-weight: 600; }

    table { width: 100%; border-collapse: collapse; text-align: left; }
    th { padding: 0.65rem 0.75rem; color: var(--text-muted); font-size: 0.8rem; font-weight: 600; border-bottom: 1px solid var(--border); background: var(--card-bg); }
    td { padding: 0.65rem 0.75rem; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
    tr:hover td { background: rgba(255, 255, 255, 0.02); }

    .tag {
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 0.25rem;
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
      border-radius: 0.375rem;
      padding: 0.6rem 0.75rem;
      color: var(--text);
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
      border: 1px solid var(--border);
      border-radius: 0.6rem;
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
      color: #fff;
    }
    .show-dropdown-badge {
      font-size: 0.75rem;
      background: var(--badge-bg);
      color: var(--text-muted);
      padding: 0.15rem 0.5rem;
      border-radius: 9999px;
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
      border: 1px solid var(--border);
      border-radius: 0.75rem;
      width: 92%;
      max-width: 580px;
      max-height: 88vh;
      overflow-y: auto;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
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
    .modal-title { font-size: 1.2rem; font-weight: 700; color: #fff; }
    .modal-close {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 1.5rem;
      cursor: pointer;
      line-height: 1;
    }
    .modal-close:hover { color: #fff; }

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
      border-radius: 0.5rem;
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
      color: #fff;
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
  </style>
</head>
<body>
  <div class="app-layout">
    <div class="top-bar-area">
      <div class="header">
        <div class="brand">
          <div class="brand-icon">📂</div>
          <div>
            <div class="brand-title" style="display: flex; align-items: center; gap: 0.5rem;">Media Sorter <span style="font-size: 0.72rem; font-weight: 600; vertical-align: middle; background: rgba(56, 189, 248, 0.18); color: var(--accent); border: 1px solid rgba(56, 189, 248, 0.4); padding: 0.12rem 0.5rem; border-radius: 9999px;">v1.0.0</span></div>
            <div class="brand-subtitle">Automated Downloads Organizer (Movies & Shows)</div>
          </div>
        </div>
        <div class="header-actions">
          <label style="display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.82rem; color: var(--text-muted); cursor: pointer; padding: 0 0.5rem;">
            <input type="checkbox" id="auto-refresh-chk" onchange="toggleAutoRefresh(this.checked)"> Auto-refresh (5s)
          </label>
          <button class="btn btn-emerald" onclick="triggerRun(false)">⚡ Run Sort Now (Live)</button>
          <button class="btn btn-accent" onclick="triggerRun(true)">🔍 Preview Sort (Dry-Run)</button>
          <button class="btn btn-amber" onclick="triggerRollback()">⏮ Rollback Batch</button>
          <button class="btn btn-outline" onclick="addSampleDownloads()">🧪 Add Test Samples</button>
          <button class="btn btn-outline" style="border-color: var(--accent); color: var(--accent); font-weight: 700;" onclick="openSettingsModal()">⚙️ Settings</button>
        </div>
      </div>

      <div class="nav-tabs">
        <div class="nav-tab active" id="nav-dashboard" onclick="switchTab('dashboard')">Dashboard & Activity</div>
        <div class="nav-tab" id="nav-files" onclick="switchTab('files')">Folder Explorer</div>
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
          <button class="btn btn-emerald btn-sm" onclick="triggerRun(false)">⚡ Sort All Files</button>
        </div>
      </div>

      <!-- Shows toolbar: Expand / Collapse All -->
      <div id="shows-toolbar" style="display: none; justify-content: space-between; align-items: center; margin: 0.75rem 0 1rem 0; padding: 0.5rem 0.85rem; background: rgba(255,255,255,0.02); border-radius: 0.375rem; border: 1px solid var(--border);">
        <span style="font-size: 0.82rem; color: var(--text-muted);">
          📁 Shows categorized in downloads: <strong id="toolbar-show-count" style="color: #fff;">0</strong>
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

      <!-- Container for Other / Standalone Files -->
      <div id="downloads-singles-container" style="display: none; margin-top: 1.5rem;">
        <h4 style="font-size: 0.95rem; font-weight: 600; color: #e2e8f0; margin-bottom: 0.65rem; display: flex; align-items: center; gap: 0.5rem;">
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
        <div style="font-size: 1.05rem; font-weight: 500; color: #fff;">No files in Downloads folder</div>
        <p style="font-size: 0.85rem; margin-top: 0.25rem;">New downloaded media will appear here ready to be categorized and organized.</p>
        <button class="btn btn-outline btn-sm" style="margin-top: 0.75rem;" onclick="addSampleDownloads()">Add Test Samples</button>
      </div>
    </div>
  </div>

  <!-- TAB 3: QUARANTINE REVIEW -->
  <div id="tab-quarantine" style="display: none;">
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Review & Quarantine Queue</div>
        <button class="btn btn-outline btn-sm" onclick="loadQuarantine()">Refresh</button>
      </div>
      <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1rem;">
        Files with confidence lower than your threshold are held safely here so you can review them and sort them into Movies or Shows with one click.
      </p>
      <div class="show-table-wrapper">
        <table>
          <thead>
            <tr>
              <th>File Name</th>
              <th>Reason</th>
              <th>Confidence</th>
              <th>Date Added</th>
              <th>Manual Action</th>
            </tr>
          </thead>
          <tbody id="quarantine-tbody">
            <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Quarantine queue is empty.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 4: SETTINGS & .ENV -->
  <div id="tab-settings" style="display: none;">
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1.5rem; max-width: 1200px;">
      
      <!-- Panel 1: Theme & Interface Preferences -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">🎨 Appearance & Themes (5 Themes)</div>
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
        </div>

        <div style="border-top: 1px solid var(--border); padding-top: 1.25rem; margin-top: 1.5rem;">
          <h4 style="font-size: 0.95rem; font-weight: 600; color: #fff; margin-bottom: 0.5rem;">⚡ Server Process Control</h4>
          <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.75rem;">
            Restart the server process to reload your environment and PM2 instance cleanly.
          </p>
          <button type="button" class="btn btn-amber" style="width: 100%; justify-content: center;" onclick="triggerServerRestart()">
            🔄 Restart Media Sorter Server
          </button>
        </div>

        <div style="border-top: 1px solid var(--border); padding-top: 1.25rem; margin-top: 1.25rem;">
          <h4 style="font-size: 0.95rem; font-weight: 600; color: #fff; margin-bottom: 0.5rem;">🗃️ Clear Activity & History</h4>
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
        <label class="form-label" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem;">
          <span>🎨 Color Theme (5 Themes)</span>
          <span style="font-size: 0.75rem; color: var(--text-muted);" id="active-theme-label">Cyber Dark</span>
        </label>
        <div class="theme-grid">
          <div class="theme-card active" data-theme-id="cyber-dark" onclick="setTheme('cyber-dark')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #090d16 50%, #38bdf8 50%);"></div>
            <div class="theme-title">Cyber Dark</div>
            <div class="theme-desc">Midnight & Sky Cyan</div>
            <div class="theme-check" id="check-cyber-dark">✓</div>
          </div>
          <div class="theme-card" data-theme-id="oled-neon" onclick="setTheme('oled-neon')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #000000 50%, #ec4899 50%);"></div>
            <div class="theme-title">Midnight OLED</div>
            <div class="theme-desc">True Black & Neon Pink</div>
            <div class="theme-check" id="check-oled-neon">✓</div>
          </div>
          <div class="theme-card" data-theme-id="nord-frost" onclick="setTheme('nord-frost')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #242933 50%, #88c0d0 50%);"></div>
            <div class="theme-title">Nord Arctic</div>
            <div class="theme-desc">Nordic Frost & Slate</div>
            <div class="theme-check" id="check-nord-frost">✓</div>
          </div>
          <div class="theme-card" data-theme-id="dracula" onclick="setTheme('dracula')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #151320 50%, #c4a7e7 50%);"></div>
            <div class="theme-title">Dracula Purple</div>
            <div class="theme-desc">Twilight Violet & Pastel</div>
            <div class="theme-check" id="check-dracula">✓</div>
          </div>
          <div class="theme-card" data-theme-id="emerald-matrix" onclick="setTheme('emerald-matrix')">
            <div class="theme-swatch" style="background: linear-gradient(135deg, #050c08 50%, #10b981 50%);"></div>
            <div class="theme-title">Emerald Matrix</div>
            <div class="theme-desc">Obsidian & Vivid Green</div>
            <div class="theme-check" id="check-emerald-matrix">✓</div>
          </div>
        </div>
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
      const mChk = document.getElementById(`check-${themeId}`);
      if (mChk) mChk.style.display = 'block';
      const tChk = document.getElementById(`tab-check-${themeId}`);
      if (tChk) tChk.style.display = 'block';
    }

    function openSettingsModal() {
      const modal = document.getElementById('modal-settings');
      if (modal) modal.style.display = 'flex';
      const cur = localStorage.getItem('ms-theme') || 'cyber-dark';
      setTheme(cur);
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
      const q = document.getElementById('tab-quarantine'); if (q) q.style.display = 'none';
      const s = document.getElementById('tab-settings'); if (s) s.style.display = 'none';

      const target = document.getElementById('tab-' + tab);
      if (target) target.style.display = 'block';
      const nav = document.getElementById('nav-' + tab);
      if (nav) nav.classList.add('active');

      if (tab === 'dashboard') loadDashboard();
      if (tab === 'files') loadFiles();
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

        loadDashboard();
      } catch (e) {
        showToast('Error executing run: ' + e);
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
      } catch (e) {
        showToast('Error executing rollback: ' + e);
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

    function renderDownloadsExplorer(downloads) {
      const pathElem = document.getElementById('path-downloads');
      if (pathElem) pathElem.textContent = downloads.path || '';

      const totalFiles = downloads.total_files || (downloads.files ? downloads.files.length : 0);
      const shows = downloads.shows || [];
      const singles = downloads.singles || [];

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
                    <div style="font-size: 0.95rem; font-weight: 600; color: #fff; margin-bottom: 0.2rem;">${showNameEsc}</div>
                    <div>
                      <span>Target Destination: </span>
                      <code style="color: var(--emerald); font-size: 0.8rem;">${destFolderEsc}</code>
                    </div>
                  </div>
                </div>
                <button class="btn btn-emerald btn-sm" onclick="triggerRun(false)">⚡ Sort Now</button>
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
          show.files.forEach(f => {
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
                <button class="btn btn-outline btn-sm" style="color: var(--rose); border-color: var(--rose);" title="Delete from downloads" onclick="deleteDownloadFile('${escapeJs(delTarget)}')">🗑️</button>
              </td>
            `;
            tbody.appendChild(tr);
          });
        });
      }

      // Render Singles / Other Media
      if (singlesContainer && singlesTbody) {
        if (singles.length > 0) {
          singlesContainer.style.display = 'block';
          const singlesBadge = document.getElementById('singles-count-badge');
          if (singlesBadge) singlesBadge.textContent = `${singles.length} file${singles.length === 1 ? '' : 's'}`;
          singlesTbody.innerHTML = '';
          singles.forEach(f => {
            const tr = document.createElement('tr');
            const typeTag = f.detected_type === 'movie' ? '<span class="tag tag-movie">MOVIE</span>' : '<span class="tag tag-dry">FILE</span>';
            const delTarget = f.relative_path || f.name;
            tr.innerHTML = `
              <td>
                <code>${escapeHtml(f.name)}</code>
                <div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(f.relative_path)}</div>
              </td>
              <td>${typeTag}</td>
              <td><strong style="color: #fff;">${escapeHtml(f.believed_title || f.name)}</strong></td>
              <td>${escapeHtml(f.size)}</td>
              <td>
                <button class="btn btn-outline btn-sm" style="color: var(--rose); border-color: var(--rose);" title="Delete from downloads" onclick="deleteDownloadFile('${escapeJs(delTarget)}')">🗑️</button>
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

    async function loadQuarantine() {
      try {
        const res = await fetch('/api/quarantine');
        const items = await res.json();
        const tbody = document.getElementById('quarantine-tbody');
        tbody.innerHTML = '';
        if (items.length === 0) {
          tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Quarantine queue is empty.</td></tr>';
          document.getElementById('quar-badge').style.display = 'none';
        } else {
          document.getElementById('quar-badge').textContent = items.length;
          document.getElementById('quar-badge').style.display = 'inline-block';
          items.forEach(q => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td><code>${q.filename}</code></td>
              <td style="color: var(--rose);">${q.reason}</td>
              <td>${q.confidence}%</td>
              <td>${q.created_at || '-'}</td>
              <td>
                <button class="btn btn-accent btn-sm" onclick="resolveItem(${q.id}, 'movie')">🎬 Movie</button>
                <button class="btn btn-emerald btn-sm" onclick="resolveItem(${q.id}, 'tv')">📺 Show</button>
              </td>
            `;
            tbody.appendChild(tr);
          });
        }
      } catch (e) {
        console.error(e);
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

    loadDashboard();
  </script>
</body>
</html>
"""

    return app
