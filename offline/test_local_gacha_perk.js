"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

let moduleValue;
const perk = {quantity: 1};
const popupText = {innerHTML: "1日１回無料で１回スカウトをします。"};
const common = {
  doc: {
    querySelector(selector) {
      assert.equal(selector, "#popupArea .popupTextArea .text");
      return popupText;
    }
  },
  storage: {
    userItemList: {
      findWhere(query) {
        return query.itemId === "LOCAL_UNLIMITED_TEN_PULL"
          ? {toJSON: () => perk} : null;
      }
    }
  }
};
const label = {textContent: "1日1回無料"};
const classes = new Set(["grayBtn"]);
const button = {
  dataset: {gachaNum: "7"},
  querySelector(selector) {
    assert.equal(selector, ".itemNum.free");
    return label;
  },
  classList: {
    contains(name) { return classes.has(name); },
    remove(name) { classes.delete(name); },
    add(name) { classes.add(name); }
  }
};
function GachaBtnView() {}
GachaBtnView.prototype.render = function () {
  this.el = {
    querySelectorAll(selector) {
      assert.equal(selector, ".gachaBtn");
      return [button];
    }
  };
  return "rendered";
};
GachaBtnView.prototype.gachaPopup = function (event) {
  this.seenGray = event.currentTarget.classList.contains("grayBtn");
  this.seenMoney = this.rootView.money;
  this.seenFreeMoney = this.rootView.freeMoney;
  this.seenKindNeedPointKind = this.model.gachaKindList[0].needPointKind;
  this.seenKindNeedQuantity = this.model.gachaKindList[0].needQuantity;
  return "drawn";
};
vm.runInNewContext(
  fs.readFileSync(path.join(
    __dirname, "web_overrides/web/js/local/LocalGachaPerk.js"), "utf8"),
  {
    define(deps, factory) {
      assert.equal(deps.length, 2);
      assert.equal(deps[0], "backboneCommon");
      assert.equal(deps[1], "js/view/gacha/GachaBtnView");
      moduleValue = factory(common, GachaBtnView);
    }
  }
);
moduleValue.install();
const view = {
  model: {gachaKindList: [
    {
      gachaKindId: 7,
      beanKind: "RARE10",
      needPointKind: "FREE",
      needQuantity: 0,
      localUnlimitedTenPull: true
    }
  ]},
  rootView: {money: 0, freeMoney: 300}
};
const event = {
  currentTarget: {
    dataset: button.dataset,
    classList: button.classList
  }
};
assert.equal(GachaBtnView.prototype.render.call(view), "rendered");
assert.equal(label.textContent, "10回無料");
assert.equal(
  GachaBtnView.prototype.gachaPopup.call(view, event), "drawn");
assert.equal(popupText.innerHTML, "無料で10回スカウトをします。<br>よろしいですか？");
assert.equal(view.seenGray, false);
assert.equal(view.seenMoney, 0);
assert.equal(view.seenFreeMoney, 0);
assert.equal(view.seenKindNeedPointKind, "FREE");
assert.equal(view.seenKindNeedQuantity, 0);
assert.equal(view.rootView.money, 0);
assert.equal(view.rootView.freeMoney, 300);
assert.equal(classes.has("grayBtn"), true);
const kind = view.model.gachaKindList[0];
kind.needPointKind = "MONEY";
kind.needQuantity = 3000;
assert.equal(
  GachaBtnView.prototype.gachaPopup.call(view, event), "drawn");
assert.equal(view.seenKindNeedPointKind, "FREE");
assert.equal(view.seenKindNeedQuantity, 0);
assert.equal(view.seenFreeMoney, 0);
assert.equal(kind.needPointKind, "MONEY");
assert.equal(kind.needQuantity, 3000);
perk.quantity = 0;
view.rootView.freeMoney = 300;
assert.equal(
  GachaBtnView.prototype.gachaPopup.call(view, event), "drawn");
assert.equal(view.seenFreeMoney, 300);
label.textContent = "1日1回無料";
assert.equal(GachaBtnView.prototype.render.call(view), "rendered");
assert.equal(label.textContent, "1日1回無料");
popupText.innerHTML = "original popup";
GachaBtnView.prototype.gachaPopup.call(view, event);
assert.equal(popupText.innerHTML, "original popup");
console.log("Account gacha perk frontend hook: PASS");
