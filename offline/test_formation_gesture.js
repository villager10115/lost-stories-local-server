const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
let guard, cleared = [];
vm.runInNewContext(fs.readFileSync(__dirname + '/web_overrides/web/js/local/LocalFormationGesture.js', 'utf8'), {
  define: (_, factory) => guard = factory(), clearTimeout: id => cleared.push(id), Math
});
for (const kind of ['pilot', 'kmf']) {
  let selections = 0, timers = 0;
  function View() { this.el = {}; }
  View.prototype.events = () => ({});
  View.prototype[kind + 'Popuptimer'] = function () { this.popupTimer = ++timers; };
  View.prototype[kind + 'Select'] = function () { selections++; };
  guard.wrap(View, {cgtm: 'mousemove', removeClass() {}}, kind);
  const view = new View(), events = view.events();
  const event = (x, y) => ({clientX: x, clientY: y, preventDefault() {}});
  view[kind + 'Popuptimer'](event(10, 10));
  view[kind + 'Select'](event(13, 12));
  assert.equal(selections, 1, 'A stationary click still selects');
  view[kind + 'Popuptimer'](event(10, 10));
  events.mousemove.call(view, event(10, 35));
  assert.ok(cleared.includes(view.popupTimer), 'Dragging cancels long press');
  view[kind + 'Select'](event(10, 10));
  assert.equal(selections, 1, 'Returning to origin cannot reactivate a drag');
  view[kind + 'Popuptimer'](event(10, 10));
  events.mouseleave.call(view);
  view[kind + 'Select'](event(10, 10));
  assert.equal(selections, 1, 'Leaving cancels the gesture');
  view[kind + 'Select'](event(10, 10));
  assert.equal(selections, 1, 'A release without a press cannot select');
  const touch = (x, y) => ({originalEvent: {changedTouches: [{clientX:x, clientY:y}]}, preventDefault() {}});
  view[kind + 'Popuptimer'](touch(5, 5));
  events.mousemove.call(view, touch(50, 5));
  view[kind + 'Select'](touch(50, 5));
  assert.equal(selections, 1, 'Touch drags cannot select');
}
console.log('Pilot and KMF click, drag, long-press cancellation and touch regressions passed.');
