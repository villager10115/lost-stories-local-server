"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "web_overrides/web/js/local/LocalKmfStrength.js"
);
const PAGE = path.join(
  __dirname,
  "web_overrides/web/js/local/LocalEnhancementPage.js"
);

let strength;
vm.runInNewContext(fs.readFileSync(SOURCE, "utf8"), {
  define(factory) {
    strength = factory();
  }
});

const kmfs = [
  {
    userKnightmareFrameId: "top",
    weaponList: [
      {selected: false, strength: 999},
      {selected: true, strength: 130}
    ]
  },
  {
    userKnightmareFrameId: "tie-a",
    weaponList: [{selected: true, strength: 100}]
  },
  {
    userKnightmareFrameId: "tie-b",
    strength: 100,
    weaponList: []
  },
  {
    userKnightmareFrameId: "fallback",
    weaponList: [{selected: true}]
  },
  {
    userKnightmareFrameId: "missing",
    weaponList: []
  }
];
const customizations = [
  {
    userKnightmareFrameId: "fallback",
    selected: true,
    strength: 74
  },
  {
    userKnightmareFrameId: "missing",
    selected: true,
    strength: 88
  }
];

const decorated = strength.decorate(kmfs, customizations);
assert.deepEqual(
  Array.from(decorated, (row) => row.strength),
  [130, 100, 100, 74, 88]
);
assert.equal(decorated[0].tier, 5);
assert.equal(decorated[1].tier, decorated[2].tier);
assert.equal(decorated[3].tier, 1);
assert.equal(decorated[4].tier, 2);

assert.equal(strength.strengthFor({
  weaponList: [{selected: true, strength: 77}]
}), 77);
assert.equal(strength.strengthFor({
  weaponList: [{selected: true, strength: "invalid"}]
}), null);
assert.equal(strength.tierFor(null, []), 0);
assert.deepEqual(
  Array.from(strength.decorate([
    {weaponList: [{selected: true, strength: 20}]},
    {weaponList: [{selected: true, strength: 20}]}
  ]), (row) => row.tier),
  [3, 3]
);

const page = fs.readFileSync(PAGE, "utf8");
assert.match(page, /js\/local\/LocalKmfStrength/);
assert.match(page, /userKnightmareFrameCustomizeList/);
assert.match(page, /data-strength-tier/);
assert.match(page, /kmfStrength\.decorate/);
assert.match(page, /\/api\/knightmareFrame\/color/);
assert.doesNotMatch(page, /\/api\/local\/kmf\/color/);
assert.match(page, /userKnightmareFrameId: id/);
assert.match(page, /customColorR/);

const rendered = {html: ""};
let pagePrototype;
let pageFactory;
const common = {
  storage: {
    knightmareFrameList: {
      each(callback) {
        callback({toJSON() {
          return {knightmareFrameId: 2201, name: "Test KMF"};
        }});
      }
    },
    userKnightmareFrameList: {toJSON() { return kmfs; }},
    userKnightmareFrameCustomizeList: {toJSON() { return customizations; }}
  },
  content: {append() {}},
  setStyle() {},
  setGlobalContents() {},
  ready: {hide() {}},
  cgti: "click"
};
vm.runInNewContext(page, {
  define(dependencies, factory) {
    assert.deepEqual(Array.from(dependencies), [
      "backboneCommon",
      "ajaxControl",
      "command",
      "js/local/LocalKmfStrength"
    ]);
    pageFactory = factory(common, {}, {}, strength);
  },
  Backbone: {View: {extend(prototype) {
    pagePrototype = prototype;
    return function () {};
  }}},
  _: {escape(value) { return String(value); }},
  window: {},
  fetch() { throw new Error("render must not fetch"); }
});
pagePrototype.render.call({
  mode: "coloring",
  $el: {html(value) { rendered.html = value; }, on() {}}
});
assert.match(rendered.html, /data-strength-tier="5"/);
assert.match(rendered.html, /戦力<b>130<\/b>/);
assert.match(rendered.html, /leLegendDot/);
assert.equal(typeof pageFactory.create, "function");

console.log(
  "Local KMF strength coloring: selected weapons, fallback strength, ties and page contract: PASS"
);
