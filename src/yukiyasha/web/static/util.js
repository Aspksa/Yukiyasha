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

  const decimalFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

  /** "1 234,5" — numbers in lists and totals. */
  function formatNumber(value) {
    return decimalFormat.format(value);
  }

  /** "2026-10-05" -> "05.10.2026"; anything else is returned unchanged. */
  function formatDate(iso) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso));
    return match ? `${match[3]}.${match[2]}.${match[1]}` : String(iso);
  }

  /** "YYYY-MM" of a Date in local time. */
  function currentMonth(now = new Date()) {
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  }

  /** Move a "YYYY-MM" string by whole months; "2026-12" + 1 -> "2027-01". */
  function shiftMonth(month, delta) {
    const [year, number] = month.split("-").map(Number);
    const index = year * 12 + (number - 1) + delta;
    return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
  }

  /** Today as "YYYY-MM-DD" in local time (the value format of <input type="date">). */
  function todayIso(now = new Date()) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
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
    if (route.module) {
      const section = route.section ? `&s=${encodeURIComponent(route.section)}` : "";
      return `#m=${encodeURIComponent(route.module)}${section}`;
    }
    if (route.file) return `#f=${encodeURIComponent(route.file)}`;
    return `#d=${encodeURIComponent(route.dir ?? "")}`;
  }

  function parseHash(hash) {
    const raw = hash.replace(/^#/, "");
    if (raw === "system") return { system: true };
    const params = new URLSearchParams(raw.replace(/\+/g, "%2B"));
    if (params.has("m")) {
      const route = { module: params.get("m") };
      if (params.has("s")) route.section = params.get("s");
      return route;
    }
    if (params.has("f")) return { file: params.get("f") };
    if (params.has("d")) return { dir: params.get("d") };
    return { dir: "projects/work" };
  }

  /**
   * Which sidebar item is active for a directory. Everything inside the module's folder
   * belongs to the module; other paths follow their project section.
   */
  function navFor(path, moduleDirs) {
    for (const [moduleId, dir] of Object.entries(moduleDirs)) {
      if (path === dir || path.startsWith(`${dir}/`)) return `module:${moduleId}`;
    }
    return sectionFor(path);
  }

  return {
    navFor,
    plural,
    formatSize,
    formatNumber,
    formatDate,
    currentMonth,
    shiftMonth,
    todayIso,
    byteLength,
    parentOf,
    baseName,
    joinPath,
    sectionFor,
    routeToHash,
    parseHash,
  };
});
