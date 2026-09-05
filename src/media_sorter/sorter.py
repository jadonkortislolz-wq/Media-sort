"""Main orchestration pipeline for Media Sorter.

Coordinates filesystem scanning, caching, parallel metadata probing, classification,
naming, dry-run previews, atomic execution, and audit logging.
"""

from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import structlog
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .analyzer import MediaAnalyzer, MediaMetadata
from .classifier import ClassificationResult, MediaClassifier
from .config import ActionType, Settings
from .db import get_db_session
from .executor import BatchExecutionReport, MediaExecutor, PlannedOperation, acquire_process_lock
from .models import FileRecord
from .namer import MediaNamer
from .notifications import send_batch_notification
from .providers import MetadataProvider, TMDBProvider
from .scanner import ScannedFile, Scanner
from .tokenizer import FilenameTokenizer, TokenizedFilename

logger = structlog.get_logger(__name__)


class MediaSorterApp:
    """High-performance orchestrator for analyzing and organizing media collections."""

    def __init__(self, settings: Settings, engine: Engine):
        self.settings = settings
        self.engine = engine

        # Component instances
        self.scanner = Scanner(
            min_file_age_seconds=settings.general.min_file_age_seconds,
            include_patterns=settings.filters.include_patterns,
            exclude_patterns=settings.filters.exclude_patterns,
        )
        self.tokenizer = FilenameTokenizer()
        self.analyzer = MediaAnalyzer()

        # Metadata provider
        provider: Optional[MetadataProvider] = None
        if settings.providers.enable_online_metadata:
            provider = TMDBProvider(
                api_key=settings.providers.tmdb_api_key,
                rate_limit_per_second=settings.providers.rate_limit_per_second,
            )

        self.classifier = MediaClassifier(
            confidence_threshold=settings.general.confidence_threshold,
            provider=provider,
        )
        self.namer = MediaNamer(settings)

    def scan_and_analyze(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        filter_paths: Optional[List[Path]] = None,
    ) -> List[Tuple[ScannedFile, ClassificationResult]]:
        """Discover files across all configured source directories and analyze in parallel."""
        source_paths = self.settings.get_source_paths()
        all_scanned: List[ScannedFile] = []

        logger.info("Starting library discovery", sources=[str(p) for p in source_paths])
        for src in source_paths:
            if src.exists():
                discovered = self.scanner.scan_directory(src)
                all_scanned.extend(discovered)
            else:
                logger.warning("Configured source path does not exist", path=str(src))

        logger.info("Filesystem discovery complete", total_discovered=len(all_scanned))

        if not all_scanned:
            return []

        # Check DB cache to skip unchanged already organized files
        qualifying_files: List[ScannedFile] = []
        with get_db_session(self.engine) as session:
            for s in all_scanned:
                rec = (
                    session.query(FileRecord)
                    .filter_by(path=str(s.path), size=s.size, mtime=s.mtime, status="organized")
                    .first()
                )
                if rec:
                    logger.debug("Skipping unchanged already organized file", path=str(s.path))
                    continue
                qualifying_files.append(s)

        if filter_paths:
            filter_resolved = {p.resolve() for p in filter_paths}
            qualifying_files = [s for s in qualifying_files if s.path.resolve() in filter_resolved]

        total_files = len(qualifying_files)
        logger.info("Files requiring processing", count=total_files)

        # Parallel analysis and classification
        results: List[Tuple[ScannedFile, ClassificationResult]] = []
        worker_count = self.settings.general.worker_count

        def process_one(scanned: ScannedFile) -> Tuple[ScannedFile, ClassificationResult]:
            tokens = self.tokenizer.tokenize(scanned.path)
            meta = self.analyzer.analyze(scanned.path)
            classification = self.classifier.classify(scanned, tokens, meta)
            return scanned, classification

        completed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_file = {executor.submit(process_one, sf): sf for sf in qualifying_files}
            for future in concurrent.futures.as_completed(future_to_file):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as e:
                    sf = future_to_file[future]
                    logger.error("Error analyzing file", path=str(sf.path), error=str(e))
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_files, str(future_to_file[future].path.name))

        return results

    def build_plan(
        self, analysis_results: List[Tuple[ScannedFile, ClassificationResult]]
    ) -> List[PlannedOperation]:
        """Convert classification results into concrete planned operations."""
        primary_dest_map: Dict[Path, Path] = {}
        plan: List[PlannedOperation] = []

        # 1. First pass: non-sidecar primary media files
        for scanned, cls_res in analysis_results:
            if not scanned.is_sidecar:
                dst = self.namer.generate_destination_path(cls_res)
                primary_dest_map[scanned.path] = dst

                plan.append(
                    PlannedOperation(
                        src=scanned.path,
                        dst=dst,
                        action=self.settings.general.action,
                        category=cls_res.category,
                        confidence=cls_res.confidence,
                        details=cls_res.signals,
                        quarantine=cls_res.needs_quarantine,
                        quarantine_reason=cls_res.quarantine_reason,
                    )
                )

        # 2. Second pass: sidecars (subtitles, artwork, metadata) matching primary destinations
        for scanned, cls_res in analysis_results:
            if scanned.is_sidecar:
                primary_dst = (
                    primary_dest_map.get(scanned.primary_media_path)
                    if scanned.primary_media_path
                    else None
                )
                dst = self.namer.generate_destination_path(cls_res, primary_dst_path=primary_dst)

                plan.append(
                    PlannedOperation(
                        src=scanned.path,
                        dst=dst,
                        action=self.settings.general.action,
                        category=cls_res.category,
                        confidence=cls_res.confidence,
                        details=cls_res.signals,
                        quarantine=cls_res.needs_quarantine,
                        quarantine_reason=cls_res.quarantine_reason,
                    )
                )

        return plan

    def run(
        self,
        dry_run: Optional[bool] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        filter_paths: Optional[List[Path]] = None,
        show_name_override: Optional[str] = None,
    ) -> BatchExecutionReport:
        """Run full media sorter pipeline: scan, analyze, plan, and execute."""
        start_time = time.time()
        is_dry_run = self.settings.general.dry_run if dry_run is None else dry_run

        logger.info("Executing media-sorter run", dry_run=is_dry_run)

        # Discover and analyze
        analysis_results = self.scan_and_analyze(
            progress_callback=progress_callback, filter_paths=filter_paths
        )

        if show_name_override:
            for scanned, cls_res in analysis_results:
                cls_res.category = "tv"
                if not cls_res.tokens.title or cls_res.tokens.title.lower() in ("episode", "unknown", ""):
                    cls_res.tokens.title = show_name_override
                cls_res.tokens.is_episodic = True
                cls_res.needs_quarantine = False
                cls_res.confidence = max(cls_res.confidence, 0.95)

        # Build plan
        planned_ops = self.build_plan(analysis_results)

        # Execute under inter-process lock to coordinate workers
        lock_path = self.settings.get_database_path().with_suffix(".lock")
        with acquire_process_lock(lock_path):
            with get_db_session(self.engine) as session:
                executor = MediaExecutor(self.settings, session)
                # Check for crash recovery from prior runs
                executor.recover_interrupted_batches()

                report = executor.execute_batch(
                    planned_ops, dry_run=is_dry_run, progress_callback=progress_callback
                )

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            "Media sorter run finished",
            elapsed_seconds=elapsed,
            total=report.total_files,
            moved=report.moved_files,
            quarantined=report.quarantined_files,
            skipped=report.skipped_files,
            failed=report.failed_files,
        )

        # Send notification webhook if configured
        if self.settings.notifications.enabled:
            send_batch_notification(self.settings.notifications, report)

        return report

    def rollback(self, batch_id: Optional[str] = None) -> int:
        """Rollback a past batch of operations."""
        with get_db_session(self.engine) as session:
            executor = MediaExecutor(self.settings, session)
            return executor.rollback_batch(batch_id)

    def rollback_all(self) -> int:
        """Rollback all past completed batches."""
        with get_db_session(self.engine) as session:
            executor = MediaExecutor(self.settings, session)
            return executor.rollback_all()

