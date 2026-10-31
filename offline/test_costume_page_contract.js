"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const webRoot = path.join(__dirname, "web_overrides", "web");
const js = fs.readFileSync(
  path.join(webRoot, "js", "costume", "CostumeTop.js"), "utf8");
const template = fs.readFileSync(
  path.join(webRoot, "template", "costume", "CostumeTop.html"), "utf8");
const css = fs.readFileSync(
  path.join(webRoot, "css", "costume", "CostumeTop.css"), "utf8");

for (const contract of [
  "userCostumeList",
  "userCharaList",
  "charaAddBookmarkCostume",
  "charaRemoveBookmarkCostume",
  "cardCostumeDressUp",
  "userCardId",
  "costumeId",
  "executeLive2d",
]) {
  assert.ok(js.includes(contract), `Missing original costume contract: ${contract}`);
}
assert.ok(!js.includes("LocalReadOnlyPage"));
for (const elementId of [
  "CostumeTop",
  "topView",
  "cardListView",
  "costumeListView",
  "bookmarkCostumeButton",
  "costumeSetDecide",
]) {
  assert.ok(template.includes(`id="${elementId}"`), `Missing element: ${elementId}`);
}
assert.ok(css.includes("width: 1920px"));
assert.ok(css.includes("height: 1080px"));
assert.ok(css.includes("#CostumeTop #topView .charaBtn"));
assert.ok(css.includes("#CostumeTop #costumeListView"));

const references = new Set();
for (const text of [template, css]) {
  for (const match of text.matchAll(/url\(["']?([^"')]+)|src=["']([^"']+)/g)) {
    const reference = match[1] || match[2];
    if (reference.startsWith("image/")) references.add(reference);
  }
}
assert.equal(references.size, 27);
for (const reference of references) {
  const file = path.join(webRoot, ...reference.split("/"));
  const body = fs.readFileSync(file);
  assert.equal(body.subarray(0, 4).toString("ascii"), "RIFF", reference);
  assert.equal(body.subarray(8, 12).toString("ascii"), "WEBP", reference);
}

console.log(`Costume page contract: PASS (${references.size} WebP assets)`);
