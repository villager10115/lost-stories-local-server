define([
  "backboneCommon",
  "ajaxControl",
  "command"
], function (common, ajax, command) {
  "use strict";

  var TITLES = {
    development: "KMF開発",
    dismantle: "KMF解体",
    carryIn: "KMF搬入",
    carryOut: "KMF搬出"
  };
  var PAGE_TITLES = {
    development: "development",
    dismantle: "dismantle",
    carryIn: "carryingin",
    carryOut: "carryingout"
  };
  var cssText = [
    "#localKmfLifecyclePage{position:absolute;left:0;top:0;width:1920px;height:930px;color:#fff;background:rgba(9,7,20,.88);}",
    "#localKmfLifecyclePage .lfHeader{height:86px;display:flex;align-items:center;justify-content:space-between;padding:0 42px;border-bottom:2px solid rgba(200,166,255,.32);}",
    "#localKmfLifecyclePage .lfTitle{font-size:36px;color:#f0ccff;letter-spacing:1px;}",
    "#localKmfLifecyclePage .lfSummary{display:flex;gap:26px;font-size:21px;color:#cfc5e8;}",
    "#localKmfLifecyclePage .lfCount b{font-size:27px;color:#fff;margin-left:8px;}",
    "#localKmfLifecyclePage .lfBack{min-width:190px;padding:11px 28px;text-align:center;background:#5c347f;font-size:21px;border-radius:3px;}",
    "#localKmfLifecyclePage .lfBody{padding:24px 42px;height:788px;overflow:auto;}",
    "#localKmfLifecyclePage .lfSectionTitle{font-size:24px;color:#e5d4ff;margin:4px 0 14px;}",
    "#localKmfLifecyclePage .lfLines{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:22px;}",
    "#localKmfLifecyclePage .lfLine{position:relative;min-height:122px;border:2px solid #47395c;background:rgba(49,35,67,.78);padding:18px 20px;border-radius:4px;}",
    "#localKmfLifecyclePage .lfLine.selected{border-color:#d9b0ff;background:rgba(92,52,127,.74);}",
    "#localKmfLifecyclePage .lfLineNo{font-size:18px;color:#bda5d4;}",
    "#localKmfLifecyclePage .lfLineName{font-size:25px;color:#fff;margin-top:7px;}",
    "#localKmfLifecyclePage .lfLineState{font-size:18px;color:#cfc2df;margin-top:8px;}",
    "#localKmfLifecyclePage .lfLineActions{display:flex;justify-content:flex-end;gap:10px;margin-top:-36px;}",
    "#localKmfLifecyclePage .lfButton{min-width:128px;height:46px;line-height:46px;padding:0 18px;text-align:center;font-size:19px;border-radius:4px;background:#6b3e91;color:#fff;}",
    "#localKmfLifecyclePage .lfButton.pink{background:#a84f82;}",
    "#localKmfLifecyclePage .lfButton.gray{background:#42394e;color:#8f849a;}",
    "#localKmfLifecyclePage .lfList{border-top:1px solid rgba(255,255,255,.16);}",
    "#localKmfLifecyclePage .lfRow{display:grid;grid-template-columns:54px minmax(360px,1fr) 330px 280px;align-items:center;gap:18px;min-height:82px;border-bottom:1px solid rgba(255,255,255,.12);padding:8px 14px;}",
    "#localKmfLifecyclePage .lfRow.disabled{opacity:.48;}",
    "#localKmfLifecyclePage .lfCheck{width:30px;height:30px;border:2px solid #9476b3;border-radius:3px;background:#221a2d;color:#f0ccff;font-size:24px;line-height:27px;text-align:center;}",
    "#localKmfLifecyclePage .lfCheck.on{background:#8756b2;}",
    "#localKmfLifecyclePage .lfCheck.disabled{border-color:#5e5667;background:#34303a;}",
    "#localKmfLifecyclePage .lfName{font-size:25px;}",
    "#localKmfLifecyclePage .lfMeta{font-size:18px;color:#c6b8d7;line-height:30px;}",
    "#localKmfLifecyclePage .lfBadge{display:inline-block;margin-right:8px;padding:2px 9px;border:1px solid #82659c;color:#d9c7ec;font-size:15px;}",
    "#localKmfLifecyclePage .lfCoreQuantity{font-size:25px;color:#f0ccff;text-align:right;font-variant-numeric:tabular-nums;}",
    "#localKmfLifecyclePage .lfCoreAction{display:flex;justify-content:flex-end;}",
    "#localKmfLifecyclePage .lfEmpty{padding:70px 20px;text-align:center;font-size:23px;color:#b8abc5;}",
    "#localKmfLifecyclePage .lfFooter{display:flex;align-items:center;justify-content:space-between;margin-top:18px;padding:12px 16px;background:rgba(36,25,51,.86);}",
    "#localKmfLifecyclePage .lfFooterText{font-size:21px;color:#d7cae4;}",
    "#localKmfLifecyclePage .lfNotice{font-size:18px;color:#c8bad5;margin:0 0 12px;}"
  ].join("");

  var needModels = [
    {id: "user"},
    {id: "gameUser"},
    {id: "itemList"},
    {id: "userItemList"},
    {id: "userStatusList"},
    {id: "backgroundGroupList"},
    {id: "knightmareFrameList"},
    {id: "knightmareFrameCustomizeList"},
    {id: "userKnightmareFrameList"},
    {id: "userKnightmareFrameCustomizeList"},
    {id: "userKnightmareFrameKeyList"},
    {id: "userKnightmareFrameDevelopmentList"},
    {id: "userDeckList"}
  ];

  function rows(name) {
    var collection = common.storage && common.storage[name];
    return collection ? collection.toJSON() : [];
  }

  function escapeHtml(value) {
    return _.escape(value === undefined || value === null ? "" : String(value));
  }

  function findRow(name, identity) {
    var collection = common.storage && common.storage[name];
    return collection ? collection.findWhere(identity) : null;
  }

  function setRows(name, incoming, identityKey) {
    if (!Array.isArray(incoming) || !common.storage[name]) return;
    var collection = common.storage[name];
    incoming.forEach(function (row) {
      if (!row || !row[identityKey]) return;
      var match = {};
      match[identityKey] = row[identityKey];
      var existing = collection.findWhere(match);
      if (existing) existing.set(row);
      else collection.add(row);
    });
  }

  function removeRows(name, incoming, identityKey) {
    if (!Array.isArray(incoming) || !common.storage[name]) return;
    var collection = common.storage[name];
    incoming.forEach(function (row) {
      var match = {};
      match[identityKey] = row[identityKey];
      var existing = collection.findWhere(match);
      if (existing) collection.remove(existing, {silent: true});
    });
  }

  function applyPayload(payload) {
    if (common.setResponseStorage) common.setResponseStorage(payload);
    setRows("userItemList", payload.userItemList, "itemId");
    setRows("userKnightmareFrameList", payload.userKnightmareFrameList,
      "userKnightmareFrameId");
    setRows("userKnightmareFrameCustomizeList",
      payload.userKnightmareFrameCustomizeList,
      "userKnightmareFrameCustomizeId");
    setRows("userKnightmareFrameKeyList",
      payload.userKnightmareFrameKeyList, "knightmareFrameId");
    setRows("userKnightmareFrameDevelopmentList",
      payload.userKnightmareFrameDevelopmentList, "frameNo");
    if (payload.deleted) {
      removeRows("userKnightmareFrameList",
        payload.deleted.userKnightmareFrameList, "userKnightmareFrameId");
      removeRows("userKnightmareFrameCustomizeList",
        payload.deleted.userKnightmareFrameCustomizeList,
        "userKnightmareFrameCustomizeId");
    }
  }

  function request(path, payload) {
    return fetch(path, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Web-Session-Id": String(Date.now())
      },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok || body.resultCode === "error") {
          throw new Error(body.errorTxt || ("request " + response.status));
        }
        return body;
      });
    });
  }

  function dateValue(value) {
    var stamp = Date.parse(value || "");
    return isFinite(stamp) ? stamp : 0;
  }

  function developmentStatus(row, now) {
    if (!row || row.receivedAt) return "blank";
    return now >= dateValue(row.endAt) ? "complete" : "doing";
  }

  function remainingText(row, now) {
    var seconds = Math.max(0, Math.ceil((dateValue(row.endAt) - now) / 1000));
    var hours = Math.floor(seconds / 3600);
    var minutes = Math.ceil((seconds % 3600) / 60);
    if (hours > 0) return hours + "時間" + minutes + "分";
    return Math.max(1, minutes) + "分";
  }

  function confirm(title, content, callback) {
    new common.PopupClass({
      title: title,
      content: content,
      closeBtnText: "キャンセル",
      decideBtnText: "OK",
      decideBtnEvent: function (event) {
        event.preventDefault();
        callback();
      }
    });
  }

  var Page = Backbone.View.extend({
    id: "localKmfLifecyclePage",

    initialize: function (options) {
      this.mode = options.mode;
      this.selectedLine = 1;
      this.selectedIds = {};
      this.currentTime = Date.now();
    },

    definitions: function () {
      var result = {};
      rows("knightmareFrameList").forEach(function (row) {
        result[row.knightmareFrameId] = row;
      });
      return result;
    },

    deckIds: function () {
      var result = {};
      rows("userDeckList").forEach(function (deck) {
        for (var index = 1; index <= 10; index++) {
          var id = deck["userKnightmareFrameId" + index];
          if (id) result[id] = true;
        }
      });
      return result;
    },

    render: function () {
      this.$el.off();
      this.$el.html(this.header() + '<div class="lfBody">' +
        (this.mode === "development" ?
          this.developmentBody() : this.unitBody()) + "</div>");
      common.content.append(this.el);
      this.$el.on(common.cgti + " .lfBack", this.back);
      this.$el.on(common.cgti + " .lfLine", this.selectLine);
      this.$el.on(common.cgti + " [data-development-action]",
        this.developmentAction);
      this.$el.on(common.cgti + " [data-start-development]",
        this.startDevelopment);
      this.$el.on(common.cgti + " .lfCheck", this.toggleSelection);
      this.$el.on(common.cgti + " .lfSubmit", this.submitUnits);
      return this;
    },

    header: function () {
      var kmfs = rows("userKnightmareFrameList");
      var stored = kmfs.filter(function (row) {
        return !!(row && row.isInStorage);
      }).length;
      var keys = rows("userKnightmareFrameKeyList").filter(function (row) {
        return row && Number(row.quantity) > 0;
      }).length;
      var summary = this.mode === "development"
        ? '<span class="lfCount">コア <b>' + keys +
          '</b></span><span class="lfCount">開発中 <b>' +
          rows("userKnightmareFrameDevelopmentList").filter(function (row) {
            return developmentStatus(row, Date.now()) === "doing";
          }).length + "</b></span>"
        : '<span class="lfCount">所持 <b>' +
          (kmfs.length - stored) + '</b></span><span class="lfCount">倉庫 <b>' +
          stored + "</b></span>";
      return '<div class="lfHeader"><div class="lfTitle">' +
        TITLES[this.mode] + '</div><div class="lfSummary">' + summary +
        '</div><div class="lfBack se_cancel">強化へ戻る</div></div>';
    },

    developmentBody: function () {
      var definitions = this.definitions();
      var keys = rows("userKnightmareFrameKeyList");
      var developments = rows("userKnightmareFrameDevelopmentList");
      var now = Date.now();
      var byLine = {};
      developments.forEach(function (row) {
        if (row && row.frameNo) byLine[row.frameNo] = row;
      });
      var cards = "";
      for (var line = 1; line <= 3; line++) {
        var development = byLine[line];
        var status = developmentStatus(development, now);
        var definition = development ?
          definitions[development.knightmareFrameId] : null;
        var name = status === "blank" ? "空きライン" :
          ((definition && definition.name) || ("KMF " +
            development.knightmareFrameId));
        var state = status === "blank" ? "開発するKMFを選択" :
          status === "complete" ? "開発完了" :
            "残り " + remainingText(development, now);
        var actions = "";
        if (status === "doing") {
          actions = '<div class="lfButton pink" data-development-action="skip">即時完了</div>';
        } else if (status === "complete") {
          actions = '<div class="lfButton pink" data-development-action="receive">受取</div>';
        }
        cards += '<div class="lfLine' +
          (this.selectedLine === line ? " selected" : "") +
          '" data-line="' + line + '"><div class="lfLineNo">開発ライン ' +
          line + '</div><div class="lfLineName">' + escapeHtml(name) +
          '</div><div class="lfLineState">' + escapeHtml(state) +
          '</div><div class="lfLineActions">' + actions + "</div></div>";
      }
      var current = byLine[this.selectedLine];
      var currentStatus = developmentStatus(current, now);
      var coreRows = "";
      if (currentStatus === "blank") {
        var self = this;
        keys.forEach(function (key) {
          var quantity = Number(key.quantity || 0);
          if (quantity <= 0) return;
          var definition = definitions[key.knightmareFrameId] || {};
          var tier = definition.knightmareFrameTier || {};
          coreRows += '<div class="lfRow"><div></div><div class="lfName">' +
            escapeHtml(definition.name || ("KMF " + key.knightmareFrameId)) +
            '</div><div class="lfMeta">必要 ギアスコイン ' +
            Number(tier.needGold || 0).toLocaleString() + '<br>所要 ' +
            Math.max(1, Math.ceil(Number(tier.needMinutes || 0) / 60)) +
            '時間</div><div class="lfCoreAction"><div class="lfButton" ' +
            'data-start-development="' + key.knightmareFrameId +
            '">開発開始</div></div></div>';
        });
      }
      return '<p class="lfNotice">コアとギアスコインを消費して、最大3ラインまで同時開発できます。</p>' +
        '<div class="lfLines">' + cards + '</div>' +
        '<div class="lfSectionTitle">固有コアルミナス</div>' +
        '<div class="lfList">' + (coreRows ||
          '<div class="lfEmpty">' +
          (currentStatus === "blank" ? "開発可能なコアがありません。" :
            "この開発ラインは使用中です。") + "</div>") + "</div>";
    },

    unitRows: function (isDismantle) {
      var definitions = this.definitions();
      var deckIds = this.deckIds();
      var units = rows("userKnightmareFrameList");
      var self = this;
      var output = "";
      units.forEach(function (unit) {
        if (!unit) return;
        if (!isDismantle) {
          var target = self.mode === "carryIn";
          if (!!unit.isInStorage === target) return;
        }
        var definition = definitions[unit.knightmareFrameId] || {};
        var blocked = isDismantle && (unit.protection || unit.first);
        var checked = !!self.selectedIds[unit.userKnightmareFrameId];
        var badges = [];
        badges.push(unit.isInStorage ? "倉庫" : "所持中");
        if (deckIds[unit.userKnightmareFrameId]) badges.push("編成中");
        if (unit.protection) badges.push("保護");
        if (unit.first) badges.push("初期配布");
        if (unit.useCustomColor) badges.push("カラー済");
        output += '<div class="lfRow' + (blocked ? " disabled" : "") +
          '"><div class="lfCheck' + (checked ? " on" : "") +
          (blocked ? " disabled" : "") + '" data-kmf="' +
          escapeHtml(unit.userKnightmareFrameId) + '">' +
          (checked ? "✓" : "") + '</div><div class="lfName">' +
          escapeHtml(definition.name || ("KMF " + unit.knightmareFrameId)) +
          '</div><div class="lfMeta">' +
          badges.map(function (badge) {
            return '<span class="lfBadge">' + escapeHtml(badge) +
              "</span>";
          }).join("") + '<br>改造 ' + Number(unit.revision || 0) +
          '</div><div class="lfCoreQuantity">1コア</div></div>';
      });
      return output;
    },

    unitBody: function () {
      var isDismantle = this.mode === "dismantle";
      var unitRows = this.unitRows(isDismantle);
      var count = Object.keys(this.selectedIds).length;
      var action = isDismantle ? "解体" :
        (this.mode === "carryIn" ? "搬入" : "搬出");
      return '<p class="lfNotice">' +
        (isDismantle
          ? "選択したKMFを解体し、同名KMFの固有コアルミナスに変換します。"
          : "倉庫との搬入・搬出を最大100機までまとめて行えます。") +
        '</p><div class="lfList">' + (unitRows ||
          '<div class="lfEmpty">表示できるKMFがありません。</div>') +
        '</div><div class="lfFooter"><div class="lfFooterText">選択中 <b>' +
        count + '</b> 機</div><div class="lfButton' +
        (count ? "" : " gray") + ' lfSubmit">' + action + "</div></div>";
    },

    back: function (event) {
      event.preventDefault();
      common.pageTransition("#/ComposeTop");
    },

    selectLine: function (event) {
      event.preventDefault();
      var line = Number(event.currentTarget.dataset.line || 0);
      if (line < 1 || line > 3 || line === this.selectedLine) return;
      this.selectedLine = line;
      this.render();
    },

    startDevelopment: function (event) {
      event.preventDefault();
      event.stopPropagation();
      var frameId = Number(event.currentTarget.dataset.startDevelopment);
      var definitions = this.definitions();
      var definition = definitions[frameId] || {};
      var tier = definition.knightmareFrameTier || {};
      var message = escapeHtml(definition.name || ("KMF " + frameId)) +
        "を開発します。<br>ギアスコイン " +
        Number(tier.needGold || 0).toLocaleString() + " / コア 1";
      var self = this;
      confirm("KMF開発", message, function () {
        self.perform("/api/knightmareFrame/development/start", {
          frameNo: self.selectedLine,
          knightmareFrameId: frameId
        }, "開発を開始しました。");
      });
    },

    developmentAction: function (event) {
      event.preventDefault();
      event.stopPropagation();
      var action = event.currentTarget.dataset.developmentAction;
      var path = action === "skip" ?
        "/api/knightmareFrame/development/skip" :
        "/api/knightmareFrame/development/receive";
      var self = this;
      confirm("KMF開発", action === "skip" ?
        "サクラダイトを消費して開発を即時完了します。" :
        "完成したKMFを受け取ります。", function () {
          self.perform(path, {frameNo: self.selectedLine},
            action === "skip" ? "開発を完了しました。" : "KMFを受け取りました。");
        });
    },

    toggleSelection: function (event) {
      event.preventDefault();
      if (event.currentTarget.classList.contains("disabled")) return;
      var id = event.currentTarget.dataset.kmf;
      if (!id) return;
      if (this.selectedIds[id]) delete this.selectedIds[id];
      else {
        if (Object.keys(this.selectedIds).length >= 100) {
          common.OverlapInfomation("一度に選択できるKMFは100機までです。");
          return;
        }
        this.selectedIds[id] = true;
      }
      this.render();
    },

    submitUnits: function (event) {
      event.preventDefault();
      var ids = Object.keys(this.selectedIds);
      if (!ids.length) return;
      var path = this.mode === "dismantle" ?
        "/api/knightmareFrame/dismantle" :
        (this.mode === "carryIn" ?
          "/api/knightmareFrame/carryIn" :
          "/api/knightmareFrame/carryOut");
      var verb = this.mode === "dismantle" ? "解体" :
        (this.mode === "carryIn" ? "搬入" : "搬出");
      var self = this;
      confirm(TITLES[this.mode], "選択中のKMF " + ids.length +
        "機を" + verb + "します。", function () {
          self.perform(path, {
            userKnightmareFrameIdList: ids
          }, verb + "しました。", true);
        });
    },

    perform: function (path, payload, message, clearSelection) {
      var self = this;
      common.tapBlock(true);
      request(path, payload).then(function (body) {
        applyPayload(body);
        if (body.currentTime) self.currentTime = dateValue(body.currentTime);
        if (clearSelection) self.selectedIds = {};
        common.tapBlock(false);
        common.OverlapInfomation(message);
        self.render();
      }).catch(function (error) {
        common.tapBlock(false);
        common.OverlapInfomation(error.message || "処理に失敗しました。");
      });
    },

    remove: function () {
      this.$el.off();
      this.$el.remove();
    }
  });

  function create(modeResolver) {
    var view = null;
    var requestedMode = null;
    return {
      needModelIdObj: needModels,
      fetch: function (mode) {
        requestedMode = mode || null;
        ajax.pageModelGet(needModels);
      },
      init: function () {
        var mode = modeResolver(requestedMode);
        common.setStyle(cssText);
        common.setGlobalContents({pageTitle: PAGE_TITLES[mode]});
        view = new Page({mode: mode});
        view.render();
        common.ready.hide();
      },
      startCommand: function () {
        common.bgmChange("Common/Bgm_Cmn_02");
      },
      removeCommand: function () {
        command.releaseLive2d();
      },
      remove: function (callback) {
        if (view) view.remove();
        view = null;
        if (callback) callback();
      }
    };
  }

  return {create: create};
});
