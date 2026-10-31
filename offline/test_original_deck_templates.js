// Isolated rendering of retained official templates; no native/browser input.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path');
const root = process.argv[2];
const context = {console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'underscore.js'), 'utf8'), context);
const _ = context._;
const data = JSON.parse(fs.readFileSync(path.join(root, 'hydrated.json'), 'utf8'));
const shell = _.template(fs.readFileSync(path.join(root, 'DeckFormation.html'), 'utf8'))({});
const templates = Object.fromEntries([...shell.matchAll(/<script[^>]*id=["']([^"']+)["'][^>]*>([\s\S]*?)<\/script>/g)].map(m => [m[1], _.template(m[2])]));
const html = [];
for (const model of data.userCardList) html.push(templates.pilotListParts({model, enableEventLimit:false, limitedFlag:false}));
for (const model of data.userKnightmareFrameList) html.push(templates.kmfListParts({model, enableEventLimit:false, limitedFlag:false}));
for (const pilotModel of [null, ...data.userCardList]) {
  const kmfModel = data.userKnightmareFrameList[0];
  html.push(templates.unitParts({pilotModel, kmfModel, changeArr:[], isNavi:false, eventId:null,
    enableEventLimit:false, limitedFlag:true, kmfLimitedFlag:true, kmfCostUp:{}, pilotCostUpHSC:1000, kmfCostUpHSC:1000}));
}
for (const row of html) assert.ok(!/\bundefined\b|\bNaN\b/.test(row), 'Invalid visible model field');
const resources = [...new Set(html.flatMap(row => [...row.matchAll(/(?:data-src|src)="([^"]+)"/g)].map(m => m[1])))];
const report = {pilots:data.userCardList.length, kmfs:data.userKnightmareFrameList.length, renderCases:html.length, resources};
fs.writeFileSync(path.join(root, 'render-report.json'), JSON.stringify(report, null, 2));
console.log(`Official formation templates rendered ${report.renderCases} cases (${report.pilots} pilots, ${report.kmfs} KMFs).`);
