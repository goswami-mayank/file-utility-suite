"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { PDFDocument } = require("pdf-lib");
const {
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
} = require("../static/toolbox-core.js");

function asFile(name, type, bytes) {
    return {
        name,
        type,
        size: bytes.byteLength,
        arrayBuffer: async () => bytes.buffer.slice(
            bytes.byteOffset,
            bytes.byteOffset + bytes.byteLength,
        ),
    };
}

async function createPdf(pageWidths) {
    const document = await PDFDocument.create();
    for (const width of pageWidths) {
        document.addPage([width, 100]);
    }
    return document.save();
}

test("formats valid JSON with readable indentation", () => {
    assert.equal(formatJson('{"name":"Ada","active":true}'), '{\n  "name": "Ada",\n  "active": true\n}');
});

test("minifies valid JSON when compact output is requested", () => {
    assert.equal(formatJson('{\n  "answer": 42\n}', true), '{"answer":42}');
});

test("rejects invalid JSON instead of returning the input unchanged", () => {
    assert.throws(() => formatJson('{"broken":}'), SyntaxError);
});

test("converts CSV with quoted commas and escaped quotes", () => {
    assert.deepEqual(
        csvToJson('name,note\r\nAda,"said ""hello, world"""'),
        [{ name: "Ada", note: 'said "hello, world"' }],
    );
});

test("converts CSV with line breaks inside quoted values", () => {
    assert.deepEqual(
        csvToJson('name,note\nAda,"line one\nline two"'),
        [{ name: "Ada", note: "line one\nline two" }],
    );
});

test("rejects duplicate headers and inconsistent CSV rows", () => {
    assert.throws(() => csvToJson("name,name\nAda,Lovelace"), /unique/i);
    assert.throws(() => csvToJson("name,age\nAda"), /same number of columns/i);
    assert.throws(() => csvToJson('name,note\nAda,"quoted"tail'), /after a quote/i);
});

test("transforms text case without altering whitespace boundaries", () => {
    assert.equal(transformText("  hello, WORLD!  ", "upper"), "  HELLO, WORLD!  ");
    assert.equal(transformText("  hello, WORLD!  ", "lower"), "  hello, world!  ");
    assert.equal(transformText("hello, brave world"), "Hello, Brave World");
});

test("rejects unknown text transformation modes", () => {
    assert.throws(() => transformText("hello", "unsupported"), /unsupported/i);
});

test("formats byte sizes at B, KB, and MB boundaries", () => {
    assert.equal(formatBytes(0), "0 B");
    assert.equal(formatBytes(1024), "1.0 KB");
    assert.equal(formatBytes(1_572_864), "1.5 MB");
});

test("resizes within a box while preserving aspect ratio and avoiding enlargement", () => {
    assert.deepEqual(resizeDimensions(800, 600, 1600, 900, true), {
        width: 800,
        height: 450,
    });
    assert.deepEqual(resizeDimensions(1600, 1200, 800, 600, true), {
        width: 800,
        height: 600,
    });
});

test("rejects invalid image dimensions before canvas allocation", () => {
    assert.throws(() => resizeDimensions(0, 600, 800, 600, false), /valid dimensions/i);
    assert.throws(() => resizeDimensions(800, 600, 0, 600, true), /image dimensions/i);
    assert.throws(() => resizeDimensions(10_000, 10_000, 800, 600, false), /40 megapixels/i);
});

test("encodes and decodes UTF-8 text using Base64", () => {
    const encoded = encodeBase64("नमस्ते, file tools");

    assert.equal(decodeBase64(encoded), "नमस्ते, file tools");
});

test("rejects invalid UTF-8 Base64 instead of returning corrupted text", () => {
    assert.throws(() => decodeBase64("/w=="), /encoded data/i);
});

test("cancels a pending media metadata read when the selection changes", async () => {
    const mediaElement = new EventTarget();
    mediaElement.readyState = 0;
    const controller = new AbortController();
    const pendingRead = waitForMediaMetadata(mediaElement, controller.signal);

    controller.abort();

    await assert.rejects(pendingRead, { name: "AbortError" });
});

test("identifies audio and video from the selected filename extension", () => {
    assert.equal(mediaKindFromFilename("clip.MP4"), "video");
    assert.equal(mediaKindFromFilename("voice.WAV"), "audio");
    assert.equal(mediaKindFromFilename("notes.txt"), "");
});

test("merges local PDF files in their selected order", async () => {
    const first = await createPdf([100]);
    const second = await createPdf([200, 300]);
    const mergedBytes = await mergePdfFiles(PDFDocument, [
        asFile("first.pdf", "application/pdf", first),
        asFile("second.pdf", "application/pdf", second),
    ]);
    const merged = await PDFDocument.load(mergedBytes);

    assert.deepEqual(
        merged.getPages().map((page) => page.getWidth()),
        [100, 200, 300],
    );
});

test("requires at least two PDF files to merge", async () => {
    await assert.rejects(() => mergePdfFiles(PDFDocument, []), /at least two/i);
});

test("rejects non-PDF files before attempting to merge them", async () => {
    const file = asFile("notes.txt", "text/plain", Buffer.from("not a PDF"));
    await assert.rejects(
        () => mergePdfFiles(PDFDocument, [file, file]),
        /not a PDF/i,
    );
});

test("converts a local PNG image into a one-page PDF", async () => {
    const png = Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/S48AAAAASUVORK5CYII=",
        "base64",
    );
    const pdfBytes = await imagesToPdf(PDFDocument, [
        asFile("pixel.png", "image/png", png),
    ]);
    const pdf = await PDFDocument.load(pdfBytes);

    assert.equal(pdf.getPageCount(), 1);
});
