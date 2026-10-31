define([], function () {
  "use strict";
  function install(root, common) {
    if (!root || root.localPartSelectionInstalled) return;
    root.localPartSelectionInstalled = true;
    var gesture = null;
    function point(event) {
      var p = (event.touches && event.touches[0]) ||
        (event.changedTouches && event.changedTouches[0]) || event;
      return {x: p.clientX, y: p.clientY};
    }
    function card(event) {
      var target = event.target.closest && event.target.closest(".partWrap");
      return target && root.contains(target) ? target : null;
    }
    function move(event) {
      if (!gesture) return;
      var p = point(event);
      if (Math.hypot(p.x - gesture.x, p.y - gesture.y) > 10) gesture.moved = true;
    }
    root.addEventListener(common.cgts, function (event) {
      var target = card(event), p = point(event);
      gesture = target ? {card: target, x: p.x, y: p.y, moved: false} : null;
    }, true);
    root.addEventListener(common.cgtm, move, true);
    root.addEventListener("mouseleave", function () { if (gesture) gesture.moved = true; }, true);
    root.addEventListener("touchcancel", function () { gesture = null; }, true);
    root.addEventListener(common.cgti, function (event) {
      var target = card(event);
      if (!target) { gesture = null; return; }
      move(event);
      var valid = gesture && !gesture.moved && gesture.card === target;
      gesture = null;
      if (!valid) {
        event.preventDefault();
        // Let the official scroller receive the release and finish its drag.
        // The selection callback checks this flag before changing the part.
        event.localPartSelectionCancelled = true;
      }
    }, true);
  }
  return {install: install};
});
