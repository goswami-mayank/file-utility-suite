"""Image inspection and resizing business logic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_IMAGE_PIXELS = 40_000_000
MEDIA_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


class ImageProcessingError(ValueError):
    """Raised when an image cannot be safely inspected or processed."""


@dataclass(frozen=True)
class ImageInfo:
    """Validated metadata needed to display and process an image."""

    format: str
    width: int
    height: int
    filename: str
    media_type: str


def inspect_image(image_path: Path) -> ImageInfo:
    """Verify image contents and return metadata for a supported format."""
    try:
        with Image.open(image_path) as image:
            image_format = image.format
            image.verify()
        if image_format not in ALLOWED_FORMATS:
            raise ImageProcessingError(
                "The uploaded file is not a supported JPG, PNG, or WEBP image."
            )

        with Image.open(image_path) as image:
            oriented = ImageOps.exif_transpose(image)
            width, height = oriented.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise ImageProcessingError(
                    "The image dimensions are invalid or too large to process."
                )
        return ImageInfo(
            format=image_format,
            width=width,
            height=height,
            filename=image_path.name,
            media_type=MEDIA_TYPES[image_format],
        )
    except ImageProcessingError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ImageProcessingError(
            "The image is corrupted or could not be read. Please upload a valid image."
        ) from exc


def resize_image(
    input_path: Path,
    output_path: Path,
    width: int,
    height: int,
    *,
    maintain_aspect_ratio: bool = False,
) -> Path:
    """Resize an image, preserving transparency and the source image format."""
    if width < 1 or height < 1:
        raise ImageProcessingError("Width and height must be greater than zero.")
    if width > 10_000 or height > 10_000 or width * height > MAX_IMAGE_PIXELS:
        raise ImageProcessingError("The requested dimensions are too large.")

    info = inspect_image(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(input_path) as source:
            image = ImageOps.exif_transpose(source)
            has_transparency = "A" in image.getbands() or "transparency" in image.info
            if info.format == "PNG" and has_transparency:
                image = image.convert("RGBA")
            elif info.format == "JPEG":
                image = image.convert("RGB")
            elif info.format == "WEBP" and has_transparency:
                image = image.convert("RGBA")
            elif image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGB")

            resampling = getattr(Image, "Resampling", Image).LANCZOS
            if maintain_aspect_ratio:
                image.thumbnail((width, height), resampling)
                resized = image
            else:
                resized = image.resize((width, height), resampling)

            save_options: dict[str, object] = {}
            if info.format == "JPEG":
                save_options["quality"] = 92
                save_options["optimize"] = True
            elif info.format == "WEBP":
                save_options["quality"] = 92
                save_options["method"] = 6
            resized.save(output_path, format=info.format, **save_options)
        return output_path
    except ImageProcessingError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        output_path.unlink(missing_ok=True)
        raise ImageProcessingError(
            "The image could not be resized. Please upload a valid image and try again."
        ) from exc
