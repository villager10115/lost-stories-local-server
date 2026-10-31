"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

function source(relative) {
  return fs.readFileSync(path.join(__dirname, relative), "utf8");
}

const page = source(
  "web_overrides/web/js/local/LocalKmfLifecyclePage.js"
);
assert.match(page, /\/api\/knightmareFrame\/development\/start/);
assert.match(page, /\/api\/knightmareFrame\/development\/skip/);
assert.match(page, /\/api\/knightmareFrame\/development\/receive/);
assert.match(page, /\/api\/knightmareFrame\/dismantle/);
assert.match(page, /\/api\/knightmareFrame\/carryIn/);
assert.match(page, /\/api\/knightmareFrame\/carryOut/);
assert.match(page, /payload\.deleted/);
assert.match(page, /userKnightmareFrameDevelopmentList/);
assert.match(page, /最大值|100機/);

for (const [relative, mode] of [
  ["web_overrides/web/js/kmf/KmfDevelopment.js", "development"],
  ["web_overrides/web/js/kmf/KmfDismantle.js", "dismantle"],
  ["web_overrides/web/js/carrying/CarryingTop.js", "carry"]
]) {
  const text = source(relative);
  assert.match(text, /js\/local\/LocalKmfLifecyclePage/);
  assert.match(text, new RegExp(mode));
}

console.log("Local KMF development/dismantle/storage contracts: PASS");
