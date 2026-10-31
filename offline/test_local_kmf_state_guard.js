"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "web_overrides/web/js/local/LocalKmfStateGuard.js"
);

function record(values) {
  return {
    values,
    get(key) {
      return values[key];
    },
    toJSON() {
      return {...values};
    }
  };
}

function collection(rows) {
  return {
    rows,
    toJSON() {
      return rows.map((row) => row.toJSON());
    },
    where(query) {
      return rows.filter((row) =>
        Object.entries(query).every(([key, value]) => row.get(key) === value));
    },
    findWhere(query) {
      return this.where(query)[0] || null;
    }
  };
}

let guard;
const common = {
  storage: {
    knightmareFrameList: collection([
      record({knightmareFrameId: 2201, name: "Test KMF"})
    ]),
    knightmareFrameCustomizeList: collection([
      record({
        knightmareFrameCustomizeId: 220102,
        knightmareFrameId: 2201,
        sortKey: 2
      }),
      record({
        knightmareFrameCustomizeId: 220101,
        knightmareFrameId: 2201,
        sortKey: 1
      })
    ]),
    userKnightmareFrameCustomizeList: collection([
      record({
        userKnightmareFrameId: "owned-kmf",
        knightmareFrameCustomizeId: 220101,
        selected: true,
        strength: 124
      })
    ]),
    userCardList: collection([
      record({cardId: 103004, strength: 468}),
      record({cardId: 113001})
    ]),
    userKnightmareFrameList: collection([
      record({
        userKnightmareFrameId: "owned-kmf",
        weaponList: [{selected: true, strength: 124}]
      }),
      record({
        userKnightmareFrameId: "empty-kmf",
        weaponList: []
      })
    ])
  },
  getPlayerStrength() {
    throw new Error("original getPlayerStrength must be replaced");
  },
  setUserKnightmareFrameModel() {
    throw new Error("original KMF model handler must be replaced");
  }
};

vm.runInNewContext(
  fs.readFileSync(SOURCE, "utf8"),
  {
    define(deps, factory) {
      assert.deepEqual(Array.from(deps), ["backboneCommon"]);
      guard = factory(common);
    },
    window: {}
  }
);

guard.install();
assert.equal(guard.install(), guard.state);
assert.equal(guard.state.installed, true);

let setPayload;
const model = {
  get(key) {
    return {
      knightmareFrameId: 2201,
      userKnightmareFrameId: "owned-kmf"
    }[key];
  },
  set(payload, options) {
    setPayload = {payload, options};
  }
};
common.setUserKnightmareFrameModel(model);
assert.equal(setPayload.payload.weaponList.length, 1);
assert.equal(
  setPayload.payload.weaponList[0].knightmareFrameCustomizeId,
  220101
);
assert.equal(guard.state.skippedCustomizations, 1);
assert.equal(setPayload.options.silent, true);
assert.equal(common.getPlayerStrength(), 592);
assert.equal(guard.state.lastCalculatedStrength, 592);

console.log(
  "Local KMF state guard: unowned customizations are skipped and missing weapon strength is ignored: PASS"
);
