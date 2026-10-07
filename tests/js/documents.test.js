"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const d = require("../../src/yukiyasha/web/static/documents.js");

test("document helper creates clean card metadata", () => {
  assert.deepEqual(
    d.normalize({
      section_id: "memos",
      section_title: "Служебные записки",
      name: "Служебная записка №12.txt",
      path: "projects/work/Примавтодор/Служебные записки/Служебная записка №12.txt",
      size: 1536,
      extension: "txt",
      preview: "  Первая   строка\nВторая строка  ",
    }),
    {
      sectionId: "memos",
      sectionTitle: "Служебные записки",
      name: "Служебная записка №12.txt",
      title: "Служебная записка №12",
      path: "projects/work/Примавтодор/Служебные записки/Служебная записка №12.txt",
      extension: "TXT",
      size: "1.5 КБ",
      preview: "Первая строка Вторая строка",
      truncated: false,
    },
  );
});

test("document helper never needs to show a raw path as title", () => {
  assert.equal(d.displayTitle("Приказ 18.md"), "Приказ 18");
  assert.equal(d.extensionLabel("pdf"), "PDF");
  assert.equal(d.previewText("x".repeat(400)).endsWith("…"), true);
  assert.equal(d.normalize({ name: "x.txt" }), null);
});
