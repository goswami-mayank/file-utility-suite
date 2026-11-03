"""Safe temporary upload storage and age-based file cleanup."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Collection

from fastapi import UploadFile

logger = logging.getLogger(__name__)
CHUNK_SIZE = 1024 * 1024


def ensure_storage_directories(*directories: Path) -> None:
    """Create storage directories when they do not already exist."""
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


async def save_upload(
    upload: UploadFile,
    destination: Path,
    allowed_extensions: Collection[str],
    *,
    max_bytes: int,
) -> Path:
    """Save an upload with a generated name and enforce extension and size limits."""
    original_name = Path(upload.filename or "").name
    extension = Path(original_name).suffix.lower()
    normalized_extensions = {item.lower() for item in allowed_extensions}
    if extension not in normalized_extensions:
        allowed = ", ".join(sorted(normalized_extensions))
        raise ValueError(f"Unsupported file type. Accepted file types: {allowed}.")
    if not original_name or original_name in {".", ".."}:
        raise ValueError("The uploaded file must have a valid filename.")

    ensure_storage_directories(destination)
    safe_extension = re.sub(r"[^a-z0-9.]", "", extension)
    target = destination / f"{uuid.uuid4().hex}{safe_extension}"
    total_bytes = 0
    try:
        with target.open("xb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise ValueError(
                        f"{original_name} is too large. The maximum file size is "
                        f"{max_bytes // (1024 * 1024)} MB."
                    )
                output.write(chunk)
        if total_bytes == 0:
            raise ValueError(f"{original_name} is empty. Choose a non-empty file.")
        return target
    except Exception:
        remove_file(target)
        raise


def remove_file(path: Path) -> None:
    """Remove one file if it exists, logging cleanup failures."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning(
            "Could not remove temporary file %s",
            path,
            exc_info=True,
        )


def cleanup_old_files(
    directories: Collection[Path],
    *,
    max_age_hours: int,
) -> int:
    """Delete files older than the retention period and return the count removed."""
    if max_age_hours < 1:
        raise ValueError("The file retention period must be at least one hour.")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    removed_count = 0
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            try:
                if path.is_file() and not path.name.startswith("."):
                    modified = datetime.fromtimestamp(
                        path.stat().st_mtime,
                        timezone.utc,
                    )
                    if modified < cutoff:
                        path.unlink()
                        removed_count += 1
            except OSError:
                logger.warning(
                    "Could not inspect or remove stale file %s",
                    path,
                    exc_info=True,
                )
    if removed_count:
        logger.info("Removed %d stale file(s).", removed_count)
    return removed_count
