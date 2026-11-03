"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const dialog = document.querySelector("#tool-dialog");
    if (!dialog) {
        return;
    }

    const core = window.FileToolboxCore;
    const title = document.querySelector("#dialog-title");
    const status = document.querySelector("#tool-status");
    const result = document.querySelector("#tool-result");
    const output = document.querySelector("#tool-output");
    const copyButton = document.querySelector("#copy-result");
    const downloadLink = document.querySelector("#download-result");
    let activePanel = null;
    let mediaUrl = null;
    let downloadUrl = null;
    let mediaInspectionController = null;
    let mediaProcessingController = null;

    function setStatus(message, state = "") {
        status.textContent = message;
        status.dataset.state = state;
    }

    function clearDownload() {
        if (downloadUrl) {
            URL.revokeObjectURL(downloadUrl);
            downloadUrl = null;
        }
        downloadLink.removeAttribute("href");
        downloadLink.hidden = true;
    }

    function clearResult() {
        clearDownload();
        result.hidden = true;
        output.hidden = false;
        output.value = "";
        copyButton.hidden = false;
    }

    function showTextResult(text, filename = "file-tool-result.txt") {
        clearDownload();
        output.value = text;
        output.hidden = false;
        copyButton.hidden = false;
        result.hidden = false;
        downloadUrl = URL.createObjectURL(
            new Blob([text], { type: "text/plain;charset=utf-8" }),
        );
        downloadLink.href = downloadUrl;
        downloadLink.download = filename;
        downloadLink.textContent = "Download result";
        downloadLink.hidden = false;
        setStatus("Done. Your result was created in this browser.", "success");
    }

    function showFileResult(blob, filename, message) {
        clearDownload();
        output.hidden = true;
        copyButton.hidden = true;
        result.hidden = false;
        downloadUrl = URL.createObjectURL(blob);
        downloadLink.href = downloadUrl;
        downloadLink.download = filename;
        downloadLink.textContent = `Download ${filename}`;
        downloadLink.hidden = false;
        setStatus(message, "success");
    }

    async function runTool(button, operation, workingMessage = "Working locally in your browser…") {
        button.disabled = true;
        setStatus(workingMessage);
        clearResult();
        try {
            await operation();
        } catch (error) {
            const cancelled = error instanceof Error && error.name === "AbortError";
            if (dialog.open && !cancelled) {
                const message = error instanceof Error
                    ? error.message
                    : "The tool could not process this input.";
                setStatus(message, "error");
            }
        } finally {
            button.disabled = false;
        }
    }

    function requireText(input, label) {
        const value = input.value;
        if (value.length === 0) {
            throw new Error(`Enter ${label} to continue.`);
        }
        if (value.length > 1_000_000) {
            throw new Error("Text input cannot exceed 1 million characters.");
        }
        return value;
    }

    function selectFiles(input, {
        extensions,
        minFiles = 1,
        maxFiles = 1,
        maxEachBytes,
        maxTotalBytes,
    }) {
        const files = Array.from(input.files || []);
        if (files.length < minFiles) {
            throw new Error(`Choose at least ${minFiles} file(s) to continue.`);
        }
        if (files.length > maxFiles) {
            throw new Error(`Choose no more than ${maxFiles} files.`);
        }

        let totalBytes = 0;
        for (const file of files) {
            const extension = `.${file.name.split(".").pop().toLowerCase()}`;
            if (!extensions.has(extension)) {
                throw new Error(`${file.name} is not a supported file type.`);
            }
            if (file.size === 0) {
                throw new Error(`${file.name} is empty.`);
            }
            if (maxEachBytes && file.size > maxEachBytes) {
                throw new Error(`${file.name} is larger than the per-file limit.`);
            }
            totalBytes += file.size;
        }
        if (maxTotalBytes && totalBytes > maxTotalBytes) {
            throw new Error("The selected files exceed the combined size limit.");
        }
        return files;
    }

    function safeFilename(value, fallback, extension) {
        const stem = value
            .replace(/^.*[\\/]/, "")
            .replace(/\.[^.]+$/, "")
            .replace(/[^A-Za-z0-9_-]+/g, "-")
            .replace(/^[-_]+|[-_]+$/g, "")
            .slice(0, 80);
        return `${stem || fallback}.${extension}`;
    }

    function releaseMedia() {
        mediaInspectionController?.abort();
        mediaInspectionController = null;
        mediaProcessingController?.abort();
        mediaProcessingController = null;
        if (mediaUrl) {
            URL.revokeObjectURL(mediaUrl);
            mediaUrl = null;
        }
        for (const selector of ["#audio-preview", "#video-preview"]) {
            const player = document.querySelector(selector);
            player.pause();
            player.removeAttribute("src");
            player.load();
            player.hidden = true;
        }
    }

    async function processMedia(endpoint, formData, filename, successMessage) {
        const controller = new AbortController();
        mediaProcessingController = controller;
        try {
            const response = await fetch(`/api/media/${endpoint}`, {
                method: "POST",
                body: formData,
                credentials: "same-origin",
                signal: controller.signal,
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => null);
                throw new Error(
                    payload?.error?.message || "The media service could not process this file.",
                );
            }
            const blob = await response.blob();
            if (blob.size === 0) {
                throw new Error("The media service returned an empty file.");
            }
            showFileResult(blob, filename, successMessage);
        } finally {
            if (mediaProcessingController === controller) {
                mediaProcessingController = null;
            }
        }
    }

    function mediaFiles(input, { minFiles = 1, maxFiles = 1, maxTotalBytes } = {}) {
        return selectFiles(input, {
            extensions: new Set([
                ".aac", ".avi", ".flac", ".m4a", ".m4v", ".mkv", ".mov",
                ".mp3", ".mp4", ".mpeg", ".mpg", ".oga", ".ogg", ".opus",
                ".wav", ".webm",
            ]),
            minFiles,
            maxFiles,
            maxEachBytes: 100 * 1024 * 1024,
            maxTotalBytes,
        });
    }

    function appendMediaFile(formData, fieldName, file) {
        const kind = core.mediaKindFromFilename(file.name);
        if (!kind) {
            throw new Error(`${file.name} has an unsupported media extension.`);
        }
        formData.append(fieldName, file, file.name);
        return kind;
    }

    function requireNumber(selector, label, integer = false) {
        const input = document.querySelector(selector);
        const value = input.valueAsNumber;
        if (!input.value || !Number.isFinite(value) || (integer && !Number.isInteger(value))) {
            throw new Error(`Enter a valid ${label}.`);
        }
        return String(value);
    }

    function pdfDocumentApi() {
        if (!window.PDFLib?.PDFDocument) {
            throw new Error("The local PDF library could not be loaded. Refresh and try again.");
        }
        return window.PDFLib.PDFDocument;
    }

    document.querySelectorAll("[data-category-filter]").forEach((button) => {
        button.addEventListener("click", () => {
            document.querySelectorAll("[data-category-filter]").forEach((filter) => {
                filter.setAttribute("aria-pressed", String(filter === button));
            });
            updateCatalog();
        });
    });
    document.querySelector("#tool-search").addEventListener("input", updateCatalog);

    function updateCatalog() {
        const query = document.querySelector("#tool-search").value.trim().toLowerCase();
        const filter = document.querySelector(
            '[data-category-filter][aria-pressed="true"]',
        ).dataset.categoryFilter;
        let visibleCount = 0;

        document.querySelectorAll("[data-tool-card]").forEach((card) => {
            const categories = card.dataset.category.split(" ");
            const matchesCategory = filter === "all" || categories.includes(filter);
            const matchesSearch = !query
                || `${card.dataset.search} ${card.textContent}`.toLowerCase().includes(query);
            const visible = matchesCategory && matchesSearch;
            card.hidden = !visible;
            visibleCount += Number(visible);
        });
        document.querySelector("#empty-tools").hidden = visibleCount > 0;
    }

    document.querySelectorAll("[data-open-tool]").forEach((button) => {
        button.addEventListener("click", () => {
            clearResult();
            releaseMedia();
            setStatus("");
            activePanel = Array.from(
                document.querySelectorAll("[data-tool-panel]"),
            ).find((panel) => panel.dataset.toolPanel === button.dataset.openTool);
            document.querySelectorAll("[data-tool-panel]").forEach((panel) => {
                panel.hidden = panel !== activePanel;
            });
            title.textContent = button.closest(".tool-card").querySelector("h3").textContent;
            dialog.showModal();
            activePanel.querySelector("input, textarea, select, button")?.focus();
        });
    });

    document.querySelector("#dialog-close").addEventListener("click", () => {
        dialog.close();
    });
    dialog.addEventListener("close", () => {
        releaseMedia();
        clearResult();
        dialog.querySelectorAll('input[type="file"]').forEach((input) => {
            input.value = "";
        });
        dialog.querySelectorAll("textarea:not([readonly])").forEach((input) => {
            input.value = "";
        });
        setStatus("");
        activePanel = null;
    });

    document.querySelectorAll("[data-json-action]").forEach((button) => {
        button.addEventListener("click", () => runTool(button, () => {
            const source = requireText(document.querySelector("#json-input"), "JSON");
            const compact = button.dataset.jsonAction === "compact";
            const value = core.formatJson(source, compact);
            showTextResult(value, compact ? "formatted.min.json" : "formatted.json");
        }));
    });

    document.querySelector("#csv-convert").addEventListener("click", (event) => {
        runTool(event.currentTarget, () => {
            const source = requireText(document.querySelector("#csv-input"), "CSV data");
            const value = JSON.stringify(core.csvToJson(source), null, 2);
            showTextResult(value, "converted.json");
        });
    });

    document.querySelector("#case-convert").addEventListener("click", (event) => {
        runTool(event.currentTarget, () => {
            const source = requireText(document.querySelector("#case-input"), "text");
            const mode = document.querySelector("#case-mode").value;
            showTextResult(core.transformText(source, mode), "transformed.txt");
        });
    });

    document.querySelector("#base64-run").addEventListener("click", (event) => {
        runTool(event.currentTarget, () => {
            const source = requireText(document.querySelector("#base64-input"), "text");
            const mode = document.querySelector("#base64-mode").value;
            const value = mode === "encode"
                ? core.encodeBase64(source)
                : core.decodeBase64(source);
            showTextResult(value, mode === "encode" ? "encoded.txt" : "decoded.txt");
        });
    });

    const qualityInput = document.querySelector("#image-quality");
    qualityInput.addEventListener("input", () => {
        document.querySelector("#quality-value").textContent = `${qualityInput.value}%`;
    });
    document.querySelector("#image-resize").addEventListener("click", (event) => {
        runTool(event.currentTarget, async () => {
            const [file] = selectFiles(document.querySelector("#image-file"), {
                extensions: new Set([".jpg", ".jpeg", ".png", ".webp"]),
                maxEachBytes: 20 * 1024 * 1024,
            });
            const image = new Image();
            const imageUrl = URL.createObjectURL(file);
            try {
                image.src = imageUrl;
                await image.decode();
                const dimensions = core.resizeDimensions(
                    Number(document.querySelector("#image-width").value),
                    Number(document.querySelector("#image-height").value),
                    image.naturalWidth,
                    image.naturalHeight,
                    document.querySelector("#image-aspect").checked,
                );
                const { width, height } = dimensions;

                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;
                const context = canvas.getContext("2d");
                if (!context) {
                    throw new Error("Image processing is unavailable in this browser.");
                }
                const mimeType = document.querySelector("#image-format").value;
                if (mimeType === "image/jpeg") {
                    context.fillStyle = "#ffffff";
                    context.fillRect(0, 0, width, height);
                }
                context.drawImage(image, 0, 0, width, height);
                const quality = Number(qualityInput.value) / 100;
                const blob = await new Promise((resolve, reject) => {
                    canvas.toBlob(
                        (value) => value
                            ? resolve(value)
                            : reject(new Error("The browser could not encode this image format.")),
                        mimeType,
                        quality,
                    );
                });
                const extensionByMime = {
                    "image/jpeg": "jpg",
                    "image/png": "png",
                    "image/webp": "webp",
                };
                const actualMime = blob.type || mimeType;
                const extension = extensionByMime[actualMime];
                if (!extension) {
                    throw new Error("The browser returned an unsupported image format.");
                }
                const filename = safeFilename(file.name, "resized-image", extension);
                showFileResult(
                    blob,
                    filename,
                    actualMime === mimeType
                        ? "Resized locally. Your image has not been uploaded."
                        : `This browser exported ${extension.toUpperCase()} instead of the requested format.`,
                );
            } finally {
                URL.revokeObjectURL(imageUrl);
            }
        });
    });

    document.querySelector("#images-to-pdf").addEventListener("click", (event) => {
        runTool(event.currentTarget, async () => {
            const files = selectFiles(document.querySelector("#images-pdf-files"), {
                extensions: new Set([".jpg", ".jpeg", ".png"]),
                maxFiles: 30,
                maxEachBytes: 20 * 1024 * 1024,
                maxTotalBytes: 100 * 1024 * 1024,
            });
            const bytes = await core.imagesToPdf(pdfDocumentApi(), files);
            const filename = safeFilename(
                document.querySelector("#images-pdf-name").value,
                "converted-images",
                "pdf",
            );
            showFileResult(
                new Blob([bytes], { type: "application/pdf" }),
                filename,
                `${files.length} image(s) converted in selection order. Files stayed in this browser.`,
            );
        });
    });

    document.querySelector("#pdf-merge").addEventListener("click", (event) => {
        runTool(event.currentTarget, async () => {
            const files = selectFiles(document.querySelector("#pdf-files"), {
                extensions: new Set([".pdf"]),
                minFiles: 2,
                maxFiles: 20,
                maxEachBytes: 30 * 1024 * 1024,
                maxTotalBytes: 100 * 1024 * 1024,
            });
            const bytes = await core.mergePdfFiles(pdfDocumentApi(), files);
            showFileResult(
                new Blob([bytes], { type: "application/pdf" }),
                "merged-document.pdf",
                `${files.length} PDF files merged in selection order. Files stayed in this browser.`,
            );
        });
    });

    const mediaInput = document.querySelector("#media-file");
    mediaInput.addEventListener("change", () => {
        releaseMedia();
        clearResult();
        setStatus("");
        const file = mediaInput.files?.[0];
        if (!file) {
            return;
        }
        if (file.size === 0 || file.size > 1024 * 1024 * 1024) {
            setStatus("Choose a non-empty media file no larger than 1 GB.", "error");
            return;
        }
        const kind = core.mediaKindFromFilename(file.name);
        if (!kind) {
            setStatus("Choose an audio or video file supported by your browser.", "error");
            return;
        }
        mediaUrl = URL.createObjectURL(file);
        const player = document.querySelector(
            kind === "audio" ? "#audio-preview" : "#video-preview",
        );
        player.src = mediaUrl;
        player.hidden = false;
        setStatus("Identified by extension. Preview codec support varies.");
    });

    document.querySelector("#media-inspect").addEventListener("click", (event) => {
        runTool(event.currentTarget, async () => {
            const controller = new AbortController();
            mediaInspectionController = controller;
            try {
                const file = mediaInput.files?.[0];
                if (!file || !mediaUrl) {
                    throw new Error("Choose a supported audio or video file first.");
                }
                const player = core.mediaKindFromFilename(file.name) === "video"
                    ? document.querySelector("#video-preview")
                    : document.querySelector("#audio-preview");
                await core.waitForMediaMetadata(player, controller.signal);
                if (mediaInput.files?.[0] !== file || !mediaUrl) {
                    const error = new Error("The media selection changed during inspection.");
                    error.name = "AbortError";
                    throw error;
                }
                if (!Number.isFinite(player.duration)) {
                    throw new Error("This browser could not read metadata for the selected codec.");
                }
                const metadata = {
                    name: file.name,
                    mediaType: core.mediaKindFromFilename(file.name),
                    size: core.formatBytes(file.size),
                    durationSeconds: Number(player.duration.toFixed(2)),
                };
                if (player instanceof HTMLVideoElement) {
                    metadata.width = player.videoWidth;
                    metadata.height = player.videoHeight;
                }
                showTextResult(JSON.stringify(metadata, null, 2), "media-metadata.json");
            } finally {
                if (mediaInspectionController === controller) {
                    mediaInspectionController = null;
                }
            }
        });
    });

    document.querySelector("#media-trim").addEventListener("click", (event) => {
        runTool(event.currentTarget, async () => {
            const [file] = mediaFiles(document.querySelector("#media-trim-file"));
            const formData = new FormData();
            const kind = appendMediaFile(formData, "file", file);
            formData.append("start", requireNumber("#trim-start", "start time"));
            formData.append("end", requireNumber("#trim-end", "end time"));
            await processMedia(
                "trim",
                formData,
                `trimmed-${kind}.${kind === "audio" ? "mp3" : "mp4"}`,
                "Trimmed by the FastAPI media service. The uploaded source was removed after processing.",
            );
        }, "Uploading media to FastAPI for trimming…");
    });

    document.querySelector("#video-crop").addEventListener("click", (event) => {
        runTool(event.currentTarget, async () => {
            const [file] = selectFiles(document.querySelector("#video-crop-file"), {
                extensions: new Set([".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"]),
                maxEachBytes: 100 * 1024 * 1024,
            });
            const formData = new FormData();
            appendMediaFile(formData, "file", file);
            for (const field of ["x", "y", "width", "height"]) {
                formData.append(field, requireNumber(`#crop-${field}`, field, true));
            }
            await processMedia(
                "crop",
                formData,
                "cropped-video.mp4",
                "Cropped by the FastAPI media service. The uploaded source was removed after processing.",
            );
        }, "Uploading video to FastAPI for cropping…");
    });

    document.querySelector("#video-caption").addEventListener("click", (event) => {
        runTool(event.currentTarget, async () => {
            const [file] = selectFiles(document.querySelector("#caption-video-file"), {
                extensions: new Set([".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"]),
                maxEachBytes: 100 * 1024 * 1024,
            });
            const formData = new FormData();
            appendMediaFile(formData, "file", file);
            formData.append("caption", requireText(document.querySelector("#caption-text"), "caption text"));
            formData.append("start", requireNumber("#caption-start", "caption start time"));
            formData.append("end", requireNumber("#caption-end", "caption end time"));
            await processMedia(
                "caption",
                formData,
                "captioned-video.mp4",
                "Caption added by the FastAPI media service. The uploaded source was removed after processing.",
            );
        }, "Uploading video to FastAPI for captioning…");
    });

    document.querySelector("#media-merge").addEventListener("click", (event) => {
        runTool(event.currentTarget, async () => {
            const files = mediaFiles(document.querySelector("#media-merge-files"), {
                minFiles: 2,
                maxFiles: 10,
                maxTotalBytes: 2 * 1024 * 1024 * 1024,
            });
            const formData = new FormData();
            const kinds = new Set(files.map((file) => appendMediaFile(formData, "files", file)));
            if (kinds.size !== 1) {
                throw new Error("Merge audio files separately from video files.");
            }
            const [kind] = kinds;
            await processMedia(
                "merge",
                formData,
                `merged-${kind}.${kind === "audio" ? "mp3" : "mp4"}`,
                `Merged ${files.length} ${kind} files. The uploaded sources were removed after processing.`,
            );
        }, "Uploading media to FastAPI for merging…");
    });

    copyButton.addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(output.value);
            setStatus("Copied to clipboard. No file was uploaded.", "success");
        } catch {
            setStatus(
                "Clipboard access was denied. Select the result text to copy it.",
                "error",
            );
        }
    });
});
