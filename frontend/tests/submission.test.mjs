import assert from "node:assert/strict";
import test from "node:test";
import { webcrypto } from "node:crypto";
import { createSubmissionId } from "../src/submission.js";

test("LAN HTTP generates a valid order ID without randomUUID", () => {
  const provider = { getRandomValues: bytes => bytes.fill(0) };
  assert.equal(provider.randomUUID, undefined);
  assert.equal(createSubmissionId(provider), "00000000000040008000000000000000");
});
test("IDs preserve full hex width and UUID bits", () => {
  assert.equal(createSubmissionId({ getRandomValues: bytes => bytes.fill(255) }), "ffffffffffff4fffbfffffffffffffff");
});
test("separate submissions receive distinct valid IDs", () => {
  const ids = Array.from({ length: 1000 }, () => createSubmissionId(webcrypto));
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ids) assert.match(id, /^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/);
});
test("missing or failed browser randomness raises a readable error", () => {
  assert.throws(() => createSubmissionId({}), /cannot generate an order ID/);
  assert.throws(() => createSubmissionId(null), /cannot generate an order ID/);
  assert.throws(() => createSubmissionId({ getRandomValues() { throw new Error("Browser random failure"); } }), /Browser random failure/);
});
