"use strict";
const assert = require("node:assert/strict");
const { test } = require("node:test");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

function fixture() {
    const jobs = [];
    const context = vm.createContext({ queueMicrotask: job => jobs.push(job) });
    vm.runInContext("globalThis.window = globalThis; const received = [];", context);
    for (const file of ["native_bridge.js", "bridge_binding.js"]) {
        vm.runInContext(fs.readFileSync(path.join(__dirname, file), "utf8"), context);
    }
    return { context, jobs };
}

test("preinstalled bridge resolves later global lexical callbacks, not window properties", () => {
    const { context, jobs } = fixture();
    vm.runInContext('const bridge = installOfflineBridge("1.4.86");', context);
    // Synthetic declarations only: never evaluate cached game scripts in node:vm.
    vm.runInContext(`
        let nativeCallback = value => received.push(["reset", value.resetCount]),
            setDeviceInfo = value => received.push(["device", value.platform]),
            appVersionGet = value => {
                received.push(["version", value]);
                window.vuplex.postMessage({
                    type: "message", message: "zero://GET_DMM_INFO"
                });
            },
            getDmmInfo = value => received.push(["identity", value.viewer_id]),
            getSnsUserIdCallback = value => received.push(["sns", value.snsUserId]);
        for (const command of ["GET_RESET_COUNT", "GET_DEVICE_INFO", "GET_APP_VERSION"]) {
            window.vuplex.postMessage({type: "message", message: "zero://" + command});
        }
    `, context);
    assert.equal(vm.runInContext("window.appVersionGet", context), undefined);
    assert.equal(vm.runInContext("received.length", context), 0);
    while (jobs.length) jobs.shift()();
    assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(received)", context)), [
        ["reset", 1], ["device", "Windows"], ["version", "1.4.86"], ["identity", "offline"]
    ]);
    assert.equal(vm.runInContext("bridge.diagnostics()['GET_DMM_INFO:scheduled']", context), 1);
});

test("installation refuses existing bridges and cannot be repeated", () => {
    const { context } = fixture();
    vm.runInContext("window.vuplex = { real: true };", context);
    assert.throws(() => vm.runInContext('installOfflineBridge("1.4.86")', context),
        /Refusing to replace/);
    assert.equal(vm.runInContext("window.vuplex.real", context), true);
    const other = fixture().context;
    vm.runInContext('installOfflineBridge("1.4.86")', other);
    assert.throws(() => vm.runInContext('installOfflineBridge("1.4.86")', other),
        /Refusing to replace/);
    assert.equal(vm.runInContext("Object.isFrozen(window.vuplex)", other), true);
});

test("invalid configuration does not install a partial bridge", () => {
    const { context } = fixture();
    assert.throws(() => vm.runInContext('installOfflineBridge("unknown")', context));
    assert.equal(vm.runInContext("'vuplex' in window", context), false);
});
