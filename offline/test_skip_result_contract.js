// Render the preserved official result template with copied-save HTTP output.
// No browser, native bridge, network, or game input is used.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path');
const [protocol, verification] = process.argv.slice(2);
const context = {console:{log(){}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(protocol,'underscore.js'),'utf8'),context);
const _ = context._;
const data = JSON.parse(fs.readFileSync(path.join(verification,'skip-result-model.json'),'utf8'));
const cards = new Map(data.after.cardList.map(c=>[c.cardId,c]));
const userCard = data.after.userCardList.map(c=>({...c,
  maxLevel:cards.get(c.cardId).rarity.maxCardLevelList[c.lbCount], displayCardId:c.cardId}));
const qid = data.formation.questId;
const render = _.template(fs.readFileSync(path.join(protocol,'QuestResult.html'),'utf8'));
const model = {
  battle:data.before.userQuestList.find(q=>q.questId===qid),
  start:{userCardList:data.before.userCardList.filter(c=>data.formation.userCardIdList.includes(c.userCardId))},
  after:data.response, afterQuest:data.after.userQuestList.find(q=>q.questId===qid),
  beforeUser:data.before.gameUser, isSkip:true, isTutorial:false, mvpCard:null,
  skipItemList:[data.response.battleResult.rewardList], userCard, questType:'daily',
  dailyPrm:{boost:false,bonus:false}, levelList:data.after.levelList,
  subsc:{active:false,expBonus:0}, skipBtnDisp:false, eventSkip:'canSkip', isNoMission:false
};
const html = render(model);
assert.match(html, /id='QuestResult' class='skipped'/);
assert.ok(!/\bundefined\b|\bNaN\b/.test(html), 'Unresolved result model');
assert.ok(!('battle' in data.response), 'Skip must not require a simulated native battle');
assert.match(html,/card_crystal_star_bronze/);
assert.match(html,/mvpDetailBtn[^>]+grayBtn/);
fs.writeFileSync(path.join(verification,'skip-result-template.html'),html);
console.log('Original skip result template rendered from copied-save HTTP output.');
