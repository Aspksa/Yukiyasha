"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.YukiDocuments = api;
})(typeof self !== "undefined" ? self : globalThis, function () {
  function extensionLabel(extension) {
    const ext = String(extension || "").trim().toUpperCase();
    return ext || "TXT";
  }

  function displayTitle(name) {
    const text = String(name || "Документ");
    return text.replace(/\.[^.]+$/, "") || text;
  }

  function formatSize(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value < 0) return "";
    if (value < 1024) return `${value} Б`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} КБ`;
    return `${(value / (1024 * 1024)).toFixed(1)} МБ`;
  }

  function previewText(text, max = 260) {
    const compact = String(text || "").replace(/\s+/g, " ").trim();
    if (!compact) return "";
    return compact.length > max ? `${compact.slice(0, max - 1).trimEnd()}…` : compact;
  }

  function normalize(document) {
    if (!document || typeof document !== "object" || !document.path || !document.name) return null;
    return {
      sectionId: String(document.section_id || ""),
      sectionTitle: String(document.section_title || "Документы"),
      name: String(document.name),
      title: displayTitle(document.name),
      path: String(document.path),
      extension: extensionLabel(document.extension),
      size: formatSize(document.size),
      preview: previewText(document.preview),
      truncated: Boolean(document.truncated),
    };
  }

  return { extensionLabel, displayTitle, formatSize, previewText, normalize };
});
