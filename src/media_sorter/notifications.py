"""Notification dispatcher for Media Sorter.

Sends batch summary alerts and error notices to webhook endpoints (Slack, Discord, generic JSON).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
import structlog

from .config import NotificationSettings
from .executor import BatchExecutionReport

logger = structlog.get_logger(__name__)


def send_batch_notification(
    settings: NotificationSettings, report: BatchExecutionReport
) -> bool:
    """Send webhook alert for completed or failed batch."""
    if not settings.enabled or not settings.webhook_url:
        return False

    is_failure = report.failed_files > 0
    if is_failure and not settings.notify_on_failure:
        return False
    if not is_failure and not settings.notify_on_complete:
        return False

    status_str = "FAILED" if is_failure else ("DRY RUN PREVIEW" if report.dry_run else "SUCCESS")
    title = f"Media Sorter: {status_str} [Batch {report.batch_id[:8]}]"

    summary_text = (
        f"**{title}**\n"
        f"• Total Files: {report.total_files}\n"
        f"• Organized/Moved: {report.moved_files}\n"
        f"• Copied: {report.copied_files}\n"
        f"• Skipped: {report.skipped_files}\n"
        f"• Quarantined: {report.quarantined_files}\n"
        f"• Failures: {report.failed_files}\n"
    )
    if report.errors:
        summary_text += f"\nErrors:\n" + "\n".join(f"- {e}" for e in report.errors[:5])

    payload: Dict[str, Any] = {
        "text": summary_text,
        "content": summary_text,  # Discord format compatibility
        "batch_id": report.batch_id,
        "dry_run": report.dry_run,
        "status": status_str,
        "total_files": report.total_files,
        "moved_files": report.moved_files,
        "quarantined_files": report.quarantined_files,
        "failed_files": report.failed_files,
    }

    try:
        resp = requests.post(settings.webhook_url, json=payload, timeout=5.0)
        if resp.status_code in (200, 201, 204):
            return True
        logger.warning("Webhook dispatch failed", status=resp.status_code)
    except Exception as e:
        logger.warning("Failed sending notification webhook", error=str(e))

    return False
