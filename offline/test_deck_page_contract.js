"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
let page, dependencies, models;const calls=[];
const common={deckArr:[],linkList:{deckSave:'/api/deck/save',deckSaveList:'/api/deck/saveList'},
 storage:{userDeckList:{toJSON(){return [];}}},tapBlock(){},setResponseStorage(){}};
const ajax={pageModelGet(value){models=value;},ajaxPost(url,payload,done){calls.push({url,payload:JSON.parse(JSON.stringify(payload))});done({resultCode:'success'});}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'web_overrides/web/js/deck/DeckFormation.js'),'utf8'),{
 define(deps,factory){dependencies=deps;page=factory(common,ajax,{});},Backbone:{View:{extend(){return function(){};}}},
 _: {findWhere(rows,query){return rows.find(r=>Object.keys(query).every(k=>r[k]===query[k]));},isEqual(a,b){return JSON.stringify(a)===JSON.stringify(b);}},
 setTimeout(fn){fn();},console
});
for(const name of ['fetch','init','startCommand','removeCommand','remove','deckChangeCheck'])assert.equal(typeof page[name],'function');
assert.ok(dependencies.includes('js/view/deck/PilotListView'));
assert.ok(dependencies.includes('js/view/deck/KmfListView'));
page.fetch('quest');assert.ok(models.some(m=>m.id==='userKnightmareFrameCustomizeList'));
common.deckArr=[{deckType:'MAIN1',userCardId1:'pilot-a',userKnightmareFrameId1:'kmf-a'},
 {deckType:'MAIN2',userCardId1:'pilot-b',userKnightmareFrameId1:'kmf-b'}];
let finished=0;page.deckChangeCheck(()=>finished++);
assert.equal(finished,1);assert.equal(calls[0].url,'/api/deck/saveList');
assert.deepEqual(calls[0].payload.userDeckInfoList,[{deckType:'MAIN1',userCardIdList:['pilot-a'],userKnightmareFrameIdList:['kmf-a']},{deckType:'MAIN2',userCardIdList:['pilot-b'],userKnightmareFrameIdList:['kmf-b']}]);
common.deckArr=[{deckType:'MAIN1'}];page.deckChangeCheck(()=>finished++);
assert.equal(calls[1].url,'/api/deck/save');assert.deepEqual(calls[1].payload.userCardIdList,[]);
console.log('Original formation AMD contract, batch-save and clear request formats: PASS');
