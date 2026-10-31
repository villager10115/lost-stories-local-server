"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const base = process.env.QUEST_WEB_ROOT || path.join(__dirname, "web_overrides/web");
const entry = fs.readFileSync(path.join(base, "index.html"), "utf8");
const pages = ["MainStoryTop", "DailyQuestTop", "ChallengeQuestTop", "ExpeditionTop",
  "RootEntangleTop", "AnotherQuestTop", "SideQuestTop", "EventStoryTop",
  "EventMultiFrontTop", "EventHighStrategicCommandTop"];

// Exercise the shipped periodic route policy, if present, with each real link.
for (const page of pages) {
  const location = {hash: "#/" + page};
  const timers = [];
  for (const match of entry.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
    if (/setInterval/.test(match[1]) && /location\.hash/.test(match[1])) {
      vm.runInNewContext(match[1], {location, setInterval: fn => timers.push(fn)});
    }
  }
  for (let tick = 0; tick < 4; tick++) timers.forEach(fn => fn());
  assert.equal(location.hash, "#/" + page, page + " must not be silently sent home");
}

let guard;
const events = {};
const notices = [];
class Element { closest() {return this;} getAttribute() {return this.href;} }
const window = {location:{hash:"#/QuestTop"}, setTimeout(){}, addEventListener(){}};
const common = {PopupClass: function (model) {notices.push(model);}};
vm.runInNewContext(fs.readFileSync(path.join(base, "js/local/LocalUnavailableLinks.js"), "utf8"), {
  define(deps, factory) {guard = factory(common, {showQuestMovie(){}, removeQuestMovie(){}});},
  window, Element, document:{querySelectorAll(){return [];},
    addEventListener(name, fn){events[name] = fn;}}
});
guard.install();
for (const page of pages.slice(2)) {
  assert.ok(guard.blockedFor("#/" + page), page);
  assert.ok(guard.blockedFor("#/" + page + "/1710"), page + " nested route");
}
assert.equal(guard.blockedFor("#/MainStoryTop"), null);
assert.equal(guard.blockedFor("#/DailyQuestTop"), null);
const target = new Element(); target.href = "#/ExpeditionTop";
let prevented = false, stopped = false;
events.click({target, preventDefault(){prevented=true;}, stopImmediatePropagation(){stopped=true;}});
assert.ok(prevented && stopped && notices.length === 1);
assert.equal(window.location.hash, "#/QuestTop");
assert.equal(notices[0].canClose, true);

// Run the actual MainStory initializer with only the verified current map.
const views = [], messages = [];
const quest = {questId:418101, quest:{questType:"MAIN", onlyStory:false, difficulty:"NORMAL"}};
const mainCommon = {storage:{userQuestList:{toJSON:()=>[quest]}}, historyArr:[],
  isScrolled:()=>false, OverlapInfomation: message=>messages.push(message)};
vm.runInNewContext(fs.readFileSync(path.join(base, "js/quest/MainStoryTop.js"), "utf8"), {
  define(deps, factory){factory(mainCommon, {}, {}, "", "", function(){});},
  Backbone:{View:{extend(spec){views.push(spec);return function(){};}}},
  _:{template:()=>()=>""}, console:{log(){}}, window:{}, setTimeout(){}
});
for (const requestedMode of [undefined,"story","extra","battle"]) {
  const instance = {createDom(){this.created=true;}};
  views[0].initialize.call(instance, requestedMode);
  assert.equal(instance.displayMode, "battle");
  assert.equal(instance.created, true);
}
for (const unavailableMode of ["story","extra"]) {
  const instance = {displayMode:"battle"};
  views[0].displayChange.call(instance, {preventDefault(){}, currentTarget:{dataset:{mode:unavailableMode}}});
  assert.equal(instance.displayMode, "battle");
}
assert.equal(messages.length,2);
console.log("Quest directory routes, unavailable notices, and captured-map mode selection: PASS");
