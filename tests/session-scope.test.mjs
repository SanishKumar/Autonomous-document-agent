import assert from "node:assert/strict";
import test from "node:test";
import { SessionScope } from "../app/static/session-scope.mjs";

test("current-session responses are accepted", () => {
  const scope = new SessionScope();
  assert.doesNotThrow(scope.capture());
});

test("late responses cannot cross a sign-out boundary", () => {
  const scope = new SessionScope();
  const checkOldSession = scope.capture();
  scope.reset();
  assert.throws(checkOldSession, { name: "StaleSessionError" });
  assert.doesNotThrow(scope.capture());
});

test("a second sign-in does not revive a previous response", () => {
  const scope = new SessionScope();
  const oldest = scope.capture();
  scope.reset();
  const middle = scope.capture();
  scope.reset();
  assert.throws(oldest, { name: "StaleSessionError" });
  assert.throws(middle, { name: "StaleSessionError" });
});
