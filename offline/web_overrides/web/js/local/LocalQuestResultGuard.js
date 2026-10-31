define(["backboneCommon"], function () {
  "use strict";

  var observer = null;

  function ensureTrustZero() {
    var columns = document.querySelectorAll(".charaCol");
    for (var i = 0; i < columns.length; i++) {
      var column = columns[i];
      if (column.querySelector(".trustGuageInner.trust0")) continue;
      var node = document.createElement("div");
      node.className = "trustGuageInner trust0";
      node.style.width = "0%";
      node.style.display = "none";
      column.appendChild(node);
    }
  }

  function install() {
    if (observer) return;
    observer = new MutationObserver(ensureTrustZero);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true
    });
    window.addEventListener("hashchange", ensureTrustZero);
    ensureTrustZero();
  }

  return {
    ensureTrustZero: ensureTrustZero,
    install: install
  };
});
