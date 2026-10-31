// DOM fixture only: never connects to the desktop, game, or formal save.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
let exported, completion, change, popup, post;
const body = {children:[],appendChild(e){this.children.push(e);e.parentNode=this;},
  removeChild(e){this.children=this.children.filter(c=>c!==e);e.parentNode=null;}};
const common = {isScrolled:()=>false,PopupClass:function(value){popup=value;},setResponseStorage:r=>{common.response=r;}};
const ajax = {ajaxPost:(url,data,callback)=>{post={url,data,callback};}};
const context = {define:(_,factory)=>{exported=factory(common,ajax);},location:{hash:'#/DeckFormation'},
  document:{body,createElement:()=>({style:{},addEventListener(name,fn){this[name]=fn;}})},
  window:{addEventListener:(_,fn)=>{change=fn;}}, $:()=>({ajaxComplete:fn=>{completion=fn;}})};
vm.runInNewContext(fs.readFileSync(__dirname+'/web_overrides/web/js/local/LocalBattleRecovery.js','utf8'),context);
exported.install();
completion(null,{status:200,responseJSON:{localActiveBattle:{userQuestResultId:'owned-battle',returnStaminaOnFail:5}}},{url:'/api/page/DeckFormation'});
assert.equal(body.children.length,1);
assert.equal(post,undefined);
body.children[0].click();
assert.equal(post,undefined); // Confirmation itself must not mutate a save.
popup.decideBtnEvent({preventDefault(){}});
assert.equal(post.url,'/api/local/battle/retire');
assert.equal(post.data.userQuestResultId,'owned-battle');
post.callback({resultCode:'success',userStatusList:[]});
assert.equal(body.children.length,0);
context.location.hash='#/QuestBackground';
exported.render({userQuestResultId:'owned-battle',returnStaminaOnFail:5});
assert.equal(body.children.length,0);
change();
let arrived=0;
common.tapBlock=v=>{common.blocked=v;};
common.loading={hide:()=>{common.loadingHidden=true;}};
common.ready={hide(){},show(){}};
common.pageTransition=v=>{common.route=v;};
ajax.ajaxPost('/api/battle/skip',{questId:512001},()=>{arrived++;},true);
post.callback({resultCode:'error',title:'No tickets',errorTxt:'Not enough tickets'});
assert.equal(arrived,0);
assert.equal(common.isBattleSkip,false);
assert.equal(common.blocked,false);
assert.equal(common.loadingHidden,true);
popup.closeEvent();
assert.equal(common.route,'#/DailyQuestTop');
common.allSkipResponse=[{resultCode:'success'}];
post.callback({resultCode:'error',title:'Limit',errorTxt:'Limit reached'});
assert.match(popup.content,/1回分/);
post.callback({resultCode:'success',battleResult:{rewardList:[]}});
assert.equal(arrived,1);
console.log('Local battle recovery, skip errors, partial success and route lifecycle passed');
