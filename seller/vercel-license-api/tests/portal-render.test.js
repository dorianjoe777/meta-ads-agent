import assert from "node:assert/strict";
import test from "node:test";

import portalHandler from "../api/portal.js";

test("portal renders usable SSH key commands for Windows CMD and Mac/Linux", async () => {
  let statusCode = 0;
  let html = "";
  const response = {
    setHeader() {},
    status(value) {
      statusCode = value;
      return this;
    },
    send(value) {
      html = String(value || "");
      return value;
    }
  };

  await portalHandler({ method: "GET" }, response);

  assert.equal(statusCode, 200);
  assert.ok(html.includes('mkdir -p "$HOME/.ssh"'));
  assert.ok(html.includes('if not exist "%USERPROFILE%\\.ssh" mkdir "%USERPROFILE%\\.ssh"'));
  assert.ok(html.includes('ssh-keygen -t ed25519 -C "admira-ia" -f "%USERPROFILE%\\.ssh\\admira_ia"'));
  assert.ok(html.includes('type "%USERPROFILE%\\.ssh\\admira_ia.pub"'));
  assert.ok(!html.includes('"%USERPROFILE%.ssh"'));
});
