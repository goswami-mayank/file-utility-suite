"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const projectRoot = path.resolve(__dirname, "..");
const readProjectFile = (relativePath) => readFileSync(
    path.join(projectRoot, relativePath),
    "utf8",
);

test("the workbench cannot submit selected files to a server form", () => {
    const home = readProjectFile("templates/home.html");
    const base = readProjectFile("templates/base.html");

    assert.doesNotMatch(home, /<form\b/i);
    assert.doesNotMatch(home, /action=["']\/(?:resize|jpg-to-pdf|merge-pdf)/i);
    assert.doesNotMatch(base, /upload-preview\.js/);
    assert.doesNotMatch(base, /<script[^>]+src=["']https?:\/\//i);
});

test("media processing is mounted as a same-origin API", () => {
    const app = readProjectFile("app.py");

    assert.match(app, /from routers\.media import router as media_router/);
    assert.match(app, /app\.include_router\(media_router, prefix="\/api"\)/);
});

test("the response policy allows same-origin API requests but blocks form submission", () => {
    const app = readProjectFile("app.py");

    assert.match(app, /connect-src 'self'/);
    assert.match(app, /form-action 'none'/);
});

test("every available catalog tool opens a matching tool panel", () => {
    const home = readProjectFile("templates/home.html");
    const toolIds = [...home.matchAll(/data-open-tool="([^"]+)"/g)]
        .map((match) => match[1])
        .sort();
    const panelIds = [...home.matchAll(/data-tool-panel="([^"]+)"/g)]
        .map((match) => match[1])
        .sort();

    assert.deepEqual(toolIds, panelIds);
});
