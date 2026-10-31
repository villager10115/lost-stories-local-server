"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const html = fs.readFileSync(path.join(__dirname,"web_overrides/web/index.html"),"utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(m=>m[1])
  .filter(script =>
    script.includes('location.hash === "#/DeckFormation"') ||
    script.includes("var allowed =")
  );
for (const route of ["MyPage","ComposePilot","ComposeKmf","DeckFormation",
                     "MainStoryTop", "MainStoryTop/106201", "QuestBackground", "QuestResult"]) {
  const timers=[];
  const location={hash:"#/"+route,pathname:"/web/index.html",search:""};
  let redirects=0;
  const context={location,history:{replaceState(){redirects++;}},
    document:{getElementById(){return null;}},
    require(deps, callback){},
    setInterval(fn){timers.push(fn);},
    setTimeout(){throw Error("Entry must not schedule forced navigation or native callbacks");}};
  for(const script of scripts)vm.runInNewContext(script,context);
  for(let tick=0;tick<30;tick++)for(const timer of timers)timer();
  assert.equal(location.hash,"#/"+route,"Supported page must remain selected");
  // Existing cold-start deck recovery is a one-time replaceState, not a timer.
  assert.equal(redirects,route==="DeckFormation"?1:0);
}
assert.ok(!html.includes("window.onerror="),"Runtime errors must remain observable");
assert.ok(!html.includes("var allowed ="), "Routes must not race an independent timed redirect");
assert.ok(!html.includes("command.hideLoading()"),"Entry timers must not inject native completions");
assert.ok(html.includes('"js/local/LocalUnavailableLinks"'),
  "Unimplemented compose entries must be gated before routing");
assert.ok(html.includes('"js/local/LocalSceneRecovery"'),
  "Scene recovery must load with the local entry guard");
assert.ok(html.includes('"js/local/LocalAccountGuard"'),
  "Existing local saves must be checked before the new-account prologue");
assert.ok(html.includes("js/local/LocalAccountStatus.js"),
  "The entry must query save status before the router starts");
assert.ok(html.includes('"js/local/LocalKmfStateGuard"'),
  "Incomplete KMF records must be normalized before page rendering");
assert.ok(html.includes('"js/local/LocalQuestResultGuard"'),
  "Quest-result rank animation must install the trust-zero guard");
assert.ok(html.includes('"js/local/LocalGachaPerk"'),
  "The account gacha perk must bypass unavailable purchase overlays");
console.log("Entry navigation: compose routes retained; no timed restarts/native completions: PASS");
