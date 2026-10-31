"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

let guard;
const appended = [];
const column = {
  querySelector() {
    return null;
  },
  appendChild(node) {
    appended.push(node);
  }
};
class MutationObserver {
  observe() {}
}
vm.runInNewContext(
  fs.readFileSync(
    path.join(__dirname, "web_overrides/web/js/local/LocalQuestResultGuard.js"),
    "utf8"
  ),
  {
    define(deps, factory) {
      assert.equal(deps.length, 1);
      assert.equal(deps[0], "backboneCommon");
      guard = factory({});
    },
    document: {
      documentElement: {},
      querySelectorAll(selector) {
        assert.equal(selector, ".charaCol");
        return [column];
      },
      createElement(tag) {
        assert.equal(tag, "div");
        return {className: "", style: {}};
      }
    },
    window: {addEventListener() {}},
    MutationObserver
  }
);

guard.install();
assert.equal(appended.length, 1);
assert.equal(appended[0].className, "trustGuageInner trust0");
assert.equal(appended[0].style.width, "0%");
assert.equal(appended[0].style.display, "none");
console.log("Quest result trust-zero guard: PASS");
