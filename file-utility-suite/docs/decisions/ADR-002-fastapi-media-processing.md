# ADR-002: Process audio and video with FastAPI

## Status
Accepted

## Date
2026-10-05

## Context

The workbench needs useful audio/video editing beyond browser preview and metadata. Browser codec and transcoding support varies, so the first release needs a consistent processing engine. The application is developed locally and is intended for later FastAPI Cloud deployment.

## Decision

- Keep image, PDF, and data/text processing in the browser.
- Identify supported audio/video kinds from an allow-listed filename extension.
- Upload audio/video only when an edit is submitted, using same-origin FastAPI endpoints backed by the pinned `imageio-ffmpeg` runtime.
- Provide trim, video crop, timed text burned into video, and compatible same-kind merges. Export audio as MP3 and video as MP4.
- Limit each file to 100 MB, merge uploads to 250 MB total, each selected time range to 30 minutes, and merge requests to 10 files.
- Store staged uploads in the existing temporary directory and delete them after processing. Delete generated outputs after the response completes; use periodic cleanup for files left by interrupted requests.
- Report unsupported extensions, invalid media, and incompatible stream layouts without promising universal codec support.

## Consequences

- The Content Security Policy permits same-origin API requests while continuing to block browser form submissions and external connections.
- Media processing consumes server CPU, memory, and temporary storage. Cloud hosting limits must support the configured upload and execution limits.
- The API currently has no authentication or distributed rate limiting. Those controls are required before public deployment.
- Browser-local tools remain usable without sending their files to FastAPI.
