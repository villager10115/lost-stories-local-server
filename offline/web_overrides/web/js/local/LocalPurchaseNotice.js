define(["backboneCommon"], function (common) {
  "use strict";

  var SHOP_ID = 99001;
  var SHOP_ITEM_ID = 990001;

  function sessionId() {
    return String(Date.now());
  }

  function setItem(collection, itemId, quantity) {
    if (!collection) return;
    var row = collection.findWhere({itemId: itemId});
    if (row) {
      row.set({quantity: quantity});
    } else if (typeof collection.add === "function") {
      collection.add({
        itemId: itemId,
        environmentId: "COMMON",
        quantity: quantity,
        total: 0,
        createdAt: new Date().toISOString()
      });
    }
  }

  function applyPurchase(payload) {
    var quantities = {};
    (payload.userItemList || []).forEach(function (item) {
      if (item && item.itemId !== undefined) {
        quantities[item.itemId] = Number(item.quantity) || 0;
      }
    });
    setItem(common.storage.userItemList, "MONEY", quantities.MONEY || 0);
    setItem(
      common.storage.userItemList,
      "PRESENTED_MONEY",
      quantities.PRESENTED_MONEY || 0
    );
    if (common.storage.userShopItemList && payload.userShopItemList) {
      common.storage.userShopItemList.set(payload.userShopItemList);
    }
    if (typeof common.setPlayerPaidStone === "function") {
      common.setPlayerPaidStone();
    }
    if (common.globalHeaderView &&
        typeof common.globalHeaderView.changeItem === "function") {
      common.globalHeaderView.changeItem();
    }
  }

  function showFailure() {
    new common.PopupClass({
      title: "サクラダイト補給",
      content: "無料サクラダイトの補給に失敗しました。<br>通信状態を確認してください。",
      closeBtnText: "閉じる",
      canClose: true
    });
  }

  function requestPurchase(success, failure) {
    var body = JSON.stringify({
      shopId: SHOP_ID,
      shopItemId: SHOP_ITEM_ID,
      num: 1
    });

    if (typeof XMLHttpRequest === "function") {
      var request = new XMLHttpRequest();
      request.open("POST", "/api/shop/buy", true);
      request.setRequestHeader("Content-Type", "application/json");
      request.setRequestHeader("X-Web-Session-Id", sessionId());
      request.onreadystatechange = function () {
        if (request.readyState !== 4) return;
        if (request.status < 200 || request.status >= 300) {
          failure();
          return;
        }
        try {
          success(JSON.parse(request.responseText));
        } catch (_) {
          failure();
        }
      };
      request.onerror = failure;
      request.send(body);
      return;
    }

    fetch("/api/shop/buy", {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Web-Session-Id": sessionId()
      },
      body: body
    }).then(function (response) {
      if (!response.ok) throw new Error("shop buy " + response.status);
      return response.json();
    }).then(success).catch(failure);
  }

  return function (event, onClose) {
    if (event) {
      event.preventDefault();
      if (common.isScrolled()) return;
    }
    common.tapBlock(true);
    requestPurchase(function (payload) {
      if (!payload || payload.resultCode !== "success") {
        common.tapBlock(false);
        showFailure();
        return;
      }
      applyPurchase(payload);
      common.tapBlock(false);
      if (typeof common.OverlapInfomation === "function") {
        common.OverlapInfomation("サクラダイト3,000個を補給しました。");
      }
      if (typeof onClose === "function") onClose();
    }, function () {
      common.tapBlock(false);
      showFailure();
    });
  };
});
