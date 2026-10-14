import test from "node:test";
import assert from "node:assert/strict";
import { comparisonPicker, comparisonResult } from "../app/static/comparison.js";

const escape = value => String(value).replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

test("version picker requires two snapshots and defaults to the latest pair", () => {
  assert.equal(comparisonPicker([{ number: 1 }]), "");
  const html = comparisonPicker([{ number: 3 }, { number: 2 }, { number: 1 }]);
  assert.match(html, /id="compare-from">.*value="2" selected/s);
  assert.match(html, /id="compare-to">.*value="3" selected/s);
});

test("comparison displays untrusted document markup as text", () => {
  const html = comparisonResult({ from_version: 1, to_version: 2, added: 1, removed: 1,
    changes: [{kind: "replace", before: ['<script>alert("old")</script>'],
      after: ['<img src=x onerror="alert(1)">']}],
  }, escape);
  assert.ok(!html.includes("<script>"));
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(html.includes("&lt;img"));
  assert.ok(html.includes("<del>"));
  assert.ok(html.includes("<ins>"));
});

test("unchanged content is collapsed and explicitly described", () => {
  const html = comparisonResult({ from_version: 1, to_version: 1, added: 0, removed: 0,
    changes: [{kind: "equal", before: ["Same content"], after: ["Same content"]}],
  }, escape);
  assert.ok(html.includes("No text changes"));
  assert.ok(html.includes("<details><summary>1 unchanged blocks</summary>"));
  assert.ok(!html.includes("<details open"));
});
