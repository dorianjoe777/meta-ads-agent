import assert from "node:assert/strict";
import test from "node:test";

import handler from "../api/portal/cloud/access-keeper-ps.js";

test("Windows cloud access keeper runs invisibly and without interactive prompts", () => {
  let body = "";
  const response = {
    status(code) {
      assert.equal(code, 200);
      return this;
    },
    setHeader() {},
    send(value) { body = String(value); },
  };
  handler({}, response);
  assert.match(body, /-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass/);
  assert.match(body, /Admira IA Cloud Access Keeper/);
});
