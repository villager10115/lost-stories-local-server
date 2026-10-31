"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

let perkModule;
let quantity = 1;
let originalCalls = 0;
let observedTotal = null;
let observedGray = null;
let observedPointKind = null;
let observedQuantity = null;

const common = {
  storage: {
    userItemList: {
      findWhere(filter) {
        assert.equal(filter.itemId, "LOCAL_UNLIMITED_TEN_PULL");
        return {get(key) {
          assert.equal(key, "quantity");
          return quantity;
        }, toJSON() { return {quantity}; }};
      }
    }
  }
};
const GachaBtnView = function () {};
GachaBtnView.prototype.gachaPopup = function () {
  originalCalls++;
  observedTotal = this.rootView.money + this.rootView.freeMoney;
  observedGray = this.gray;
  observedPointKind = this.model.gachaKindList[0].needPointKind;
  observedQuantity = this.model.gachaKindList[0].needQuantity;
};

vm.runInNewContext(
  fs.readFileSync(
    path.join(__dirname, "web_overrides/web/js/local/LocalGachaPerk.js"),
    "utf8"
  ),
  {
    define(deps, factory) {
      assert.equal(deps.length, 2);
      assert.equal(deps[0], "backboneCommon");
      assert.equal(deps[1], "js/view/gacha/GachaBtnView");
      perkModule = factory(common, GachaBtnView);
    }
  }
);

perkModule.install();
const view = new GachaBtnView();
view.rootView = {money: 0, freeMoney: 0};
view.model = {gachaKindList: [{
  gachaKindId: 1008,
  beanKind: "RARE10",
  needPointKind: "MONEY",
  needQuantity: 1500
}]};
const target = {
  dataset: {gachaNum: 1008},
  classList: {
    contains(name) { return name === "grayBtn"; },
    remove(name) { if (name === "grayBtn") view.gray = false; },
    add(name) { if (name === "grayBtn") view.gray = true; }
  }
};
view.gray = true;
view.gachaPopup({currentTarget: target});
assert.equal(originalCalls, 1);
assert.equal(observedTotal, 0);
assert.equal(observedPointKind, "FREE");
assert.equal(observedQuantity, 0);
assert.equal(observedGray, false);
assert.equal(view.rootView.money, 0);
assert.equal(view.rootView.freeMoney, 0);
assert.equal(view.gray, true);
assert.equal(view.model.gachaKindList[0].needPointKind, "MONEY");
assert.equal(view.model.gachaKindList[0].needQuantity, 1500);

quantity = 0;
view.rootView = {money: 0, freeMoney: 0};
view.gray = false;
view.gachaPopup({currentTarget: target});
assert.equal(originalCalls, 2);
assert.equal(observedTotal, 0);
assert.equal(observedPointKind, "MONEY");
assert.equal(observedQuantity, 1500);
console.log("Gacha account perk overlay bypass: PASS");
