"""Audio and video validation and FFmpeg processing operations."""

from __future__ import annotations

import math
import subprocess
import uuid
from pathlib import Path
from typing import Sequence

import imageio_ffmpeg
import reportlab
from PIL import Image, ImageDraw, ImageFont

MEDIA_EXTENSIONS = {
    "audio": frozenset({".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav"}),
    "video": frozenset({".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}),
}
MAX_MEDIA_SECONDS = 30 * 60
MAX_MERGE_FILES = 10
MAX_CAPTION_LENGTH = 500
MAX_CROP_PIXELS = 40_000_000
FFMPEG_TIMEOUT_SECONDS = 10 * 60
CAPTION_FONT_PATH = Path(reportlab.__file__).resolve().parent / "fonts" / "Vera.ttf"


class MediaProcessingError(ValueError):
    """Raised when media input is unsupported or could not be processed."""


def get_media_kind(filename: str) -> str:
    """Classify supported media using its filename extension."""
    extension = Path(filename).suffix.lower()
    for kind, extensions in MEDIA_EXTENSIONS.items():
        if extension in extensions:
            return kind
    raise MediaProcessingError(
        "Unsupported media extension. Choose a supported audio or video file."
    )


def validate_time_range(start: float, end: float) -> float:
    """Validate a bounded time interval and return its duration in seconds."""
    if (
        not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end <= start
        or end - start > MAX_MEDIA_SECONDS
    ):
        raise MediaProcessingError(
            "Choose a valid time range no longer than 30 minutes."
        )
    return end - start


def validate_crop(x: int, y: int, width: int, height: int) -> None:
    """Validate crop geometry before building the FFmpeg filter."""
    if (
        any(type(value) is not int for value in (x, y, width, height))
        or x < 0
        or y < 0
        or width < 1
        or height < 1
        or width * height > MAX_CROP_PIXELS
    ):
        raise MediaProcessingError(
            "Crop values must be non-negative and the crop must be under 40 megapixels."
        )


def validate_caption(caption: str) -> str:
    """Normalize caption text and reject blank, oversized, or control input."""
    value = caption.strip()
    if (
        not value
        or len(value) > MAX_CAPTION_LENGTH
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
        or "\x7f" in value
    ):
        raise MediaProcessingError(
            "Enter caption text containing 1 to 500 printable characters."
        )
    return value


def validate_merge_inputs(filenames: Sequence[str]) -> str:
    """Require 2–10 supported files of the same media kind."""
    if not 2 <= len(filenames) <= MAX_MERGE_FILES:
        raise MediaProcessingError("Choose between 2 and 10 media files to merge.")
    kinds = {get_media_kind(filename) for filename in filenames}
    if len(kinds) != 1:
        raise MediaProcessingError("Merge audio files separately from video files.")
    return kinds.pop()


def trim_media(
    input_path: Path,
    output_path: Path,
    start: float,
    end: float,
) -> Path:
    """Trim an audio or video file and export a common, broadly supported format."""
    duration = validate_time_range(start, end)
    kind = get_media_kind(input_path.name)
    args = ["-ss", f"{start:.3f}", "-i", str(input_path), "-t", f"{duration:.3f}"]
    if kind == "audio":
        args.extend(["-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-q:a", "2"])
    else:
        args.extend(_video_encoding_args())
    _run_ffmpeg([*args, str(output_path)], cwd=input_path.parent)
    return output_path


def crop_video(
    input_path: Path,
    output_path: Path,
    x: int,
    y: int,
    width: int,
    height: int,
) -> Path:
    """Crop a video frame and export an MP4."""
    if get_media_kind(input_path.name) != "video":
        raise MediaProcessingError("Video cropping requires a video file.")
    validate_crop(x, y, width, height)
    args = [
        "-i", str(input_path),
        "-vf", f"crop={width}:{height}:{x}:{y}",
        *_video_encoding_args(),
        str(output_path),
    ]
    _run_ffmpeg(args, cwd=input_path.parent)
    return output_path


def add_caption(
    input_path: Path,
    output_path: Path,
    caption: str,
    start: float,
    end: float,
) -> Path:
    """Burn custom timed text into a video and export an MP4."""
    if get_media_kind(input_path.name) != "video":
        raise MediaProcessingError("Captions can only be added to video files.")
    validate_time_range(start, end)
    caption_text = validate_caption(caption)
    if not CAPTION_FONT_PATH.is_file():
        raise MediaProcessingError("The bundled caption font is unavailable.")
    suffix = uuid.uuid4().hex
    frame_path = input_path.with_name(f"caption-frame-{suffix}.png")
    overlay_path = input_path.with_name(f"caption-overlay-{suffix}.png")
    try:
        _run_ffmpeg(
            [
                "-i", str(input_path),
                "-map", "0:v:0",
                "-frames:v", "1",
                str(frame_path),
            ],
            cwd=input_path.parent,
        )
        with Image.open(frame_path) as frame:
            width, height = frame.size
        _render_caption_overlay(overlay_path, width, height, caption_text)
        caption_filter = (
            f"[0:v:0][1:v:0]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'"
            "[captioned]"
        )
        args = [
            "-i", str(input_path), "-i", str(overlay_path),
            "-filter_complex", caption_filter,
            "-map", "[captioned]", "-map", "0:a?",
            *_video_codec_args(),
            str(output_path),
        ]
        _run_ffmpeg(args, cwd=input_path.parent)
        return output_path
    except MediaProcessingError:
        raise
    except (OSError, ValueError) as exc:
        raise MediaProcessingError(
            "The caption overlay could not be created for this video."
        ) from exc
    finally:
        frame_path.unlink(missing_ok=True)
        overlay_path.unlink(missing_ok=True)


def _render_caption_overlay(
    output_path: Path,
    width: int,
    height: int,
    caption: str,
) -> None:
    """Render readable caption text into a transparent full-frame PNG."""
    margin = max(2, min(width, height) // 20)
    max_text_width = max(1, width - 2 * margin)
    max_text_height = max(8, int(height * 0.45))
    draw_image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(draw_image)

    for font_size in range(max(8, min(36, height // 6)), 5, -1):
        font = ImageFont.truetype(str(CAPTION_FONT_PATH), font_size)
        lines = _wrap_caption(caption, font, max_text_width)
        text = "\n".join(lines)
        spacing = max(2, font_size // 4)
        bounds = draw.multiline_textbbox(
            (0, 0),
            text,
            font=font,
            spacing=spacing,
            align="center",
        )
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        if text_width <= max_text_width and text_height <= max_text_height:
            break
    else:
        raise MediaProcessingError("The caption is too long to fit this video frame.")

    padding = max(2, font_size // 4)
    text_x = (width - text_width) // 2 - bounds[0]
    text_y = height - margin - text_height - bounds[1]
    draw.rounded_rectangle(
        (
            text_x + bounds[0] - padding,
            text_y + bounds[1] - padding,
            text_x + bounds[2] + padding,
            text_y + bounds[3] + padding,
        ),
        radius=padding,
        fill=(0, 0, 0, 166),
    )
    draw.multiline_text(
        (text_x, text_y),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        spacing=spacing,
        align="center",
    )
    draw_image.save(output_path, format="PNG", optimize=True)


def _wrap_caption(caption: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap caption text to fit the video frame, including long unbroken words."""
    lines: list[str] = []
    for paragraph in caption.splitlines() or [caption]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if font.getlength(candidate) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            for character in word:
                if line and font.getlength(line + character) > max_width:
                    lines.append(line)
                    line = character
                else:
                    line += character
        if line:
            lines.append(line)
    return lines or [""]


def merge_media(
    input_paths: Sequence[Path],
    output_path: Path,
) -> Path:
    """Concatenate compatible audio or video inputs in selection order."""
    kind = validate_merge_inputs([path.name for path in input_paths])
    manifest_path = input_paths[0].with_name(f"concat-{uuid.uuid4().hex}.txt")
    manifest_path.write_text(
        "".join(f"file '{path.name}'\n" for path in input_paths),
        encoding="utf-8",
    )
    args = ["-f", "concat", "-safe", "0", "-i", str(manifest_path)]
    if kind == "audio":
        args.extend(["-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-q:a", "2"])
    else:
        args.extend(_video_encoding_args())
    args.append(str(output_path))
    try:
        _run_ffmpeg(args, cwd=manifest_path.parent)
        return output_path
    finally:
        manifest_path.unlink(missing_ok=True)


def _video_encoding_args() -> list[str]:
    return [
        "-map", "0:v:0", "-map", "0:a?",
        *_video_codec_args(),
    ]


def _video_codec_args() -> list[str]:
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
    ]


def _run_ffmpeg(args: list[str], *, cwd: Path) -> None:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessingError(
            "Media processing exceeded the 10-minute limit."
        ) from exc
    except OSError as exc:
        raise MediaProcessingError(
            "The media processing engine could not be started."
        ) from exc
    if result.returncode != 0:
        raise MediaProcessingError(
            "The file could not be processed. Check that it is valid and uses a supported codec."
        )