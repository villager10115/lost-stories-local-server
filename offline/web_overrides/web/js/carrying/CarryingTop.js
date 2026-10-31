define(["js/local/LocalKmfLifecyclePage"], function (Page) {
  "use strict";
  return Page.create(function (mode) {
    return mode === "carryOut" ? "carryOut" : "carryIn";
  });
});
