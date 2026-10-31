"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

let purchase;
let xhrRequest;
let noticeText;
let closeCount = 0;
const rows = {
  MONEY: {quantity: 0, set(value) { this.quantity = value.quantity; }},
  PRESENTED_MONEY: {quantity: 0, set(value) { this.quantity = value.quantity; }}
};
const common = {
  storage: {
    userItemList: {
      findWhere(query) {
        return rows[query.itemId] || null;
      }
    },
    userShopItemList: {set() {}}
  },
  isScrolled() { return false; },
  tapBlock() {},
  setPlayerPaidStone() {},
  OverlapInfomation(text) { noticeText = text; },
  globalHeaderView: {changeItem() {}},
  PopupClass: function () {}
};

function FakeXMLHttpRequest() {
  this.headers = {};
  this.readyState = 0;
  this.status = 0;
}
FakeXMLHttpRequest.prototype.open = function (method, url) {
  this.method = method;
  this.url = url;
};
FakeXMLHttpRequest.prototype.setRequestHeader = function (name, value) {
  this.headers[name] = value;
};
FakeXMLHttpRequest.prototype.send = function (body) {
  this.body = body;
  this.readyState = 4;
  this.status = 200;
  this.responseText = JSON.stringify({
    resultCode: "success",
    userItemList: [
      {itemId: "MONEY", quantity: 3000},
      {itemId: "PRESENTED_MONEY", quantity: 500}
    ]
  });
  xhrRequest = this;
  this.onreadystatechange();
};

vm.runInNewContext(
  fs.readFileSync(path.join(
    __dirname,
    "web_overrides/web/js/local/LocalPurchaseNotice.js"), "utf8"),
  {
    define(deps, factory) {
      assert.deepEqual(Array.from(deps), ["backboneCommon"]);
      purchase = factory(common);
    },
    Date,
    JSON,
    XMLHttpRequest: FakeXMLHttpRequest
  }
);

purchase({preventDefault() {}}, () => { closeCount += 1; });
assert.equal(xhrRequest.url, "/api/shop/buy");
assert.equal(xhrRequest.method, "POST");
assert.equal(xhrRequest.headers["Content-Type"], "application/json");
assert.equal(xhrRequest.headers["X-Web-Session-Id"].length > 0, true);
assert.deepEqual(JSON.parse(xhrRequest.body), {
  shopId: 99001,
  shopItemId: 990001,
  num: 1
});
assert.equal(rows.MONEY.quantity, 3000);
assert.equal(rows.PRESENTED_MONEY.quantity, 500);
assert.equal(noticeText, "サクラダイト3,000個を補給しました。");
assert.equal(closeCount, 1);
console.log("Free paid-stone purchase hook: PASS");
