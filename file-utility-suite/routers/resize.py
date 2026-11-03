"""Routes for image resizing."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from services.cleanup import remove_file, save_upload
from services.image_service import ImageProcessingError, inspect_image, resize_image

router = APIRouter()
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _error_page(
    request: Request,
    message: str,
    status_code: int = 400,
) -> HTMLResponse:
    """Build a consistent error response for this router."""
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"message": message, "status_code": status_code},
        status_code=status_code,
    )


def _validate_dimensions(width: int, height: int) -> str | None:
    """Return a message when requested dimensions are unsafe or invalid."""
    if width < 1 or height < 1:
        return "Width and height must be greater than zero."
    if width > 10_000 or height > 10_000 or width * height > 40_000_000:
        return "The requested dimensions are too large. Choose a smaller image size."
    return None


@router.get("/resize", response_class=HTMLResponse, name="resize_page")
async def resize_page(request: Request) -> HTMLResponse:
    """Render the image resizing form."""
    return templates.TemplateResponse(
        request=request,
        name="resize.html",
    )


@router.post("/resize/process", name="resize_process")
async def resize_process(
    request: Request,
    image: UploadFile = File(...),
    width: int = Form(...),
    height: int = Form(...),
    maintain_aspect_ratio: bool = Form(False),
) -> Response:
    """Resize an uploaded image and return it as a download."""
    dimension_error = _validate_dimensions(width, height)
    if dimension_error:
        return _error_page(request, dimension_error)

    input_path: Path | None = None
    output_path: Path | None = None
    try:
        input_path = await save_upload(
            image,
            UPLOADS_DIR,
            ALLOWED_EXTENSIONS,
            max_bytes=MAX_UPLOAD_BYTES,
        )
        info = inspect_image(input_path)
        if info.format not in FORMAT_EXTENSIONS:
            raise ImageProcessingError("The uploaded file is not a supported image.")

        extension = FORMAT_EXTENSIONS[info.format]
        output_path = OUTPUTS_DIR / f"{uuid.uuid4().hex}{extension}"
        resize_image(
            input_path,
            output_path,
            width,
            height,
            maintain_aspect_ratio=maintain_aspect_ratio,
        )
        safe_stem = (
            re.sub(
                r"[^A-Za-z0-9_-]+",
                "-",
                Path(image.filename or "resized-image").stem,
            ).strip("-_")
            or "resized-image"
        )
        return FileResponse(
            output_path,
            media_type=info.media_type,
            filename=f"{safe_stem}-resized{extension}",
        )
    except (ImageProcessingError, ValueError, OSError) as exc:
        if output_path is not None:
            remove_file(output_path)
        logger.info("Image resize failed: %s", exc)
        return _error_page(request, str(exc))
    finally:
        if input_path is not None:
            remove_file(input_path)
        await image.close()
