"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const p = require("../../src/yukiyasha/web/static/proposals.js");

test("proposal diff shows only changed fields for update", () => {
  const diff = p.buildProposalDiff({
    operation: "update",
    before: { plate: "А123АА25", model: "УАЗ", active: true },
    payload: { plate: "А123АА25", model: "ГАЗ", active: true },
  });
  assert.deepEqual(diff, [
    { field: "model", before: "УАЗ", after: "ГАЗ", change: "update" },
  ]);
});

test("proposal diff represents create and delete", () => {
  assert.deepEqual(
    p.buildProposalDiff({ operation: "create", payload: { model: "УАЗ" } }),
    [{ field: "model", before: null, after: "УАЗ", change: "add" }],
  );
  assert.deepEqual(
    p.buildProposalDiff({ operation: "delete", before: { model: "УАЗ" } }),
    [{ field: "model", before: "УАЗ", after: null, change: "remove" }],
  );
});

test("proposal labels and values are readable", () => {
  assert.equal(p.fieldLabel("plate"), "Госномер");
  assert.equal(p.fieldLabel("custom_field"), "custom field");
  assert.equal(p.statusLabel("pending"), "Ожидает подтверждения");
  assert.equal(p.operationLabel("delete"), "Удаление");
  assert.equal(p.kindLabel("vehicles"), "Машины");
  assert.equal(p.formatValue(true), "Да");
  assert.equal(p.formatValue(null), "—");
});
