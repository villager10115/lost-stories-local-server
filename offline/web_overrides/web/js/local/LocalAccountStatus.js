(function () {
  "use strict";

  var sessionId = String(Date.now());
  window.localSaveStatus = {
    resultCode: "success",
    hasSave: false,
    checked: false
  };
  window.localSaveStatusPromise = fetch("/api/local/save-status", {
    cache: "no-store",
    headers: {"X-Web-Session-Id": sessionId}
  }).then(function (response) {
    if (!response.ok) throw new Error("save status " + response.status);
    return response.json();
  }).then(function (payload) {
    window.localSaveStatus = Object.assign({}, payload, {
      checked: true
    });
    return window.localSaveStatus;
  }).catch(function () {
    window.localSaveStatus = {
      resultCode: "error",
      hasSave: false,
      checked: false
    };
    return window.localSaveStatus;
  });
})();
