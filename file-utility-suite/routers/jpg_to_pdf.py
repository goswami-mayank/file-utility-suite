"""Routes for converting image uploads into a single PDF."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.cleanup import remove_file, save_upload
from services.pdf_service import PdfProcessingError, images_to_pdf

router = APIRouter()
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_TOTAL_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_FILES = 30


def _safe_pdf_name(value: str) -> str:
    """Normalize a user-provided download name to a safe PDF filename."""
    stem = Path(value).name.rsplit(".", 1)[0]
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")
    return f"{(safe_stem or 'converted-images')[:80]}.pdf"


@router.get("/jpg-to-pdf", response_class=HTMLResponse, name="jpg_to_pdf_page")
async def jpg_to_pdf_page(request: Request) -> HTMLResponse:
    """Render the image-to-PDF converter form."""
    return templates.TemplateResponse(
        request=request,
        name="jpg_to_pdf.html",
        context={"error": None},
    )


@router.post("/jpg-to-pdf", response_class=HTMLResponse, name="jpg_to_pdf_convert")
async def jpg_to_pdf_convert(
    request: Request,
    images: list[UploadFile] = File(...),
    output_filename: str = Form("converted-images"),
) -> HTMLResponse:
    """Convert submitted images in upload order and show a download link."""
    if not images or all(not image.filename for image in images):
        return _error_page(request, "Choose at least one JPG or PNG image.")
    if len(images) > MAX_FILES:
        return _error_page(
            request,
            f"Upload no more than {MAX_FILES} images at a time.",
        )

    staged_paths: list[Path] = []
    filenames: list[str] = []
    total_upload_bytes = 0
    output_path = OUTPUTS_DIR / f"{uuid.uuid4().hex}.pdf"
    try:
        for image in images:
            if not image.filename:
                raise ValueError("Each selected image must have a filename.")
            staged_path = await save_upload(
                image,
                UPLOADS_DIR,
                ALLOWED_EXTENSIONS,
                max_bytes=MAX_UPLOAD_BYTES,
            )
            staged_paths.append(staged_path)
            total_upload_bytes += staged_path.stat().st_size
            if total_upload_bytes > MAX_TOTAL_UPLOAD_BYTES:
                raise ValueError("The combined upload size cannot exceed 100 MB.")
            filenames.append(Path(image.filename).name)

        images_to_pdf(staged_paths, output_path)
        download_name = _safe_pdf_name(output_filename)
        file_id = output_path.stem
        return _success_page(
            request,
            title="Your PDF is ready",
            message=(
                f"{len(staged_paths)} image(s) were converted in the order "
                "you selected."
            ),
            filenames=filenames,
            download_url=f"/download/{file_id}/{download_name}",
            download_name=download_name,
        )
    except (PdfProcessingError, OSError, ValueError) as exc:
        remove_file(output_path)
        logger.info("Image-to-PDF conversion failed: %s", exc)
        return _error_page(request, str(exc))
    except Exception:
        remove_file(output_path)
        logger.exception("Unexpected image-to-PDF conversion failure")
        return _error_page(
            request,
            "The images could not be converted. Please try again.",
            500,
        )
    finally:
        for path in staged_paths:
            remove_file(path)
        for image in images:
            await image.close()


def _success_page(
    request: Request,
    *,
    title: str,
    message: str,
    filenames: list[str],
    download_url: str,
    download_name: str,
) -> HTMLResponse:
    """Render the shared conversion success page."""
    return templates.TemplateResponse(
        request=request,
        name="success.html",
        context={
            "title": title,
            "message": message,
            "filenames": filenames,
            "download_url": download_url,
            "download_name": download_name,
        },
    )


def _error_page(request: Request, message: str, status_code: int = 400) -> HTMLResponse:
    """Render the shared error page."""
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"message": message, "status_code": status_code},
        status_code=status_code,
    )
