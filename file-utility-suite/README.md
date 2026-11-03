# File Utility Suite

A workbench for everyday image, PDF, media, and data/text tasks. Image, PDF, and data/text processing happens in the browser. Audio/video editing uploads selected files to the same-origin FastAPI service for FFmpeg processing.

## Available tools

| Category | Tool | Support |
|---|---|---|
| Images | Resize JPG, PNG, or WEBP; export PNG, JPEG, or WEBP | Browser canvas |
| PDF & documents | Combine JPG/PNG images into a PDF | Local `pdf-lib` bundle |
| PDF & documents | Merge PDFs in selection order | Local `pdf-lib` bundle |
| Audio & video | Preview media and read supported metadata | Browser codec support varies |
| Audio & video | Identify supported media by filename extension | Browser and FastAPI validation |
| Audio & video | Trim audio/video; crop video; add timed text captions | FastAPI with bundled FFmpeg; audio exports as MP3, video as MP4 |
| Audio & video | Merge 2–10 audio files or 2–10 video files | FastAPI with FFmpeg; input codecs/streams must be compatible |
| Data & text | Format/minify JSON, convert CSV to JSON, change text case, encode/decode UTF-8 Base64 | Browser JavaScript |

Media editing accepts AAC, FLAC, M4A, MP3, OGA, OGG, OPUS, WAV, AVI, M4V, MKV, MOV, MP4, MPEG, MPG, and WEBM filename extensions. Each upload is limited to 100 MB, merge requests to 250 MB total, and media operations to 30 minutes of selected content. FFmpeg must also be able to decode the file. Merge requires compatible source stream layouts and codecs.

Password-protected PDFs are not supported. Size and page-count limits are shown in the relevant tools. Media source files are removed after processing; generated downloads are removed after the response completes. Stale temporary files are cleaned on startup and hourly.

## Run locally

Install the Python requirements, then start the FastAPI app from this directory:

```powershell
python -m pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`. The app serves the workbench and static assets plus same-origin FastAPI media endpoints. Its Content Security Policy permits same-origin API requests and blocks form submissions.

The media runtime is installed from the pinned `imageio-ffmpeg` package in `requirements.txt`; the PDF browser bundle works without Node at runtime. To regenerate it after changing the pinned `pdf-lib` dependency:

```powershell
npm ci --ignore-scripts
npm run vendor:pdf
```

## Tests

```powershell
npm test
python -m unittest discover -s tests -p "test_media*.py"
```

The tests cover browser-local tools, media extension identification, upload/API validation, and real FFmpeg trim/crop/caption/merge operations using generated sample files.

## Cloud deployment

Install `requirements.txt` in the FastAPI deployment so the platform-specific FFmpeg binary is included. Verify the cloud request-body, execution-time, and temporary-disk limits against the media limits above. The media API currently has no authentication or distributed rate limiting; add those controls before exposing it publicly to prevent anonymous users from consuming processing capacity.
