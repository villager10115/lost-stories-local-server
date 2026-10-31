"use strict";
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const handlers = {};
const calls = [];
const command = {showQuestMovie(data){calls.push(['show', data]);},
                 removeQuestMovie(){calls.push(['hide']);}};
const window = {location:{hash:'#/QuestTop'}, setTimeout(){},
  addEventListener(event, fn){(handlers[event] ||= []).push(fn);}};
let guard;
vm.runInNewContext(fs.readFileSync(path.join(__dirname,
  'web_overrides/web/js/local/LocalUnavailableLinks.js'), 'utf8'), {
  define(deps, factory){guard=factory({}, command);}, window,
  document:{addEventListener(){}, querySelectorAll(){return [];}}
});
guard.install();
command.showQuestMovie({partId:6,chapterId:50});
window.location.hash='#/MainStoryTop';
handlers.hashchange.forEach(fn=>fn());
assert.deepEqual(calls, [['show',{partId:6,chapterId:50}],['hide']]);
window.location.hash='#/MyPage';
handlers.hashchange.forEach(fn=>fn());
command.showQuestMovie({partId:6,chapterId:50}); // stale async page callback
assert.equal(calls.length,2);
window.location.hash='#/QuestTop';
handlers.hashchange.forEach(fn=>fn());
command.showQuestMovie({partId:6,chapterId:50});
assert.equal(calls.length,3,'Returning to QuestTop must still play its movie');
command.removeQuestMovie();
guard.install();
assert.equal(handlers.hashchange.length,2,'Installation must be idempotent');
console.log('Quest native movie route ownership and late callbacks: PASS');
