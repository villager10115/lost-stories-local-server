define([
  "backboneCommon",
  "ajaxControl",
  "command",
  "js/local/LocalKmfStrength"
], function (common, ajax, command, kmfStrength) {
  "use strict";

  var cssText = [
    "#localEnhancementPage{position:absolute;left:0;top:0;width:1920px;height:930px;color:#fff;background:rgba(10,8,22,.72);}",
    "#localEnhancementPage .leHeader{height:88px;display:flex;align-items:center;justify-content:space-between;padding:0 42px;border-bottom:2px solid rgba(197,166,255,.35);}",
    "#localEnhancementPage .leTitle{font-size:38px;color:#f0ccff;letter-spacing:2px;}",
    "#localEnhancementPage .leSummary{display:flex;align-items:center;gap:18px;font-size:22px;color:#cfc5e8;}",
    "#localEnhancementPage .leLegend{display:flex;align-items:center;gap:5px;}",
    "#localEnhancementPage .leLegendDot{display:block;width:18px;height:18px;border:2px solid var(--strength-color);background:var(--strength-fill);border-radius:3px;}",
    "#localEnhancementPage .leList{padding:26px 42px;height:770px;overflow:auto;}",
    "#localEnhancementPage .leRow{position:relative;display:grid;grid-template-columns:80px minmax(300px,1fr) 300px 300px;align-items:center;gap:22px;min-height:92px;border-bottom:1px solid rgba(255,255,255,.12);border-left:6px solid var(--strength-color);padding:8px 18px;}",
    "#localEnhancementPage .leRow[data-strength-tier=\"1\"],#localEnhancementPage .leLegendDot[data-strength-tier=\"1\"]{--strength-color:#8490a3;--strength-fill:rgba(132,144,163,.22);}",
    "#localEnhancementPage .leRow[data-strength-tier=\"2\"],#localEnhancementPage .leLegendDot[data-strength-tier=\"2\"]{--strength-color:#67a0ce;--strength-fill:rgba(103,160,206,.22);}",
    "#localEnhancementPage .leRow[data-strength-tier=\"3\"],#localEnhancementPage .leLegendDot[data-strength-tier=\"3\"]{--strength-color:#62b49a;--strength-fill:rgba(98,180,154,.22);}",
    "#localEnhancementPage .leRow[data-strength-tier=\"4\"],#localEnhancementPage .leLegendDot[data-strength-tier=\"4\"]{--strength-color:#c6a353;--strength-fill:rgba(198,163,83,.24);}",
    "#localEnhancementPage .leRow[data-strength-tier=\"5\"],#localEnhancementPage .leLegendDot[data-strength-tier=\"5\"]{--strength-color:#d27770;--strength-fill:rgba(210,119,112,.24);}",
    "#localEnhancementPage .leRow[data-strength-tier=\"0\"]{--strength-color:rgba(151,143,165,.35);}",
    "#localEnhancementPage .leIndex{font-size:24px;color:#b99adf;text-align:center;}",
    "#localEnhancementPage .leName{font-size:27px;}",
    "#localEnhancementPage .leMeta{display:flex;align-items:center;gap:14px;font-size:19px;color:#c7badb;}",
    "#localEnhancementPage .leStrength{display:inline-flex;align-items:center;gap:8px;min-width:108px;height:38px;padding:0 12px;border:1px solid var(--strength-color);background:var(--strength-fill);color:var(--strength-color);font-size:17px;}",
    "#localEnhancementPage .leStrength b{font-size:23px;color:#fff;font-variant-numeric:tabular-nums;}",
    "#localEnhancementPage .leAction{display:flex;justify-content:flex-end;align-items:center;gap:14px;}",
    "#localEnhancementPage .leBtn{min-width:150px;height:52px;line-height:52px;text-align:center;font-size:21px;border-radius:4px;background:#5c347f;color:#fff;}",
    "#localEnhancementPage .leBtn.gray{background:#493d57;color:#91869c;}",
    "#localEnhancementPage .leColor{width:64px;height:42px;border:0;background:none;}",
    "#localEnhancementPage .leEmpty{font-size:25px;color:#b7abc7;text-align:center;padding-top:180px;}",
    "#localEnhancementPage .leBack{padding:10px 34px;background:#5c347f;font-size:22px;border-radius:3px;}",
    "#localEnhancementPage .leNotice{font-size:19px;color:#bfb2cf;margin:0 42px 8px;}"
  ].join("");

  var needModels = [
    {id: "user"},
    {id: "gameUser"},
    {id: "userKnightmareFrameList"},
    {id: "userKnightmareFrameCustomizeList"},
    {id: "knightmareFrameList"},
    {id: "knightmareFrameCustomizeList"},
    {id: "itemList"},
    {id: "userItemList"}
  ];

  var titles = {
    development: "KMF開発",
    dismantle: "KMF分解",
    coloring: "KMFカラー変更",
    carryingIn: "KMF格納",
    carryingOut: "KMF取出"
  };

  var notices = {
    development: "保存済みの開発状況を表示します。未受領の開発がある場合のみ受領できます。",
    dismantle: "同名KMFが2機以上ある場合のみ分解できます。",
    coloring: "機体色はローカル保存され、次回起動後も維持されます。",
    carryingIn: "機体を倉庫へ格納します。",
    carryingOut: "倉庫から機体を取り出します。"
  };

  function post(path, payload) {
    return fetch(path, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Web-Session-Id": String(Date.now())
      },
      body: JSON.stringify(payload)
    }).then(function (response) {
      if (!response.ok) throw new Error("request " + response.status);
      return response.json();
    });
  }

  var Page = Backbone.View.extend({
    id: "localEnhancementPage",

    initialize: function (options) {
      this.mode = options.mode;
    },

    render: function () {
      var self = this;
      var definitions = {};
      if (common.storage.knightmareFrameList) {
        common.storage.knightmareFrameList.each(function (model) {
          var row = model.toJSON();
          definitions[row.knightmareFrameId] = row;
        });
      }
      var kmfs = common.storage.userKnightmareFrameList
        ? common.storage.userKnightmareFrameList.toJSON() : [];
      var customizations = common.storage.userKnightmareFrameCustomizeList
        ? common.storage.userKnightmareFrameCustomizeList.toJSON() : [];
      var strengthRows = kmfStrength.decorate(kmfs, customizations);
      var rows = kmfs.map(function (kmf, index) {
        var definition = definitions[kmf.knightmareFrameId] || {};
        var color = "#" + [kmf.customColorR, kmf.customColorG, kmf.customColorB]
          .map(function (value) {
            var n = Math.max(0, Math.min(255, Number(value || 150)));
            return ("0" + n.toString(16)).slice(-2);
          }).join("");
        var action = "";
        var strengthInfo = strengthRows[index] || {strength: null, tier: 0};
        var strength = strengthInfo.strength === null
          ? "-" : String(strengthInfo.strength);
        if (self.mode === "coloring") {
          action = '<input class="leColor" type="color" value="' + color +
            '" data-kmf="' + kmf.userKnightmareFrameId +
            '"><div class="leBtn se_decide" data-kmf="' +
            kmf.userKnightmareFrameId + '">保存</div>';
        } else if (self.mode === "carryingIn" ||
                   self.mode === "carryingOut") {
          var target = self.mode === "carryingIn";
          var current = !!kmf.isInStorage;
          action = current === target
            ? '<div class="leBtn gray">移動済み</div>'
            : '<div class="leBtn se_decide" data-kmf="' +
              kmf.userKnightmareFrameId + '" data-target="' + target +
              '">' + (target ? "格納" : "取出") + "</div>";
        } else if (self.mode === "dismantle") {
          var duplicates = kmfs.filter(function (row) {
            return row.knightmareFrameId === kmf.knightmareFrameId;
          }).length;
          action = '<div class="leBtn ' + (duplicates > 1 ? "" : "gray") +
            '">' + (duplicates > 1 ? "分解準備" : "分解対象外") + "</div>";
        } else {
          action = '<div class="leBtn gray">所持済み</div>';
        }
        return '<div class="leRow" data-strength-tier="' +
          strengthInfo.tier + '"><div class="leIndex">' + (index + 1) +
          '</div><div class="leName">' +
          _.escape(definition.name || ("KMF " + kmf.knightmareFrameId)) +
          '</div><div class="leMeta"><span>' +
          (kmf.isInStorage ? "倉庫" : "所持中") +
          " / 改造 " + Number(kmf.revision || 0) +
          '</span><span class="leStrength tier-' + strengthInfo.tier +
          '">戦力<b>' + strength + "</b></span></div>" +
          '<div class="leAction">' + action + "</div></div>";
      }).join("");
      var legend = "";
      for (var tier = 1; tier <= 5; tier++) {
        legend += '<span class="leLegendDot" data-strength-tier="' + tier +
          '" title="' + ["", "低", "やや低", "標準", "高", "最高"][tier] +
          '"></span>';
      }
      this.$el.html(
        '<div class="leHeader"><div class="leTitle">' + titles[this.mode] +
        '</div><div class="leSummary"><span>' + kmfs.length +
        ' 機</span><span class="leLegend">' + legend + "</span></div>" +
        '<div class="leBack se_cancel">強化へ戻る</div></div>' +
        '<p class="leNotice">' + notices[this.mode] + "</p>" +
        '<div class="leList">' + (rows ||
          '<div class="leEmpty">表示できるKMFがありません。</div>') +
        "</div>");
      common.content.append(this.el);
      this.$el.on(common.cgti + " .leBack", this.back);
      this.$el.on(common.cgti + " .leBtn[data-kmf]", this.act);
      return this;
    },

    back: function (event) {
      event.preventDefault();
      common.pageTransition("#/ComposeTop");
    },

    act: function (event) {
      event.preventDefault();
      if (event.currentTarget.classList.contains("gray")) return;
      var id = event.currentTarget.dataset.kmf;
      var target = this.mode === "coloring"
        ? post("/api/knightmareFrame/color", {
            userKnightmareFrameId: id,
            customColorR: parseInt(this.$el.find(
              '.leColor[data-kmf="' + id + '"]').val().slice(1, 3), 16),
            customColorG: parseInt(this.$el.find(
              '.leColor[data-kmf="' + id + '"]').val().slice(3, 5), 16),
            customColorB: parseInt(this.$el.find(
              '.leColor[data-kmf="' + id + '"]').val().slice(5, 7), 16)
          })
        : post("/api/local/kmf/storage", {
            userKmfId: id,
            isInStorage: event.currentTarget.dataset.target === "true"
          });
      var self = this;
      common.tapBlock(true);
      target.then(function (payload) {
        if (common.setResponseStorage) common.setResponseStorage(payload);
        common.tapBlock(false);
        common.OverlapInfomation("保存しました。");
        self.remove();
        self.render();
      }).catch(function () {
        common.tapBlock(false);
        common.OverlapInfomation("保存に失敗しました。");
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
        common.setGlobalContents({pageTitle: "composeTop"});
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
