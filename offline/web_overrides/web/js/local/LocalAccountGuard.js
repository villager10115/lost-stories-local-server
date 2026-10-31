define([
  "backboneCommon",
  "command"
], function (common, command) {
  "use strict";

  var installed = false;
  var lastCallback = null;

  function parsePayload(payload) {
    if (typeof payload !== "string") {
      return {value: payload, serialized: false};
    }
    try {
      return {value: JSON.parse(payload), serialized: true};
    } catch (_) {
      return {value: payload, serialized: true};
    }
  }

  function applySaveStatus(payload, status) {
    var parsed = parsePayload(payload);
    var value = parsed.value;
    var existingSave = status && (
      status.hadSaveAtStart === true ||
      (typeof status.hadSaveAtStart === "undefined" && status.hasSave === true));
    if (!existingSave || !value ||
        typeof value !== "object") {
      return payload;
    }

    var result = Object.assign({}, value);
    if (!result.prologue_state || result.prologue_state === "OP0000") {
      result.prologue_state = "OP0070";
    }
    result.name = status.displayName || result.name;
    result.sex = status.sex || result.sex;
    result.player_id = status.playerId || result.player_id;
    result.localSaveValidated = true;
    return parsed.serialized ? JSON.stringify(result) : result;
  }

  function install() {
    if (installed) return;
    installed = true;

    var originalSetNativeCallback = common.setNativeCallback;
    var originalGetPlayerInfo = command.getPlayerInfo;

    common.setNativeCallback = function (callback, target, eventName) {
      lastCallback = {
        callback: callback,
        target: target,
        eventName: eventName
      };
      return originalSetNativeCallback.apply(common, arguments);
    };

    command.getPlayerInfo = function () {
      var request = arguments;
      var registered = lastCallback;
      if (!registered || typeof registered.callback !== "function") {
        return originalGetPlayerInfo.apply(command, request);
      }

      var statusPromise = window.localSaveStatusPromise ||
        Promise.resolve(window.localSaveStatus || {hasSave: false});
      statusPromise.then(function (status) {
        originalSetNativeCallback.call(
          common,
          function (payload) {
            return registered.callback(applySaveStatus(payload, status));
          },
          registered.target,
          registered.eventName
        );
        originalGetPlayerInfo.apply(command, request);
      });
    };
  }

  return {
    applySaveStatus: applySaveStatus,
    install: install
  };
});
