"""Image-to-PDF conversion and PDF merging business logic."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from services.image_service import MAX_IMAGE_PIXELS

MAX_PDF_PAGES = 2_000


class PdfProcessingError(ValueError):
    """Raised when an image or PDF cannot be processed safely."""


def images_to_pdf(image_paths: Sequence[Path], output_path: Path) -> Path:
    """Convert images to RGB pages in one PDF, preserving the input order."""
    if not image_paths:
        raise PdfProcessingError("Choose at least one JPG or PNG image.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        document = canvas.Canvas(str(output_path), pageCompression=1)
        for image_path in image_paths:
            with Image.open(image_path) as source:
                if source.format not in {"JPEG", "PNG"}:
                    raise PdfProcessingError(
                        "Only valid JPG, JPEG, and PNG images can be converted."
                    )
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise PdfProcessingError("An image is too large to convert safely.")
                image = ImageOps.exif_transpose(source).convert("RGB")
                width, height = image.size
                image_buffer = BytesIO()
                image.save(image_buffer, format="JPEG", quality=92, optimize=True)
                image_buffer.seek(0)
                document.setPageSize((width, height))
                document.drawImage(
                    ImageReader(image_buffer),
                    0,
                    0,
                    width=width,
                    height=height,
                    preserveAspectRatio=True,
                )
                document.showPage()
        document.save()
        return output_path
    except PdfProcessingError:
        output_path.unlink(missing_ok=True)
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        output_path.unlink(missing_ok=True)
        raise PdfProcessingError(
            "One or more images are corrupted or could not be converted."
        ) from exc


def merge_pdfs(pdf_paths: Sequence[Path], output_path: Path) -> Path:
    """Validate and merge PDF files in the order supplied."""
    if len(pdf_paths) < 2:
        raise PdfProcessingError("Choose at least two PDF files to merge.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    total_pages = 0
    try:
        for pdf_path in pdf_paths:
            reader = PdfReader(str(pdf_path), strict=True)
            if reader.is_encrypted:
                raise PdfProcessingError(
                    f"{pdf_path.name} is password-protected. Remove its "
                    "password and try again."
                )
            if not reader.pages:
                raise PdfProcessingError(f"{pdf_path.name} does not contain any pages.")
            total_pages += len(reader.pages)
            if total_pages > MAX_PDF_PAGES:
                raise PdfProcessingError(
                    f"The combined PDF cannot exceed {MAX_PDF_PAGES} pages."
                )
            writer.append(reader)

        with output_path.open("wb") as output:
            writer.write(output)
        return output_path
    except PdfProcessingError:
        output_path.unlink(missing_ok=True)
        raise
    except (PdfReadError, OSError, ValueError, KeyError, IndexError) as exc:
        output_path.unlink(missing_ok=True)
        raise PdfProcessingError(
            "One or more files are invalid or corrupted PDFs. Please check your files."
        ) from exc
    finally:
        writer.close()
