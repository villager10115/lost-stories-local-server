define([], function () {
  "use strict";
  function point(event) {
    var source = event.originalEvent || event;
    var touch = (source.touches && source.touches[0]) ||
      (source.changedTouches && source.changedTouches[0]) || source;
    return {x: touch.clientX, y: touch.clientY};
  }
  function wrap(View, common, kind) {
    var proto = View.prototype;
    var start = proto[kind + "Popuptimer"];
    var select = proto[kind + "Select"];
    var events = proto.events;
    function cancel() {
      if (this.localGesture) this.localGesture.cancelled = true;
      clearTimeout(this.popupTimer);
      common.removeClass(this.el, "scale");
    }
    function move(event) {
      if (!this.localGesture) return;
      var p = point(event), g = this.localGesture;
      if (Math.hypot(p.x - g.x, p.y - g.y) > 10) cancel.call(this);
    }
    proto[kind + "Popuptimer"] = function (event) {
      cancel.call(this);
      this.localGesture = point(event);
      return start.call(this, event);
    };
    proto[kind + "Select"] = function (event) {
      move.call(this, event);
      var gesture = this.localGesture;
      this.localGesture = null;
      if (!gesture || gesture.cancelled) {
        cancel.call(this);
        event.preventDefault();
        return;
      }
      return select.call(this, event);
    };
    proto.events = function () {
      var result = events.call(this);
      result[common.cgtm] = move;
      result.mouseleave = cancel;
      result.touchcancel = cancel;
      return result;
    };
  }
  return {wrap: wrap};
});
