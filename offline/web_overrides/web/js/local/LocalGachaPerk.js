define([
  "backboneCommon",
  "js/view/gacha/GachaBtnView"
], function (common, GachaBtnView) {
  "use strict";

  var PERK_ITEM_ID = "LOCAL_UNLIMITED_TEN_PULL";
  var installed = false;

  function perkEnabled() {
    var row = common.storage.userItemList &&
      common.storage.userItemList.findWhere({itemId: PERK_ITEM_ID});
    return !!row && Number(row.toJSON().quantity) > 0;
  }

  function tenDrawKind(view, event) {
    if (!event || !event.currentTarget || !view.model) return null;
    var gachaKindId = Number(
      event.currentTarget.dataset && event.currentTarget.dataset.gachaNum);
    return (view.model.gachaKindList || []).find(function (kind) {
      return Number(kind.gachaKindId) === gachaKindId &&
        String(kind.beanKind || "").indexOf("10") !== -1;
    }) || null;
  }

  function localUnlimitedTenDraw(kind) {
    return !!kind && kind.localUnlimitedTenPull === true &&
      String(kind.beanKind || "").indexOf("10") !== -1;
  }

  function isTenDrawKind(kind) {
    return !!kind && String(kind.beanKind || "").indexOf("10") !== -1;
  }

  function markFreeLabels(view) {
    if (!perkEnabled() || !view || !view.el ||
        !view.el.querySelectorAll || !view.model) return;
    var buttons = view.el.querySelectorAll(".gachaBtn");
    Array.prototype.forEach.call(buttons, function (button) {
      var gachaKindId = Number(button.dataset && button.dataset.gachaNum);
      var kind = (view.model.gachaKindList || []).find(function (entry) {
        return Number(entry.gachaKindId) === gachaKindId;
      });
      if (!isTenDrawKind(kind)) return;
      var label = button.querySelector(".itemNum.free");
      if (label) label.textContent = "10回無料";
    });
  }

  function correctPopupLabel(kind, forceFree) {
    if (!perkEnabled() || (!forceFree && !localUnlimitedTenDraw(kind)) ||
        !common.doc || !common.doc.querySelector) return;
    var text = common.doc.querySelector(
      "#popupArea .popupTextArea .text");
    if (!text) return;
    text.innerHTML = "無料で10回スカウトをします。<br>よろしいですか？";
  }

  function install() {
    if (installed) return;
    installed = true;
    var originalRender = GachaBtnView.prototype.render;
    GachaBtnView.prototype.render = function () {
      var result = originalRender.apply(this, arguments);
      markFreeLabels(this);
      return result;
    };
    var wrappedPopup = GachaBtnView.prototype.gachaPopup;
    GachaBtnView.prototype.gachaPopup = function (event) {
      var kind = tenDrawKind(this, event);
      if (!kind || !perkEnabled()) return wrappedPopup.call(this, event);

      var target = event.currentTarget;
      var wasGray = target.classList.contains("grayBtn");
      var root = this.rootView;
      var oldMoney = root.money;
      var oldFreeMoney = root.freeMoney;
      if (wasGray) target.classList.remove("grayBtn");
      root.money = 0;
      root.freeMoney = 0;
      var oldNeedPointKind = kind.needPointKind;
      var oldNeedQuantity = kind.needQuantity;
      kind.needPointKind = "FREE";
      kind.needQuantity = 0;
      var result;
      try {
        result = wrappedPopup.call(this, event);
        correctPopupLabel(kind, true);
      } finally {
        kind.needPointKind = oldNeedPointKind;
        kind.needQuantity = oldNeedQuantity;
        root.money = oldMoney;
        root.freeMoney = oldFreeMoney;
        if (wasGray) target.classList.add("grayBtn");
      }
      return result;
    };
  }

  return {install: install, perkEnabled: perkEnabled};
});
