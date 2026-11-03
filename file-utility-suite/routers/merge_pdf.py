"""Routes for merging PDF documents."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from services.cleanup import remove_file, save_upload
from services.pdf_service import PdfProcessingError, merge_pdfs

router = APIRouter()
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
ALLOWED_EXTENSIONS = {".pdf"}
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_TOTAL_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_FILES = 20
DOWNLOAD_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
DOWNLOAD_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,119}\.pdf$",
    re.IGNORECASE,
)


@router.get("/merge-pdf", response_class=HTMLResponse, name="merge_pdf_page")
async def merge_pdf_page(request: Request) -> HTMLResponse:
    """Render the PDF merger form."""
    return templates.TemplateResponse(
        request=request,
        name="merge_pdf.html",
        context={"error": None},
    )


@router.post("/merge-pdf", response_class=HTMLResponse, name="merge_pdf_process")
async def merge_pdf_process(
    request: Request,
    files: list[UploadFile] = File(...),
) -> HTMLResponse:
    """Validate and merge PDFs in their submitted order."""
    if not files or all(not file.filename for file in files):
        return _error_page(request, "Choose at least two PDF files to merge.")
    if len(files) < 2:
        return _error_page(request, "Choose at least two PDF files to merge.")
    if len(files) > MAX_FILES:
        return _error_page(
            request,
            f"Upload no more than {MAX_FILES} PDF files at a time.",
        )

    staged_paths: list[Path] = []
    filenames: list[str] = []
    total_upload_bytes = 0
    output_path = OUTPUTS_DIR / f"{uuid.uuid4().hex}.pdf"
    download_name = "merged-document.pdf"
    try:
        for pdf_file in files:
            if not pdf_file.filename:
                raise ValueError("Each selected PDF must have a filename.")
            staged_path = await save_upload(
                pdf_file,
                UPLOADS_DIR,
                ALLOWED_EXTENSIONS,
                max_bytes=MAX_UPLOAD_BYTES,
            )
            staged_paths.append(staged_path)
            total_upload_bytes += staged_path.stat().st_size
            if total_upload_bytes > MAX_TOTAL_UPLOAD_BYTES:
                raise ValueError(
                    "The combined upload size cannot exceed 100 MB."
                )
            filenames.append(Path(pdf_file.filename).name)

        merge_pdfs(staged_paths, output_path)
        return templates.TemplateResponse(
            request=request,
            name="success.html",
            context={
                "title": "Your merged PDF is ready",
                "message": (
                    f"{len(staged_paths)} PDF files were merged in the order "
                    "you selected."
                ),
                "filenames": filenames,
                "download_url": f"/download/{output_path.stem}/{download_name}",
                "download_name": download_name,
            },
        )
    except (PdfProcessingError, OSError, ValueError) as exc:
        remove_file(output_path)
        logger.info("PDF merge failed: %s", exc)
        return _error_page(request, str(exc))
    except Exception:
        remove_file(output_path)
        logger.exception("Unexpected PDF merge failure")
        return _error_page(
            request,
            "The PDF files could not be merged. Please try again.",
            500,
        )
    finally:
        for path in staged_paths:
            remove_file(path)
        for pdf_file in files:
            await pdf_file.close()


@router.get("/download/{file_id}/{download_name}", name="download_file")
async def download_file(file_id: str, download_name: str) -> FileResponse:
    """Download an output file after validating its ID and displayed filename."""
    if not DOWNLOAD_ID_PATTERN.fullmatch(file_id):
        raise HTTPException(status_code=404, detail="The download could not be found.")
    if (
        not DOWNLOAD_NAME_PATTERN.fullmatch(download_name)
        or Path(download_name).name != download_name
    ):
        raise HTTPException(
            status_code=400,
            detail="The requested download name is invalid.",
        )

    path = OUTPUTS_DIR / f"{file_id}.pdf"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="This download has expired.")
    return FileResponse(path, media_type="application/pdf", filename=download_name)


def _error_page(request: Request, message: str, status_code: int = 400) -> HTMLResponse:
    """Render the shared error page."""
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"message": message, "status_code": status_code},
        status_code=status_code,
    )
