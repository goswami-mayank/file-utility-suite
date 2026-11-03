"use strict";

/**
 * Show local image thumbnails and PDF page previews before form submission.
 * Files stay in the browser until the user presses the form's action button.
 */
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-file-preview]").forEach((input) => {
        const form = input.closest("form");
        const preview = form?.querySelector("[data-preview-list]");
        const submitButton = form?.querySelector('button[type="submit"]');

        if (!form || !preview || !submitButton) {
            return;
        }

        const allowedExtensions = new Set(
            (input.dataset.allowedExtensions || "")
                .split(",")
                .map((extension) => extension.trim().toLowerCase())
                .filter(Boolean),
        );
        const maxFiles = Number(input.dataset.maxFiles || 1);
        const minFiles = Number(input.dataset.minFiles || 1);
        const maxSizeBytes =
            Number(input.dataset.maxSizeMb || 0) * 1024 * 1024;
        const objectUrls = new Set();

        const releasePreviews = () => {
            objectUrls.forEach((url) => URL.revokeObjectURL(url));
            objectUrls.clear();
            preview.replaceChildren();
        };

        const createPreviewItem = (file, index) => {
            const item = document.createElement("article");
            item.className = "file-preview-item";
            const thumbnail = document.createElement("div");
            thumbnail.className = "file-preview-thumbnail";
            const fileUrl = URL.createObjectURL(file);
            objectUrls.add(fileUrl);

            if (file.type.startsWith("image/")) {
                const image = document.createElement("img");
                image.src = fileUrl;
                image.alt = `Preview of ${file.name}`;
                image.className = "file-preview-image";
                thumbnail.append(image);
            } else if (file.type === "application/pdf") {
                const documentPreview = document.createElement("iframe");
                documentPreview.src = `${fileUrl}#page=1&toolbar=0&navpanes=0`;
                documentPreview.title = `Preview of ${file.name}`;
                documentPreview.className = "file-preview-pdf";
                documentPreview.loading = "lazy";
                thumbnail.append(documentPreview);
            } else {
                const fileIcon = document.createElement("span");
                fileIcon.className = "file-preview-generic";
                fileIcon.setAttribute("aria-hidden", "true");
                fileIcon.textContent = "FILE";
                thumbnail.append(fileIcon);
            }

            const details = document.createElement("div");
            details.className = "file-preview-details";
            const fileName = document.createElement("strong");
            fileName.className = "file-preview-name";
            fileName.textContent = file.name;
            const fileSize = document.createElement("span");
            fileSize.className = "file-preview-size";
            fileSize.textContent = formatFileSize(file.size);
            details.append(fileName, fileSize);

            if (input.multiple) {
                const order = document.createElement("span");
                order.className = "file-preview-order";
                order.textContent = `File ${index + 1}`;
                details.append(order);
            }

            item.append(thumbnail, details);
            return item;
        };

        const updatePreviews = () => {
            releasePreviews();
            const files = Array.from(input.files || []);
            const issues = [];

            if (files.length > maxFiles) {
                issues.push(`Choose no more than ${maxFiles} files.`);
            }
            if (files.length > 0 && files.length < minFiles) {
                issues.push(
                    `Choose at least ${minFiles} files before continuing.`,
                );
            }
            files.forEach((file) => {
                const extension = `.${file.name.split(".").pop()}`.toLowerCase();
                if (!allowedExtensions.has(extension)) {
                    issues.push(`${file.name} is not a supported file type.`);
                } else if (maxSizeBytes && file.size > maxSizeBytes) {
                    issues.push(
                        `${file.name} is larger than the ${input.dataset.maxSizeMb} MB limit.`,
                    );
                }
            });

            if (files.length > 0) {
                const heading = document.createElement("div");
                heading.className = "selected-files-heading";
                const count = document.createElement("strong");
                count.textContent = `${files.length} file${files.length === 1 ? "" : "s"} selected`;
                heading.append(count);

                if (input.multiple) {
                    const order = document.createElement("span");
                    order.textContent = "Processing order";
                    heading.append(order);
                }
                preview.append(heading);

                const list = document.createElement("div");
                list.className = "file-preview-grid";
                files.forEach((file, index) => {
                    list.append(createPreviewItem(file, index));
                });
                preview.append(list);
            }

            if (issues.length > 0) {
                const notice = document.createElement("p");
                notice.className = "file-preview-error";
                notice.setAttribute("role", "alert");
                notice.textContent = issues.join(" ");
                preview.append(notice);
            }

            preview.hidden = files.length === 0 && issues.length === 0;
            submitButton.disabled = issues.length > 0;
            input.setCustomValidity(issues.join(" "));
        };

        input.addEventListener("change", updatePreviews);
        form.addEventListener("submit", () => {
            submitButton.classList.add("is-submitting");
            submitButton.disabled = true;
        });
        window.addEventListener("beforeunload", releasePreviews, { once: true });
    });
});

/**
 * Format a file size into a compact user-facing label.
 *
 * @param {number} bytes - File size in bytes.
 * @returns {string} Human-readable size.
 */
function formatFileSize(bytes) {
    if (bytes < 1024) {
        return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
