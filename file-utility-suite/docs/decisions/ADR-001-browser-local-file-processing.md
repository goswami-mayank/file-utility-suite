# ADR-001: Process files in the browser

## Status
Superseded for audio/video editing by [ADR-002](ADR-002-fastapi-media-processing.md); remains in effect for image, PDF, and data/text tools.

## Date
2026-10-01

## Context

The suite is expanding across images, PDFs/documents, audio/video, and data/text. Users require files to remain on their device. The original image and PDF forms sent file contents to FastAPI multipart endpoints, which does not satisfy that requirement.

## Decision

- Run image, PDF, media-inspection, and data/text operations in browser JavaScript.
- Do not mount file-upload processing routers in the FastAPI application.
- Block browser network APIs and form submissions with the Content Security Policy.
- Bundle `pdf-lib` locally for image-to-PDF and PDF merge rather than loading a CDN or uploading files to a server.
- Label media transcoding unavailable until a reliable browser-only implementation is available.

## Alternatives considered

- **Keep server-side processing:** rejected because files would leave the browser.
- **Load conversion libraries from a CDN:** rejected because the workbench should not need third-party network access.
- **Hide PDF tools:** rejected in favor of bundling a local PDF library and keeping the existing PDF workflows.
- **Claim universal media conversion:** rejected because codec and transcoding support varies by browser.

## Consequences

- Selected files are handled as browser `File` objects and generated output is offered through local object URLs.
- The PDF bundle is pinned to `pdf-lib` 1.17.1 and checked into the static assets; its source package is MIT licensed. See the [official PDFDocument API](https://pdf-lib.js.org/docs/api/classes/pdfdocument).
- Large files and unsupported codecs may still exceed browser memory or capability limits; the workbench enforces size/page limits and reports unsupported cases.
- Audio/video preview and metadata are browser-dependent; transcoding is explicitly unavailable.
