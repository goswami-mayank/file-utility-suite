import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from services.media_service import (
    MediaProcessingError,
    add_caption,
    get_media_kind,
    validate_caption,
    validate_crop,
    validate_merge_inputs,
    validate_time_range,
)


class MediaValidationTests(unittest.TestCase):
    def test_media_kind_is_selected_from_extension(self):
        self.assertEqual(get_media_kind("clip.MP4"), "video")
        self.assertEqual(get_media_kind("voice.wav"), "audio")

    def test_unsupported_extension_is_rejected(self):
        with self.assertRaises(MediaProcessingError):
            get_media_kind("notes.txt")

    def test_time_range_returns_duration(self):
        self.assertEqual(validate_time_range(2, 7), 5)

    def test_time_range_rejects_invalid_values(self):
        for start, end in ((-1, 2), (2, 2), (float("nan"), 5), (0, 1801)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(MediaProcessingError):
                    validate_time_range(start, end)

    def test_crop_rejects_nonpositive_or_negative_geometry(self):
        for rectangle in ((0, 0, 0, 10), (-1, 0, 10, 10), (0, 0, 10, -1)):
            with self.subTest(rectangle=rectangle):
                with self.assertRaises(MediaProcessingError):
                    validate_crop(*rectangle)

    def test_caption_requires_short_nonblank_text(self):
        self.assertEqual(validate_caption("  Hello  "), "Hello")
        with self.assertRaises(MediaProcessingError):
            validate_caption(" \n ")
        with self.assertRaises(MediaProcessingError):
            validate_caption("x" * 501)

    def test_caption_uses_a_portable_overlay_filter(self):
        with TemporaryDirectory() as directory:
            input_path = Path(directory) / "sample.mp4"
            input_path.touch()
            output_path = Path(directory) / "captioned.mp4"

            def fake_ffmpeg(arguments, *, cwd):
                if arguments[-1].endswith(".png"):
                    Image.new("RGB", (64, 48)).save(arguments[-1])

            with patch(
                "services.media_service._run_ffmpeg",
                side_effect=fake_ffmpeg,
            ) as run_ffmpeg:
                add_caption(input_path, output_path, "Smoke test", 0, 1)

        commands = [call.args[0] for call in run_ffmpeg.call_args_list]
        arguments = commands[-1]
        filter_expression = arguments[arguments.index("-filter_complex") + 1]
        self.assertIn("overlay=", filter_expression)
        self.assertNotIn("drawtext", filter_expression)

    def test_merge_accepts_multiple_files_of_one_media_kind(self):
        self.assertEqual(
            validate_merge_inputs(["one.mp3", "two.wav"]),
            "audio",
        )
        self.assertEqual(
            validate_merge_inputs(["one.mp4", "two.mov"]),
            "video",
        )

    def test_merge_rejects_mixed_kinds_and_invalid_counts(self):
        for filenames in (("one.mp3",), ("one.mp3", "two.mp4"), ()):
            with self.subTest(filenames=filenames):
                with self.assertRaises(MediaProcessingError):
                    validate_merge_inputs(filenames)


if __name__ == "__main__":
    unittest.main()
