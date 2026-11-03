"use strict";

const { copyFile, mkdir } = require("node:fs/promises");
const path = require("node:path");

const projectRoot = path.resolve(__dirname, "..");
const packageEntry = require.resolve("pdf-lib");
const packageRoot = path.resolve(path.dirname(packageEntry), "..");
const source = path.join(packageRoot, "dist", "pdf-lib.min.js");
const destinationDirectory = path.join(projectRoot, "static", "vendor");
const destination = path.join(destinationDirectory, "pdf-lib.min.js");

async function main() {
    await mkdir(destinationDirectory, { recursive: true });
    await copyFile(source, destination);
}

main().catch((error) => {
    console.error("Could not bundle the local pdf-lib browser build.", error);
    process.exitCode = 1;
});
