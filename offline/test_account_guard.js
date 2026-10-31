"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

let moduleValue;
let active = null;
const common = {
  setNativeCallback(callback, target, eventName) {
    active = {callback, target, eventName};
  }
};
const command = {
  getPlayerInfo() {
    setTimeout(() => active.callback({
      name: "マリオ",
      sex: "MALE",
      player_id: "",
      prologue_state: "OP0000"
    }), 0);
  }
};
const windowValue = {
  localSaveStatusPromise: Promise.resolve({hasSave: false})
};
vm.runInNewContext(
  fs.readFileSync(path.join(
    __dirname, "web_overrides/web/js/local/LocalAccountGuard.js"), "utf8"),
  {
    define(deps, factory) {
      assert.deepEqual(Array.from(deps), ["backboneCommon", "command"]);
      moduleValue = factory(common, command);
    },
    Promise,
    setTimeout,
    window: windowValue
  }
);
moduleValue.install();

async function playerInfo(status) {
  let received = null;
  windowValue.localSaveStatusPromise = Promise.resolve(status);
  common.setNativeCallback(payload => {
    received = payload;
    return payload;
  });
  command.getPlayerInfo();
  await new Promise(resolve => setTimeout(resolve, 5));
  return received;
}

(async () => {
  const existing = await playerInfo({
    hasSave: true,
    displayName: "ヨハン",
    sex: "MALE",
    playerId: "local-player"
  });
  assert.equal(existing.prologue_state, "OP0070");
  assert.equal(existing.name, "ヨハン");
  assert.equal(existing.player_id, "local-player");
  assert.equal(existing.localSaveValidated, true);

  const fresh = await playerInfo({hasSave: false});
  assert.equal(fresh.prologue_state, "OP0000");
  assert.equal(fresh.name, "マリオ");
  assert.equal(fresh.localSaveValidated, undefined);
  console.log("Account save guard: existing save resumes; fresh save keeps prologue: PASS");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
