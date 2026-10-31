"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

let gate;
let popup;
let popupCalls = 0;
const listeners = [];
const common = {
  PopupClass: function (options) {
    popup = options;
    popupCalls++;
  }
};
class Element {}

vm.runInNewContext(
  fs.readFileSync(
    path.join(__dirname, "web_overrides/web/js/local/LocalUnavailableLinks.js"),
    "utf8"
  ),
  {
    define(deps, factory) {
      assert.equal(deps.length, 2);
      assert.equal(deps[0], "backboneCommon");
      assert.equal(deps[1], "command");
      gate = factory(common, {
        showQuestMovie() {},
        removeQuestMovie() {},
        releaseLive2d() {}
      });
    },
    window: {
      location: {hash: "#/MyPage"},
      setTimeout() {},
      addEventListener() {}
    },
    document: {
      addEventListener(type, listener, capture) {
        listeners.push({ type, listener, capture });
      }
    },
    Element
  }
);

assert.equal(gate.blockedFor("#/KmfDevelopment"), null);
assert.equal(gate.blockedFor("#/KmfDismantle"), null);
assert.equal(gate.blockedFor("#/CarryingTop/carryIn"), null);
assert.equal(
  gate.blockedFor("#/ChallengeQuestTop").label,
  "チャレンジクエスト"
);
assert.equal(gate.blockedFor("#/ComposePilot"), null);

gate.install();
gate.install();
assert.equal(listeners.length, 6);
assert.ok(listeners.every((item) => item.capture));
const pointerDown = listeners.find((item) => item.type === "pointerdown");
const pointerUp = listeners.find((item) => item.type === "pointerup");
assert.ok(pointerDown);
assert.ok(pointerUp);

function eventFor(href) {
  const target = new Element();
  target.closest = () => ({ getAttribute: () => href });
  let prevented = false;
  let stopped = false;
  return {
    target,
    preventDefault() { prevented = true; },
    stopImmediatePropagation() { stopped = true; },
    get prevented() { return prevented; },
    get stopped() { return stopped; }
  };
}

const blocked = eventFor("#/ChallengeQuestTop");
pointerDown.listener(blocked);
assert.ok(blocked.prevented);
assert.ok(blocked.stopped);
assert.equal(popup.canClose, true);
assert.match(popup.content, /チャレンジクエスト/);
pointerUp.listener(eventFor("#/ChallengeQuestTop"));
assert.equal(popupCalls, 1);

popup = null;
const allowed = eventFor("#/ComposePilot");
pointerDown.listener(allowed);
assert.equal(allowed.prevented, false);
assert.equal(popup, null);

console.log(
  "Local unavailable links: blocked routes show a closable notice: PASS"
);
