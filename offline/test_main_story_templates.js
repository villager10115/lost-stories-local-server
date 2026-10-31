"use strict";
// Render the retained official templates with the entire candidate page model.
// No browser, native bridge, network, or player database is involved.
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const [underscorePath, templatePath, payloadPath, reportPath] = process.argv.slice(2);
const context = {console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(underscorePath, "utf8"), context);
const underscore = context._;
const payload = JSON.parse(fs.readFileSync(payloadPath, "utf8"));
const shell = underscore.template(fs.readFileSync(templatePath, "utf8"))({first:"story", selectPartId:6});
const chapterSource = shell.match(/<script id="chapterTemp"[^>]*>([\s\S]*?)<\/script>/)[1];
const render = underscore.template(chapterSource);
const rows = [], images = new Set();
for (const chapter of payload.userChapterList) {
  for (const type of ["_s", "_b", "_e"]) {
    const stories = payload.userQuestList.filter(row => row.quest.chapterId === chapter.chapterId &&
      (type === "_s" ? row.quest.onlyStory : !row.quest.onlyStory &&
        (type === "_e" ? row.quest.difficulty === "EXTRA" : row.quest.difficulty !== "EXTRA")));
    const html = render({chapter, stories, type, clearCount:0, allBattleClear:false, allS:false,
      allCount: type === "_s" ? chapter.chapter.storyNum : 3 * (type === "_b" ?
        chapter.chapter.battleNum : chapter.chapter.extraBattleNum || 0),
      today:Date.parse(payload.currentTime), isApHalf:false});
    assert.ok(!/\bundefined\b|\bNaN\b/.test(html), `Invalid rendered data: ${chapter.chapterId}/${type}`);
    const rendered = [...html.matchAll(/class="storyCol[^>]+data-battle-id="(\d+)"/g)].length;
    const scheduled = stories.length === 1 && type === "_e" &&
      Date.parse(stories[0].quest.schedule.startDate) > Date.parse(payload.currentTime);
    assert.equal(rendered, scheduled ? 0 : stories.length, `${chapter.chapterId}/${type}`);
    for (const match of html.matchAll(/<img src="([^"]+)"/g)) images.add("/web/" + match[1]);
    rows.push({chapterId:chapter.chapterId,type,definitions:stories.length,rendered,scheduled});
  }
}
assert.equal(rows.length, 150);
assert.equal(payload.userQuestList.length, 1640);
fs.writeFileSync(reportPath, JSON.stringify({chapters:50,modeLists:150,questDefinitions:1640,
  renderedNodes:rows.reduce((n,r)=>n+r.rendered,0),rows,images:[...images]},null,2));
console.log("Official chapter templates: 50 chapters / 150 mode lists rendered without missing fields.");
