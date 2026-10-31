define([], function () {
  "use strict";

  var PUSH_HOME_TIMEOUT_MS = 5000;
  var FORCE_VISIBLE_DELAY_MS = 2500;
  var bridgePostMessage = null;
  var bridge = null;
  var nativeCallbackOriginal = null;
  var pushHomeTimer = null;
  var forceVisibleTimer = null;

  var state = window.__localSceneRecovery = window.__localSceneRecovery || {
    installed: false,
    pending: false,
    recoveredCount: 0,
    duplicateCount: 0,
    lastStartedAt: null,
    lastCompletedAt: null,
    lastRecoveredAt: null,
    lastForcedAt: null,
    lastEvent: null
  };

  function publish(eventName, detail) {
    state.lastEvent = {
      event: eventName,
      at: new Date().toISOString(),
      detail: detail || null
    };
    try {
      window.dispatchEvent(new CustomEvent("local-scene-recovery", {
        detail: state.lastEvent
      }));
    } catch (_) {}
  }

  function messageText(message) {
    if (typeof message === "string") return message;
    if (message && typeof message.message === "string") return message.message;
    return "";
  }

  function commandName(message) {
    var text = messageText(message);
    var match = /^zero:\/\/([^?]+)/.exec(text);
    return match ? match[1] : "";
  }

  function sendRaw(name, parameter) {
    if (!bridge || typeof bridgePostMessage !== "function") return false;
    var message = "zero://" + name;
    if (parameter) {
      message += "?commandParam=" + encodeURIComponent(JSON.stringify(parameter));
    }
    bridgePostMessage.call(bridge, {type: "message", message: message});
    return true;
  }

  function clearPushHomeTimer() {
    if (pushHomeTimer !== null) {
      clearTimeout(pushHomeTimer);
      pushHomeTimer = null;
    }
  }

  function clearForceVisibleTimer() {
    if (forceVisibleTimer !== null) {
      clearTimeout(forceVisibleTimer);
      forceVisibleTimer = null;
    }
  }

  function completePushHome(source) {
    if (!state.pending) return;
    clearPushHomeTimer();
    state.pending = false;
    state.lastCompletedAt = new Date().toISOString();
    publish("push-home-complete", {source: source});
  }

  function forceVisible() {
    forceVisibleTimer = null;
    sendRaw("SET_WEBVIEW_VISIBLE", {isVisible: true});
    sendRaw("HIDE_LOADING");

    var loading = document.getElementById("loading");
    if (loading) loading.className = "hide";
    var tapBlock = document.getElementById("tapBlock");
    if (tapBlock) tapBlock.className = "";
    var ready = document.getElementById("ready");
    if (ready) ready.className = "";
    var baseContainer = document.getElementById("baseContainer");
    if (baseContainer) baseContainer.style.display = "block";
    var mainContent = document.getElementById("mainContent");
    if (mainContent) mainContent.style.display = "block";

    state.lastForcedAt = new Date().toISOString();
    publish("webview-forced-visible");
  }

  function scheduleForceVisible() {
    clearForceVisibleTimer();
    forceVisibleTimer = setTimeout(forceVisible, FORCE_VISIBLE_DELAY_MS);
  }

  function onPushHomeTimeout() {
    if (!state.pending) return;

    clearPushHomeTimer();
    state.pending = false;
    state.recoveredCount += 1;
    state.lastRecoveredAt = new Date().toISOString();
    scheduleForceVisible();
    publish("push-home-timeout", {
      timeoutMs: PUSH_HOME_TIMEOUT_MS,
      recoveredCount: state.recoveredCount
    });

    // The page registers its continuation on nativeCallback immediately
    // before PUSH_HOME. Resuming it here avoids leaving the WebView hidden.
    try {
      if (typeof nativeCallbackOriginal === "function") {
        nativeCallbackOriginal();
      }
    } catch (error) {
      publish("native-callback-error", {message: String(error)});
    }
  }

  function armPushHome() {
    var now = new Date().toISOString();
    state.lastStartedAt = now;
    if (state.pending) {
      state.duplicateCount += 1;
      publish("push-home-duplicate", {duplicateCount: state.duplicateCount});
      return;
    }
    state.pending = true;
    clearPushHomeTimer();
    pushHomeTimer = setTimeout(onPushHomeTimeout, PUSH_HOME_TIMEOUT_MS);
    publish("push-home-pending", {timeoutMs: PUSH_HOME_TIMEOUT_MS});
  }

  function installBridge() {
    if (bridge && bridge.__localSceneRecoveryWrapped) return true;
    bridge = window.vuplex;
    if (!bridge || typeof bridge.postMessage !== "function") return false;

    bridgePostMessage = bridge.postMessage;
    var wrappedPostMessage = function (message) {
      var name = commandName(message);
      if (name === "PUSH_HOME") {
        armPushHome();
      } else if (
        name === "SET_WEBVIEW_VISIBLE" &&
        messageText(message).indexOf("%22isVisible%22%3Atrue") !== -1
      ) {
        clearForceVisibleTimer();
      }
      return bridgePostMessage.apply(bridge, arguments);
    };
    Object.defineProperty(wrappedPostMessage, "__localSceneRecoveryWrapper", {
      value: true
    });
    bridge.postMessage = wrappedPostMessage;
    Object.defineProperty(bridge, "__localSceneRecoveryWrapped", {
      value: true
    });
    return true;
  }

  function installNativeCallback() {
    if (typeof nativeCallback !== "function") return false;
    if (nativeCallback.__localSceneRecoveryWrapper) return true;

    nativeCallbackOriginal = nativeCallback;
    var wrappedNativeCallback = function () {
      completePushHome("native-callback");
      return nativeCallbackOriginal.apply(this, arguments);
    };
    Object.defineProperty(wrappedNativeCallback, "__localSceneRecoveryWrapper", {
      value: true
    });
    nativeCallback = wrappedNativeCallback;
    return true;
  }

  function install() {
    if (state.installed) return state;
    var bridgeReady = installBridge();
    var callbackReady = installNativeCallback();
    state.installed = bridgeReady && callbackReady;
    if (state.installed) publish("installed");
    return state;
  }

  return {
    install: install,
    state: state,
    PUSH_HOME_TIMEOUT_MS: PUSH_HOME_TIMEOUT_MS,
    FORCE_VISIBLE_DELAY_MS: FORCE_VISIBLE_DELAY_MS
  };
});
