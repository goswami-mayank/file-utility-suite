"use strict";

function formatJson(source, compact = false) {
    const value = JSON.parse(source);
    return JSON.stringify(value, null, compact ? 0 : 2);
}

function csvToJson(source) {
    const text = source.replace(/^\uFEFF/, "");
    const rows = [];
    let row = [];
    let field = "";
    let quoted = false;
    let afterQuote = false;

    for (let index = 0; index < text.length; index += 1) {
        const character = text[index];

        if (quoted) {
            if (character === '"') {
                if (text[index + 1] === '"') {
                    field += '"';
                    index += 1;
                } else {
                    quoted = false;
                    afterQuote = true;
                }
            } else {
                field += character;
            }
            continue;
        }

        if (afterQuote) {
            if (character === ",") {
                row.push(field);
                field = "";
                afterQuote = false;
            } else if (character === "\n" || character === "\r") {
                row.push(field);
                if (row.some((value) => value.length > 0)) {
                    rows.push(row);
                }
                row = [];
                field = "";
                afterQuote = false;
                if (character === "\r" && text[index + 1] === "\n") {
                    index += 1;
                }
            } else if (character !== " " && character !== "\t") {
                throw new Error("Unexpected character after a quote in CSV.");
            }
            continue;
        }

        if (character === '"' && field.length === 0) {
            quoted = true;
        } else if (character === ",") {
            row.push(field);
            field = "";
        } else if (character === "\n" || character === "\r") {
            row.push(field);
            if (row.some((value) => value.length > 0)) {
                rows.push(row);
            }
            row = [];
            field = "";
            if (character === "\r" && text[index + 1] === "\n") {
                index += 1;
            }
        } else if (character === '"') {
            throw new Error("A quote must begin a CSV field.");
        } else {
            field += character;
        }
    }

    if (quoted) {
        throw new Error("A quoted CSV field was not closed.");
    }
    if (field.length > 0 || row.length > 0) {
        row.push(field);
        rows.push(row);
    }
    if (rows.length === 0) {
        throw new Error("The CSV file is empty.");
    }

    const headers = rows[0].map((header) => header.trim());
    if (headers.some((header) => header.length === 0)) {
        throw new Error("CSV column names cannot be empty.");
    }
    if (new Set(headers).size !== headers.length) {
        throw new Error("CSV column names must be unique.");
    }

    return rows.slice(1).map((values, rowIndex) => {
        if (values.length !== headers.length) {
            throw new Error(
                `CSV row ${rowIndex + 2} must have the same number of columns as the header.`,
            );
        }
        return Object.fromEntries(
            headers.map((header, index) => [header, values[index]]),
        );
    });
}

function transformText(text, mode = "title") {
    if (mode === "upper") {
        return text.toUpperCase();
    }
    if (mode === "lower") {
        return text.toLowerCase();
    }
    if (mode === "title") {
        return text
            .toLowerCase()
            .replace(/(^|[\s\p{P}])(\p{L})/gu, (_, boundary, letter) => (
                `${boundary}${letter.toUpperCase()}`
            ));
    }
    throw new Error("Unsupported text case transformation.");
}

function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) {
        throw new RangeError("File size must be a non-negative number.");
    }
    if (bytes < 1024) {
        return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function waitForMediaMetadata(mediaElement, signal) {
    if (signal.aborted) {
        const error = new Error("Media metadata inspection was cancelled.");
        error.name = "AbortError";
        return Promise.reject(error);
    }
    if (mediaElement.readyState >= 1) {
        return Promise.resolve();
    }

    return new Promise((resolve, reject) => {
        function cleanup() {
            mediaElement.removeEventListener("loadedmetadata", onLoadedMetadata);
            mediaElement.removeEventListener("error", onError);
            signal.removeEventListener("abort", onAbort);
        }
        function onLoadedMetadata() {
            cleanup();
            resolve();
        }
        function onError() {
            cleanup();
            reject(new Error("This browser could not read metadata for the selected codec."));
        }
        function onAbort() {
            cleanup();
            const error = new Error("Media metadata inspection was cancelled.");
            error.name = "AbortError";
            reject(error);
        }

        mediaElement.addEventListener("loadedmetadata", onLoadedMetadata, { once: true });
        mediaElement.addEventListener("error", onError, { once: true });
        signal.addEventListener("abort", onAbort, { once: true });
        if (signal.aborted) {
            onAbort();
        }
    });
}

function mediaKindFromFilename(filename) {
    const extension = `.${String(filename).split(".").pop().toLowerCase()}`;
    if ([".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav"].includes(extension)) {
        return "audio";
    }
    if ([".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"].includes(extension)) {
        return "video";
    }
    return "";
}

function resizeDimensions(width, height, sourceWidth, sourceHeight, keepAspectRatio) {
    if (
        !Number.isInteger(width)
        || !Number.isInteger(height)
        || width < 1
        || height < 1
        || width > 10_000
        || height > 10_000
        || width * height > 40_000_000
    ) {
        throw new RangeError("Choose valid dimensions no larger than 10,000 pixels or 40 megapixels.");
    }
    if (
        !Number.isInteger(sourceWidth)
        || !Number.isInteger(sourceHeight)
        || sourceWidth < 1
        || sourceHeight < 1
        || sourceWidth * sourceHeight > 40_000_000
    ) {
        throw new RangeError("The image dimensions are invalid or too large to process.");
    }
    if (!keepAspectRatio) {
        return { width, height };
    }

    const scale = Math.min(width / sourceWidth, height / sourceHeight, 1);
    return {
        width: Math.max(1, Math.round(sourceWidth * scale)),
        height: Math.max(1, Math.round(sourceHeight * scale)),
    };
}

async function mergePdfFiles(PDFDocument, files) {
    if (files.length < 2) {
        throw new Error("Choose at least two PDF files to merge.");
    }
    if (files.length > 20) {
        throw new Error("Choose no more than 20 PDF files at a time.");
    }

    const merged = await PDFDocument.create();
    let totalPages = 0;
    for (const file of files) {
        if (!file.name.toLowerCase().endsWith(".pdf")) {
            throw new Error(`${file.name} is not a PDF file.`);
        }
        const source = await PDFDocument.load(await file.arrayBuffer());
        const pageCount = source.getPageCount();
        if (pageCount < 1) {
            throw new Error(`${file.name} does not contain any pages.`);
        }
        totalPages += pageCount;
        if (totalPages > 2_000) {
            throw new Error("The merged PDF cannot exceed 2,000 pages.");
        }
        const pages = await merged.copyPages(
            source,
            source.getPageIndices(),
        );
        pages.forEach((page) => merged.addPage(page));
    }
    return merged.save();
}

async function imagesToPdf(PDFDocument, files) {
    if (files.length < 1) {
        throw new Error("Choose at least one JPG or PNG image.");
    }
    if (files.length > 30) {
        throw new Error("Choose no more than 30 images at a time.");
    }

    const document = await PDFDocument.create();
    for (const file of files) {
        const extension = file.name.split(".").pop().toLowerCase();
        let image;
        if (file.type === "image/jpeg" || extension === "jpg" || extension === "jpeg") {
            image = await document.embedJpg(await file.arrayBuffer());
        } else if (file.type === "image/png" || extension === "png") {
            image = await document.embedPng(await file.arrayBuffer());
        } else {
            throw new Error(`${file.name} is not a supported JPG or PNG image.`);
        }

        const page = document.addPage([image.width, image.height]);
        page.drawImage(image, {
            x: 0,
            y: 0,
            width: image.width,
            height: image.height,
        });
    }
    return document.save();
}

function encodeBase64(text) {
    const bytes = new TextEncoder().encode(text);
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
    }
    return btoa(binary);
}

function decodeBase64(encoded) {
    const binary = atob(encoded.replace(/\s/g, ""));
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        csvToJson,
        decodeBase64,
        encodeBase64,
        formatBytes,
        formatJson,
        imagesToPdf,
        mediaKindFromFilename,
        mergePdfFiles,
        resizeDimensions,
        transformText,
        waitForMediaMetadata,
    };
}

if (typeof window !== "undefined") {
    window.FileToolboxCore = {
        csvToJson,
        decodeBase64,
        encodeBase64,
        formatBytes,
        formatJson,
        imagesToPdf,
        mediaKindFromFilename,
        mergePdfFiles,
        resizeDimensions,
        transformText,
        waitForMediaMetadata,
    };
}
