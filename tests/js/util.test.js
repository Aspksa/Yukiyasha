"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const u = require("../../src/yukiyasha/web/static/util.js");

test("plural follows Russian rules", () => {
  const f = (n) => u.plural(n, "объект", "объекта", "объектов");
  assert.deepEqual(
    [0, 1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 101, 111, 112].map(f),
    [
      "объектов", "объект", "объекта", "объекта", "объектов", "объектов", "объектов",
      "объектов", "объект", "объекта", "объектов", "объект", "объектов", "объектов",
    ],
  );
});

test("formatSize uses binary units and Russian decimals", () => {
  assert.equal(u.formatSize(0), "0 Б");
  assert.equal(u.formatSize(1023), "1023 Б");
  assert.equal(u.formatSize(1024), "1 КБ");
  assert.equal(u.formatSize(1536), "1,5 КБ");
  assert.equal(u.formatSize(1048576), "1 МБ");
});

test("byteLength counts UTF-8 bytes, not characters", () => {
  assert.equal(u.byteLength("abc"), 3);
  assert.equal(u.byteLength("привет"), 12);
  assert.equal(u.byteLength("雪"), 3);
});

test("path helpers", () => {
  assert.equal(u.parentOf("a/b/c.txt"), "a/b");
  assert.equal(u.parentOf("c.txt"), "");
  assert.equal(u.baseName("a/b/c.txt"), "c.txt");
  assert.equal(u.joinPath("projects/work", "note.md"), "projects/work/note.md");
  assert.equal(u.joinPath("", "note.md"), "note.md");
  assert.equal(u.joinPath("d", "./x/y.txt"), "d/x/y.txt");
  assert.equal(u.joinPath("d", "/abs.txt"), "d/abs.txt");
  assert.equal(u.joinPath("d", "  spaced.txt  "), "d/spaced.txt");
});

test("sectionFor maps paths to sidebar sections", () => {
  assert.equal(u.sectionFor("projects/work"), "projects/work");
  assert.equal(u.sectionFor("projects/work/sub"), "projects/work");
  assert.equal(u.sectionFor("projects/home/x"), "projects/home");
  assert.equal(u.sectionFor("projects/workshop"), ""); // not a prefix match on names
  assert.equal(u.sectionFor("projects"), "");
  assert.equal(u.sectionFor(""), "");
});

test("hash routing round-trips, including unicode, spaces and plus signs", () => {
  const routes = [
    { dir: "projects/work" },
    { dir: "" },
    { file: "projects/home/заметки/идея 1.md" },
    { file: "projects/work/a+b.txt" },
    { system: true },
    { module: "primavtodor" },
    { module: "primavtodor", section: "waybills" },
    { ai: true },
    { ai: true, chat: "chat-1a2b3c4d" },
  ];
  for (const route of routes) {
    const parsed = u.parseHash(u.routeToHash(route));
    assert.deepEqual(parsed, route);
  }
});

test("parseHash falls back to the work section", () => {
  assert.deepEqual(u.parseHash(""), { dir: "projects/work" });
  assert.deepEqual(u.parseHash("#garbage"), { dir: "projects/work" });
});

test("navFor highlights a module for everything inside its folder", () => {
  const dirs = { primavtodor: "projects/work/Примавтодор" };
  assert.equal(u.navFor("projects/work/Примавтодор", dirs), "module:primavtodor");
  assert.equal(u.navFor("projects/work/Примавтодор/Табель", dirs), "module:primavtodor");
  assert.equal(u.navFor("projects/work/ПримавтодорX", dirs), "projects/work");
  assert.equal(u.navFor("projects/work", dirs), "projects/work");
  assert.equal(u.navFor("projects/home/a", dirs), "projects/home");
  assert.equal(u.navFor("", dirs), "");
});

test("formatDate and formatNumber", () => {
  assert.equal(u.formatDate("2026-10-05"), "05.10.2026");
  assert.equal(u.formatDate("not a date"), "not a date");
  assert.equal(u.formatNumber(1234.5).replace(/\s/g, " "), "1 234,5");
  assert.equal(u.formatNumber(0), "0");
  assert.equal(u.formatNumber(2.456), "2,46");
});

test("month helpers cross year boundaries", () => {
  assert.equal(u.shiftMonth("2026-10", 1), "2026-11");
  assert.equal(u.shiftMonth("2026-12", 1), "2027-01");
  assert.equal(u.shiftMonth("2026-01", -1), "2025-12");
  assert.equal(u.shiftMonth("2026-03", -15), "2024-12");
  assert.equal(u.currentMonth(new Date(2026, 0, 31)), "2026-01");
  assert.equal(u.todayIso(new Date(2026, 8, 5)), "2026-09-05");
});
