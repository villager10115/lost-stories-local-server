"use strict";
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { createOfflineBridge } = require("./native_bridge");

const envelope = (name, params) => ({
    type: "message",
    message: "zero://" + name + (params === undefined ? "" :
        "?commandParam=" + encodeURIComponent(JSON.stringify(params)))
});

test("startup callbacks preserve order and are asynchronous", () => {
    const jobs = [], received = [];
    const callbacks = {};
    for (const name of ["nativeCallback", "setDeviceInfo", "appVersionGet",
        "getDmmInfo", "getSnsUserIdCallback"]) {
        callbacks[name] = value => received.push([name, value]);
    }
    const bridge = createOfflineBridge({
        callbacks, appVersion: "1.4.86", schedule: job => jobs.push(job)
    });
    const commands = [
        ["GET_RESET_COUNT", { callback: "nativeCallback" }],
        ["GET_DEVICE_INFO", { callbackName: "setDeviceInfo" }],
        ["GET_APP_VERSION"],
        ["GET_DMM_INFO", { callback: "getDmmInfo" }],
        ["GET_SNS_USER_ID", { callback: "getSnsUserIdCallback", useCallback: true }],
        ["GET_ACCESS_TOKEN", { useCallback: true }]
    ];
    for (const [name, params] of commands) {
        assert.equal(bridge.postMessage(envelope(name, params)).status, "scheduled");
    }
    assert.equal(received.length, 0);
    jobs.forEach(job => job());
    assert.deepEqual(received.map(item => item[0]), [
        "nativeCallback", "setDeviceInfo", "appVersionGet",
        "getDmmInfo", "getSnsUserIdCallback", "nativeCallback"
    ]);
    assert.equal(received[0][1].resetCount, 1);
    assert.equal(received[2][1], "1.4.86");
    assert.equal(received[3][1].onetime_token, "");
    assert.equal(received[5][1].accessToken, "");
});

test("external, purchase and arbitrary callback commands cannot dispatch", () => {
    const jobs = [];
    const bridge = createOfflineBridge({
        callbacks: { nativeCallback() {} }, appVersion: "1.4.86",
        schedule: job => jobs.push(job)
    });
    for (const name of ["OPEN_URL", "EXECUTE_PURCHASE", "DELETE_USER_DEFAULTS_ALL"]) {
        assert.equal(bridge.postMessage(envelope(name, { secret: "private-value" })).status, "blocked");
    }
    assert.equal(bridge.postMessage(envelope("GET_RESET_COUNT", {
        callback: "constructor.constructor"
    })).status, "rejected");
    assert.equal(bridge.postMessage(envelope("GET_APP_VERSION")).status, "missing_callback");
    assert.equal(jobs.length, 0);
    assert.equal(JSON.stringify(bridge.diagnostics()).includes("private-value"), false);
    assert.equal(bridge.diagnostics()["UNSUPPORTED:blocked"], 3);
});

test("malformed envelopes and parameters are rejected", () => {
    const bridge = createOfflineBridge({ callbacks: {}, appVersion: "1.4.86" });
    for (const value of [null, [], {}, { type: "message", message: "https://example.invalid" },
        { type: "message", message: "zero://GET_RESET_COUNT?commandParam=%ZZ" },
        { type: "message", message: "zero://GET_RESET_COUNT?commandParam={}&extra=1" },
        envelope("GET_RESET_COUNT", []), envelope("GET_RESET_COUNT", null),
        { type: "message", message: "x".repeat(65537) }]) {
        assert.equal(bridge.postMessage(value).status, "rejected");
    }
    assert.throws(() => createOfflineBridge({ callbacks: {}, appVersion: "unknown" }));
});

test("preview-only effects do not fabricate native completion", () => {
    const bridge = createOfflineBridge({ callbacks: {}, appVersion: "1.4.86" });
    assert.equal(bridge.postMessage(envelope("GET_FONT")).status, "unavailable");
    assert.equal(bridge.postMessage(envelope("SET_WEBVIEW_VISIBLE", { isVisible: true })).status,
        "ignored_preview_only");
    assert.equal(bridge.postMessage(envelope("SET_CDN_QUERY_VERSION", { version: 1 })).status,
        "ignored_preview_only");
});
