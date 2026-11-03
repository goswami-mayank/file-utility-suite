"""FastAPI endpoints for audio and video processing."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from services.cleanup import remove_file, save_upload
from services.media_service import (
    MEDIA_EXTENSIONS,
    MediaProcessingError,
    add_caption,
    crop_video,
    get_media_kind,
    merge_media,
    trim_media,
    validate_merge_inputs,
)

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_UPLOAD_BYTES = 250 * 1024 * 1024


@router.post("/media/trim", name="trim_media")
async def trim_media_route(
    file: UploadFile = File(...),
    start: float = Form(...),
    end: float = Form(...),
) -> FileResponse:
    """Trim a selected time range from an audio or video file."""
    return await _process_uploads(
        [file],
        lambda paths, output: trim_media(paths[0], output, start, end),
        lambda kind: f"trimmed-{kind}.{'mp3' if kind == 'audio' else 'mp4'}",
    )


@router.post("/media/crop", name="crop_video")
async def crop_video_route(
    file: UploadFile = File(...),
    x: int = Form(...),
    y: int = Form(...),
    width: int = Form(...),
    height: int = Form(...),
) -> FileResponse:
    """Crop a video to the submitted rectangle."""
    return await _process_uploads(
        [file],
        lambda paths, output: crop_video(paths[0], output, x, y, width, height),
        lambda _: "cropped-video.mp4",
        expected_kind="video",
    )


@router.post("/media/caption", name="caption_video")
async def caption_video_route(
    file: UploadFile = File(...),
    caption: str = Form(...),
    start: float = Form(...),
    end: float = Form(...),
) -> FileResponse:
    """Burn a custom caption into a selected time range of a video."""
    return await _process_uploads(
        [file],
        lambda paths, output: add_caption(paths[0], output, caption, start, end),
        lambda _: "captioned-video.mp4",
        expected_kind="video",
    )


@router.post("/media/merge", name="merge_media")
async def merge_media_route(
    files: list[UploadFile] = File(...),
) -> FileResponse:
    """Merge compatible audio files or compatible video files in selection order."""
    try:
        kind = validate_merge_inputs([file.filename or "" for file in files])
    except MediaProcessingError as exc:
        for file in files:
            await file.close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _process_uploads(
        files,
        lambda paths, output: merge_media(paths, output),
        lambda _: f"merged-{kind}.{'mp3' if kind == 'audio' else 'mp4'}",
        expected_kind=kind,
    )


async def _process_uploads(
    uploads: Sequence[UploadFile],
    operation: Callable[[list[Path], Path], Path],
    download_name: Callable[[str], str],
    *,
    expected_kind: str | None = None,
) -> FileResponse:
    """Stage bounded uploads, process them off-loop, and return a temporary download."""
    output_path: Path | None = None
    staged_paths: list[Path] = []
    try:
        filenames = [upload.filename or "" for upload in uploads]
        kind = (
            validate_merge_inputs(filenames)
            if len(uploads) > 1
            else get_media_kind(filenames[0] if filenames else "")
        )
        if expected_kind and kind != expected_kind:
            raise MediaProcessingError(
                f"This operation requires a {expected_kind} file."
            )

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        extensions = MEDIA_EXTENSIONS[kind]
        for upload in uploads:
            staged_path = await save_upload(
                upload,
                UPLOADS_DIR,
                extensions,
                max_bytes=MAX_FILE_BYTES,
            )
            staged_paths.append(staged_path)
            total_bytes += staged_path.stat().st_size
            if total_bytes > MAX_TOTAL_UPLOAD_BYTES:
                raise MediaProcessingError(
                    "The combined upload size cannot exceed 250 MB."
                )

        extension = ".mp3" if kind == "audio" else ".mp4"
        output_path = OUTPUTS_DIR / f"{uuid.uuid4().hex}{extension}"
        await asyncio.to_thread(operation, staged_paths, output_path)
        return FileResponse(
            output_path,
            media_type="audio/mpeg" if kind == "audio" else "video/mp4",
            filename=download_name(kind),
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            background=BackgroundTask(remove_file, output_path),
        )
    except (MediaProcessingError, ValueError) as exc:
        if output_path:
            remove_file(output_path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        for upload in uploads:
            await upload.close()
        for staged_path in staged_paths:
            remove_file(staged_path)
