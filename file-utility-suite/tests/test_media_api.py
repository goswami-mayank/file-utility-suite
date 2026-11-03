import math
import os
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import imageio_ffmpeg
from fastapi.testclient import TestClient

from app import app


class MediaApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_path = Path(cls.temp_dir.name)
        cls.audio_path = cls.temp_path / "tone.wav"
        cls.video_path = cls.temp_path / "sample.mp4"
        cls._create_audio(cls.audio_path)
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=64x48:r=5:d=1",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(cls.video_path),
            ],
            check=True,
            capture_output=True,
        )
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    @staticmethod
    def _create_audio(path):
        sample_rate = 8_000
        sample_count = sample_rate
        frames = b"".join(
            struct.pack("<h", int(10_000 * math.sin(2 * math.pi * 440 * index / sample_rate)))
            for index in range(sample_count)
        )
        with wave.open(os.fspath(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(frames)

    def _post_video(self, endpoint, data):
        with self.video_path.open("rb") as video:
            return self.client.post(
                endpoint,
                files={"file": ("sample.mp4", video, "video/mp4")},
                data=data,
            )

    def test_trims_audio_and_returns_an_mp3_download(self):
        with self.audio_path.open("rb") as audio:
            response = self.client.post(
                "/api/media/trim",
                files={"file": ("tone.wav", audio, "audio/wav")},
                data={"start": "0", "end": "0.5"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "audio/mpeg")
        self.assertIn("trimmed-audio.mp3", response.headers["content-disposition"])
        self.assertGreater(len(response.content), 100)

    def test_crops_video_and_returns_an_mp4_download(self):
        response = self._post_video(
            "/api/media/crop",
            {"x": "0", "y": "0", "width": "32", "height": "24"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "video/mp4")
        self.assertIn(b"ftyp", response.content[:32])

    def test_burns_custom_caption_into_video(self):
        response = self._post_video(
            "/api/media/caption",
            {"caption": "Hello: 'media', [world]", "start": "0", "end": "1"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(b"ftyp", response.content[:32])

    def test_merges_compatible_video_files_in_order(self):
        with self.video_path.open("rb") as first, self.video_path.open("rb") as second:
            response = self.client.post(
                "/api/media/merge",
                files=[
                    ("files", ("first.mp4", first, "video/mp4")),
                    ("files", ("second.mp4", second, "video/mp4")),
                ],
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("merged-video.mp4", response.headers["content-disposition"])
        self.assertIn(b"ftyp", response.content[:32])

    def test_rejects_mixed_audio_and_video_merge(self):
        with self.audio_path.open("rb") as audio, self.video_path.open("rb") as video:
            response = self.client.post(
                "/api/media/merge",
                files=[
                    ("files", ("tone.wav", audio, "audio/wav")),
                    ("files", ("sample.mp4", video, "video/mp4")),
                ],
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Merge audio files separately", response.json()["error"]["message"])


if __name__ == "__main__":
    unittest.main()
