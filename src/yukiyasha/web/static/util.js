"use strict";

/* Pure helpers for the Yukiyasha UI. No DOM access, so they run unchanged under `node --test`. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.YukiUtil = api;
})(typeof self !== "undefined" ? self : globalThis, function () {
  const SECTION_ROOTS = ["projects/work", "projects/home"];
  const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });

  /** Russian plural form: plural(2, "объект", "объекта", "объектов") -> "объекта". */
  function plural(n, one, few, many) {
    const m10 = n % 10;
    const m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) return few;
    return many;
  }

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} Б`;
    if (bytes < 1024 * 1024) return `${numberFormat.format(bytes / 1024)} КБ`;
    return `${numberFormat.format(bytes / (1024 * 1024))} МБ`;
  }

  function byteLength(text) {
    return new TextEncoder().encode(text).length;
  }

  function parentOf(path) {
    return path.split("/").slice(0, -1).join("/");
  }

  function baseName(path) {
    return path.split("/").pop() || path;
  }

  /** Join the current directory and a user-typed name; leading "./" and "/" are dropped. */
  function joinPath(dir, name) {
    const clean = name.trim().replace(/^(\.?\/)+/, "");
    return dir ? `${dir}/${clean}` : clean;
  }

  /** The sidebar section ("projects/work", "projects/home" or "" for the whole disk). */
  function sectionFor(path) {
    for (const key of SECTION_ROOTS) {
      if (path === key || path.startsWith(`${key}/`)) return key;
    }
    return "";
  }

  function routeToHash(route) {
    if (route.system) return "#system";
    if (route.file) return `#f=${encodeURIComponent(route.file)}`;
    return `#d=${encodeURIComponent(route.dir ?? "")}`;
  }

  function parseHash(hash) {
    const raw = hash.replace(/^#/, "");
    if (raw === "system") return { system: true };
    const params = new URLSearchParams(raw.replace(/\+/g, "%2B"));
    if (params.has("f")) return { file: params.get("f") };
    if (params.has("d")) return { dir: params.get("d") };
    return { dir: "projects/work" };
  }

  return {
    plural,
    formatSize,
    byteLength,
    parentOf,
    baseName,
    joinPath,
    sectionFor,
    routeToHash,
    parseHash,
  };
});
