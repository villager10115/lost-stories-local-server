"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  isBodyCapturePath,
  sanitizeUrl,
  summarizePostData,
} = require("./gacha_capture.js");

test("keeps only endpoint path and query parameter names", () => {
  assert.deepEqual(
    sanitizeUrl(
      "https://app.lost-stories.net/api/page/MyPage?value=userCardList&timeStamp=1"
    ),
    {
      host: "app.lost-stories.net",
      path: "/api/page/MyPage",
      query_keys: ["timeStamp", "value"],
    }
  );
});

test("keeps gacha selection fields and drops unknown values", () => {
  assert.deepEqual(
    summarizePostData(
      "/api/gacha/draw",
      JSON.stringify({
        gachaScheduleId: 1795,
        gachaBeanKind: "SELECTABLE10",
        cardId: 101001,
        token: "must-not-be-recorded",
      })
    ),
    {
      keys: ["cardId", "gachaBeanKind", "gachaScheduleId", "token"],
      gachaScheduleId: 1795,
      gachaBeanKind: "SELECTABLE10",
      cardId: 101001,
    }
  );
});

test("body capture is restricted to explicit endpoints", () => {
  assert.equal(isBodyCapturePath("/api/gacha/draw"), true);
  assert.equal(isBodyCapturePath("/api/gacha/result/example"), true);
  assert.equal(isBodyCapturePath("/api/gacha/probability"), true);
  assert.equal(isBodyCapturePath("/api/page/GachaTop"), true);
  assert.equal(isBodyCapturePath("/api/page/MyPage"), true);
  assert.equal(isBodyCapturePath("/api/user/secret"), false);
});
