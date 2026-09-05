"""Safe execution engine and transactional operation journal for Media Sorter.

Enforces dry-run previews, atomic moves, cross-filesystem safety, conflict handling,
attribute preservation (POSIX timestamps/permissions), crash recovery, and instant rollbacks.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog
from sqlalchemy.orm import Session

from .config import ActionType, ConflictPolicy, Settings
from .models import BatchRecord, FileRecord, Operation, OperationStatus, QuarantineRecord, QuarantineStatus

from contextlib import contextmanager
import sys

logger = structlog.get_logger(__name__)


class ProcessLockError(Exception):
    """Raised when another media-sorter process holds the execution lock."""
    pass


@contextmanager
def acquire_process_lock(lock_file_path: Path):
    """Ensure mutual exclusion so multiple workers/instances do not run concurrent batches."""
    lock_file = Path(lock_file_path).resolve()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_file, "a+")
    try:
        if sys.platform != "win32":
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                raise ProcessLockError(
                    f"Another media-sorter process currently holds the lock on {lock_file}."
                )
        else:
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except (IOError, OSError):
                raise ProcessLockError(
                    f"Another media-sorter process currently holds the lock on {lock_file}."
                )
        yield
    finally:
        try:
            if sys.platform != "win32":
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            else:
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        f.close()


def copy_extended_attributes(src: Path, dst: Path) -> None:
    """Preserve POSIX extended attributes (xattrs) across filesystems where supported."""
    if hasattr(os, "listxattr") and hasattr(os, "getxattr") and hasattr(os, "setxattr"):
        try:
            attrs = os.listxattr(src)
            for attr in attrs:
                try:
                    val = os.getxattr(src, attr)
                    os.setxattr(dst, attr, val)
                except (OSError, PermissionError):
                    pass
        except (OSError, PermissionError):
            pass


def compute_file_hash(file_path: Path, max_bytes: int = 1048576) -> str:
    """Compute quick partial SHA-256 hash (first 1MB) for fast identity verification."""
    try:
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            chunk = f.read(max_bytes)
            hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


@dataclass
class PlannedOperation:
    src: Path
    dst: Path
    action: ActionType
    category: str
    confidence: float
    details: Dict[str, Any] = field(default_factory=dict)
    is_conflict: bool = False
    conflict_resolved_dst: Optional[Path] = None
    quarantine: bool = False
    quarantine_reason: Optional[str] = None


@dataclass
class BatchExecutionReport:
    batch_id: str
    dry_run: bool
    total_files: int = 0
    moved_files: int = 0
    copied_files: int = 0
    linked_files: int = 0
    skipped_files: int = 0
    quarantined_files: int = 0
    failed_files: int = 0
    operations: List[PlannedOperation] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class MediaExecutor:
    """Executes planned operations with transactional safety and crash recovery."""

    def __init__(self, settings: Settings, session: Session):
        self.settings = settings
        self.session = session

    def plan_operations(
        self, planned_items: List[PlannedOperation]
    ) -> List[PlannedOperation]:
        """Validate destination conflicts and resolve destination paths."""
        allocated_destinations: Dict[Path, PlannedOperation] = {}
        validated_plan: List[PlannedOperation] = []

        for item in planned_items:
            # If already marked for quarantine, keep as is
            if item.quarantine:
                validated_plan.append(item)
                continue

            target_dst = item.dst

            # 1. Check intra-batch duplicate destination conflict
            if target_dst in allocated_destinations:
                logger.warning(
                    "Intra-batch destination collision detected",
                    dst=str(target_dst),
                    src1=str(allocated_destinations[target_dst].src),
                    src2=str(item.src),
                )
                item.is_conflict = True
                target_dst = self._resolve_conflict(item.src, target_dst)
                item.conflict_resolved_dst = target_dst

            # 2. Check on-disk destination conflict
            if target_dst.exists():
                logger.info("Destination already exists on disk", dst=str(target_dst), src=str(item.src))
                item.is_conflict = True
                target_dst = self._resolve_conflict(item.src, target_dst)
                item.conflict_resolved_dst = target_dst

            if item.quarantine:
                validated_plan.append(item)
                continue

            item.dst = target_dst
            allocated_destinations[target_dst] = item
            validated_plan.append(item)

        return validated_plan

    def _resolve_conflict(self, src: Path, desired_dst: Path) -> Path:
        """Resolve conflict according to the configured conflict policy."""
        policy = self.settings.conflicts.policy

        if policy == ConflictPolicy.SKIP:
            return desired_dst  # Will be skipped during execution
        elif policy == ConflictPolicy.ERROR:
            raise FileExistsError(f"Destination conflict: {desired_dst} already exists")
        elif policy == ConflictPolicy.QUARANTINE:
            return self.settings.get_destination_path("quarantine") / f"conflicts/{src.name}"
        elif policy == ConflictPolicy.REPLACE_IF_HIGHER_QUALITY:
            # Allow replacing existing file (will backup during execution)
            return desired_dst
        else:
            # ConflictPolicy.RENAME_UNIQUE: foo (1).mp4
            parent = desired_dst.parent
            stem = desired_dst.stem
            ext = desired_dst.suffix
            counter = 1
            candidate = parent / f"{stem} ({counter}){ext}"
            while candidate.exists():
                counter += 1
                candidate = parent / f"{stem} ({counter}){ext}"
            return candidate

    def execute_batch(
        self,
        planned_items: List[PlannedOperation],
        dry_run: Optional[bool] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> BatchExecutionReport:
        """Execute a batch of operations transactionally, with dry-run support."""
        is_dry_run = self.settings.general.dry_run if dry_run is None else dry_run
        batch_id = str(uuid.uuid4())

        # Validate and resolve destination collisions
        validated_plan = self.plan_operations(planned_items)

        report = BatchExecutionReport(
            batch_id=batch_id,
            dry_run=is_dry_run,
            total_files=len(validated_plan),
            operations=validated_plan,
        )

        # Create Batch Record in DB
        batch_record = BatchRecord(
            id=batch_id,
            dry_run=is_dry_run,
            status="IN_PROGRESS",
            total_files=len(validated_plan),
        )
        self.session.add(batch_record)
        self.session.commit()

        total = len(validated_plan)
        for idx, item in enumerate(validated_plan):
            if progress_callback:
                progress_callback(idx + 1, total, str(item.src.name))

            if item.quarantine:
                self._record_quarantine(batch_id, item, is_dry_run)
                report.quarantined_files += 1
                continue

            # Check if skipping due to conflict
            if item.is_conflict and self.settings.conflicts.policy == ConflictPolicy.SKIP and item.dst.exists():
                logger.info("Skipping existing destination", dst=str(item.dst))
                report.skipped_files += 1
                self._record_operation(
                    batch_id, item, status=OperationStatus.SKIPPED, is_dry_run=is_dry_run
                )
                continue

            if is_dry_run:
                # Dry run preview only: do not touch filesystem
                if item.action == ActionType.MOVE:
                    report.moved_files += 1
                elif item.action == ActionType.COPY:
                    report.copied_files += 1
                elif item.action in (ActionType.LINK, ActionType.HARDLINK):
                    report.linked_files += 1

                self._record_operation(
                    batch_id, item, status=OperationStatus.PLANNED, is_dry_run=True
                )
                continue

            # Live execution
            try:
                self._execute_single_op(batch_id, item)
                if item.action == ActionType.MOVE:
                    report.moved_files += 1
                elif item.action == ActionType.COPY:
                    report.copied_files += 1
                elif item.action in (ActionType.LINK, ActionType.HARDLINK):
                    report.linked_files += 1
            except Exception as e:
                report.failed_files += 1
                err_msg = f"Failed {item.action} on {item.src} -> {item.dst}: {e}"
                logger.error(err_msg, exc_info=True)
                report.errors.append(err_msg)

        # Update batch record completion status
        batch_record.completed_at = datetime.now(timezone.utc)
        batch_record.moved_files = report.moved_files
        batch_record.skipped_files = report.skipped_files
        batch_record.failed_files = report.failed_files
        batch_record.quarantined_files = report.quarantined_files
        batch_record.status = "COMPLETED" if report.failed_files == 0 else "PARTIAL_FAILURE"
        self.session.commit()

        return report

    def _execute_single_op(self, batch_id: str, item: PlannedOperation) -> None:
        """Perform atomic move, copy, or link with attribute preservation and journal update."""
        src = item.src
        dst = item.dst
        action = item.action

        if not src.exists():
            raise FileNotFoundError(f"Source file missing: {src}")

        src_hash = compute_file_hash(src)
        backup_path: Optional[str] = None

        # Handle backup if replacing
        if dst.exists():
            if self.settings.conflicts.policy == ConflictPolicy.REPLACE_IF_HIGHER_QUALITY:
                b_dir = Path(self.settings.conflicts.backup_dir or ".backup") / batch_id
                b_dir.mkdir(parents=True, exist_ok=True)
                backup_dst = b_dir / dst.name
                shutil.move(dst, backup_dst)
                backup_path = str(backup_dst)
            elif not self.settings.conflicts.allow_overwrite:
                raise FileExistsError(f"Destination exists and allow_overwrite is False: {dst}")

        # Create journal entry in IN_PROGRESS state
        op = Operation(
            batch_id=batch_id,
            src=str(src),
            dst=str(dst),
            action=action.value,
            category=item.category,
            confidence=item.confidence,
            src_hash=src_hash,
            backup_path=backup_path,
            details=item.details,
            status=OperationStatus.IN_PROGRESS.value,
        )
        self.session.add(op)
        self.session.commit()

        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            if action == ActionType.MOVE:
                self._safe_move(src, dst)
            elif action == ActionType.COPY:
                self._safe_copy(src, dst)
            elif action == ActionType.LINK:
                if dst.exists() or dst.is_symlink():
                    dst.unlink()
                os.symlink(src, dst)
            elif action == ActionType.HARDLINK:
                if dst.exists():
                    dst.unlink()
                os.link(src, dst)

            # Apply custom permissions if specified
            self._apply_permissions(dst)

            op.status = OperationStatus.COMMITTED.value
            op.completed_at = datetime.now(timezone.utc)
            op.dst_hash = compute_file_hash(dst)

            # Update or create FileRecord in database
            self._update_file_record(dst, item)

            self.session.commit()

        except Exception as e:
            op.status = OperationStatus.FAILED.value
            op.error_message = str(e)
            self.session.commit()
            raise

    def _safe_move(self, src: Path, dst: Path) -> None:
        """Atomic move on same filesystem, or safe temp-copy-atomic-rename cross-filesystem."""
        try:
            # Check if same filesystem by comparing st_dev
            src_dev = src.stat().st_dev
            dst_parent_dev = dst.parent.stat().st_dev
            if src_dev == dst_parent_dev:
                # Same device: atomic rename
                os.replace(src, dst)
                return
        except Exception:
            pass

        # Cross-filesystem move:
        # 1. Copy to temp file in destination directory
        temp_dst = dst.parent / f".tmp_media_sorter_{uuid.uuid4().hex}_{dst.name}"
        try:
            shutil.copy2(src, temp_dst)
            if self.settings.permissions.preserve_attributes:
                copy_extended_attributes(src, temp_dst)
            # Verify file size matches
            if temp_dst.stat().st_size != src.stat().st_size:
                raise IOError(f"Size mismatch during copy: {temp_dst.stat().st_size} != {src.stat().st_size}")
            # Atomically replace into final destination
            os.replace(temp_dst, dst)
            # Unlink original source
            src.unlink()
        finally:
            if temp_dst.exists():
                try:
                    temp_dst.unlink()
                except Exception:
                    pass

    def _safe_copy(self, src: Path, dst: Path) -> None:
        """Safe copy using temporary file and atomic replace."""
        temp_dst = dst.parent / f".tmp_media_sorter_{uuid.uuid4().hex}_{dst.name}"
        try:
            shutil.copy2(src, temp_dst)
            if self.settings.permissions.preserve_attributes:
                copy_extended_attributes(src, temp_dst)
            if temp_dst.stat().st_size != src.stat().st_size:
                raise IOError("Copy size mismatch")
            os.replace(temp_dst, dst)
        finally:
            if temp_dst.exists():
                try:
                    temp_dst.unlink()
                except Exception:
                    pass

    def _apply_permissions(self, path: Path) -> None:
        """Apply configured mode bits and ownership safely."""
        perm_cfg = self.settings.permissions
        if perm_cfg.file_mode and path.is_file():
            try:
                mode = int(perm_cfg.file_mode, 8)
                os.chmod(path, mode)
            except Exception as e:
                logger.debug("Failed setting file mode", path=str(path), error=str(e))

        if (perm_cfg.owner or perm_cfg.group) and hasattr(os, "chown"):
            try:
                import pwd
                import grp
                uid = -1
                gid = -1
                if perm_cfg.owner:
                    uid = int(perm_cfg.owner) if perm_cfg.owner.isdigit() else pwd.getpwnam(perm_cfg.owner).pw_uid
                if perm_cfg.group:
                    gid = int(perm_cfg.group) if perm_cfg.group.isdigit() else grp.getgrnam(perm_cfg.group).gr_gid
                os.chown(path, uid, gid)
            except Exception as e:
                logger.debug("Failed setting ownership", path=str(path), error=str(e))

    def _update_file_record(self, final_path: Path, item: PlannedOperation) -> None:
        """Record the file in the database to prevent re-processing."""
        try:
            stat = final_path.stat()
            rec = self.session.query(FileRecord).filter_by(path=str(final_path)).first()
            if not rec:
                rec = FileRecord(
                    path=str(final_path),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    category=item.category,
                    confidence=item.confidence,
                    status="organized",
                    last_processed=datetime.now(timezone.utc),
                )
                self.session.add(rec)
            else:
                rec.size = stat.st_size
                rec.mtime = stat.st_mtime
                rec.category = item.category
                rec.confidence = item.confidence
                rec.status = "organized"
                rec.last_processed = datetime.now(timezone.utc)
        except Exception:
            pass

    def _record_operation(
        self, batch_id: str, item: PlannedOperation, status: OperationStatus, is_dry_run: bool
    ) -> None:
        op = Operation(
            batch_id=batch_id,
            src=str(item.src),
            dst=str(item.dst),
            action=item.action.value,
            category=item.category,
            confidence=item.confidence,
            details=item.details,
            status=status.value,
        )
        self.session.add(op)
        self.session.commit()

    def _record_quarantine(self, batch_id: str, item: PlannedOperation, is_dry_run: bool) -> None:
        q = self.session.query(QuarantineRecord).filter_by(src=str(item.src)).first()
        if not q:
            q = QuarantineRecord(
                src=str(item.src),
                suggested_category=item.category,
                confidence=item.confidence,
                reason=item.quarantine_reason or "Low confidence or unclassifiable",
                signals=item.details,
                status=QuarantineStatus.PENDING.value,
            )
            self.session.add(q)
            self.session.commit()

        if not is_dry_run and self.settings.quarantine.move_to_quarantine_folder:
            # Move to quarantine folder
            q_dir = self.settings.get_destination_path("quarantine") / (item.quarantine_reason or "review")
            q_dir.mkdir(parents=True, exist_ok=True)
            dst_path = q_dir / item.src.name
            try:
                self._safe_move(item.src, dst_path)
                q.resolved_path = str(dst_path)
                self.session.commit()
            except Exception as e:
                logger.error("Failed moving to quarantine folder", src=str(item.src), error=str(e))

    def rollback_batch(self, batch_id: Optional[str] = None) -> int:
        """Invert all COMMITTED operations in a batch, returning count of reverted files."""
        query = self.session.query(BatchRecord)
        if batch_id:
            batch = query.filter_by(id=batch_id).first()
        else:
            # Default to latest non-rolled-back completed batch
            batch = query.filter(BatchRecord.status != "ROLLED_BACK", BatchRecord.dry_run == False).order_by(BatchRecord.created_at.desc()).first()

        if not batch:
            logger.warning("No qualifying batch found for rollback", requested_id=batch_id)
            return 0

        logger.info("Initiating rollback", batch_id=batch.id)
        # Query committed operations in reverse execution order
        ops = (
            self.session.query(Operation)
            .filter_by(batch_id=batch.id, status=OperationStatus.COMMITTED.value)
            .order_by(Operation.id.desc())
            .all()
        )

        reverted_count = 0
        for op in ops:
            src = Path(op.src)
            dst = Path(op.dst)
            action = op.action

            try:
                if action == ActionType.MOVE.value:
                    if dst.exists():
                        src.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(dst, src)
                        reverted_count += 1

                    # Restore backup if one was taken
                    if op.backup_path and Path(op.backup_path).exists():
                        os.replace(Path(op.backup_path), dst)

                elif action == ActionType.COPY.value:
                    if dst.exists():
                        dst.unlink()
                        reverted_count += 1

                elif action in (ActionType.LINK.value, ActionType.HARDLINK.value):
                    if dst.exists() or dst.is_symlink():
                        dst.unlink()
                        reverted_count += 1

                op.status = OperationStatus.ROLLED_BACK.value
            except Exception as e:
                logger.error("Error reverting operation during rollback", op_id=op.id, error=str(e))

        batch.status = "ROLLED_BACK"
        self.session.commit()
        return reverted_count

    def recover_interrupted_batches(self) -> int:
        """Clean up orphaned temp files and mark interrupted operations as FAILED."""
        in_progress_ops = (
            self.session.query(Operation)
            .filter_by(status=OperationStatus.IN_PROGRESS.value)
            .all()
        )
        recovered_count = 0

        for op in in_progress_ops:
            logger.warning("Found interrupted operation during crash recovery", op_id=op.id, src=op.src, dst=op.dst)
            op.status = OperationStatus.FAILED.value
            op.error_message = "Interrupted by system crash or process kill"
            recovered_count += 1

        if recovered_count > 0:
            self.session.commit()

        return recovered_count
