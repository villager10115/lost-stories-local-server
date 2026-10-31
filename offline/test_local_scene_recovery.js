"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "web_overrides/web/js/local/LocalSceneRecovery.js"
);

function element() {
  return {className: "", style: {}};
}

function createHarness() {
  let timerId = 0;
  const timers = new Map();
  const sent = [];
  const events = [];
  const elements = {
    loading: element(),
    tapBlock: element(),
    ready: element(),
    baseContainer: element(),
    mainContent: element()
  };
  const bridge = {
    postMessage(message) {
      sent.push(message);
    }
  };
  const window = {
    vuplex: bridge,
    dispatchEvent(event) {
      events.push(event);
    }
  };
  const context = {
    define(deps, factory) {
      assert.deepEqual(Array.from(deps), []);
      context.gate = factory();
    },
    window,
    document: {
      getElementById(id) {
        return elements[id] || null;
      }
    },
    CustomEvent: function (type, options) {
      this.type = type;
      this.detail = options.detail;
    },
    Date,
    JSON,
    String,
    encodeURIComponent,
    setTimeout(callback, delay) {
      timerId += 1;
      timers.set(timerId, {callback, delay, cancelled: false});
      return timerId;
    },
    clearTimeout(id) {
      const timer = timers.get(id);
      if (timer) timer.cancelled = true;
    },
    console
  };
  context.nativeCallback = function () {
    context.nativeCallbackCalls += 1;
  };
  context.nativeCallbackCalls = 0;

  vm.createContext(context);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), context, {
    filename: SOURCE
  });
  return {
    context,
    bridge,
    elements,
    sent,
    events,
    timers,
    runTimer(delay) {
      const entry = Array.from(timers.entries()).find(
        ([, timer]) => timer.delay === delay && !timer.cancelled
      );
      assert.ok(entry, `expected active ${delay}ms timer`);
      const [id, timer] = entry;
      timer.cancelled = true;
      timer.callback();
      return id;
    }
  };
}

const normal = createHarness();
normal.context.gate.install();
assert.equal(normal.context.gate.install(), normal.context.gate.state);
assert.equal(normal.context.gate.state.installed, true);
normal.bridge.postMessage({message: "zero://PUSH_HOME"});
assert.equal(normal.context.gate.state.pending, true);
vm.runInContext("nativeCallback()", normal.context);
assert.equal(normal.context.gate.state.pending, false);
assert.equal(normal.context.gate.state.recoveredCount, 0);
assert.equal(normal.context.nativeCallbackCalls, 1);

const stalled = createHarness();
stalled.context.gate.install();
stalled.bridge.postMessage({message: "zero://PUSH_HOME"});
assert.equal(stalled.context.gate.state.pending, true);
stalled.runTimer(5000);
assert.equal(stalled.context.gate.state.pending, false);
assert.equal(stalled.context.gate.state.recoveredCount, 1);
assert.equal(stalled.context.nativeCallbackCalls, 1);
assert.equal(stalled.context.gate.state.lastEvent.event, "push-home-timeout");

stalled.runTimer(2500);
const forcedCommands = stalled.sent.map((item) => item.message);
assert.ok(forcedCommands.includes("zero://SET_WEBVIEW_VISIBLE?commandParam=%7B%22isVisible%22%3Atrue%7D"));
assert.ok(forcedCommands.includes("zero://HIDE_LOADING"));
assert.equal(stalled.elements.loading.className, "hide");
assert.equal(stalled.elements.tapBlock.className, "");
assert.equal(stalled.elements.baseContainer.style.display, "block");
assert.equal(stalled.elements.mainContent.style.display, "block");

const duplicate = createHarness();
duplicate.context.gate.install();
duplicate.bridge.postMessage({message: "zero://PUSH_HOME"});
duplicate.bridge.postMessage({message: "zero://PUSH_HOME"});
assert.equal(duplicate.context.gate.state.duplicateCount, 1);
assert.equal(
  Array.from(duplicate.timers.values()).filter(
    (timer) => timer.delay === 5000 && !timer.cancelled
  ).length,
  1
);

console.log(
  "Local scene recovery: normal callbacks pass through; stalled PUSH_HOME resumes and exposes the WebView: PASS"
);
