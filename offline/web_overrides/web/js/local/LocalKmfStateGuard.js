define(["backboneCommon"], function (common) {
  "use strict";

  var state = window.__localKmfStateGuard = window.__localKmfStateGuard || {
    installed: false,
    processed: 0,
    skippedCustomizations: 0,
    lastCalculatedStrength: null
  };

  function isFiniteNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function setUserKnightmareFrameModel(model) {
    if (!common.storage.knightmareFrameList ||
        !common.storage.knightmareFrameCustomizeList ||
        !common.storage.userKnightmareFrameCustomizeList) {
      return;
    }

    var knightmareFrame = common.storage.knightmareFrameList.findWhere({
      knightmareFrameId: model.get("knightmareFrameId")
    });
    if (!knightmareFrame) return;

    var customizations = common.storage.knightmareFrameCustomizeList.where({
      knightmareFrameId: model.get("knightmareFrameId")
    });
    if (!customizations || !customizations.length) return;

    customizations = customizations.slice().sort(function (left, right) {
      return Number(left.get("sortKey")) - Number(right.get("sortKey"));
    });

    var weapons = [];
    for (var index = 0; index < customizations.length; index++) {
      var customization = customizations[index];
      var owned = common.storage.userKnightmareFrameCustomizeList.findWhere({
        userKnightmareFrameId: model.get("userKnightmareFrameId"),
        knightmareFrameCustomizeId:
          customization.get("knightmareFrameCustomizeId")
      });
      if (!owned) {
        state.skippedCustomizations += 1;
        continue;
      }
      var weapon = owned.toJSON();
      weapon.weapon = customization.toJSON();
      weapons.push(weapon);
    }

    state.processed += 1;
    model.set({
      knightmareFrame: knightmareFrame.toJSON(),
      weaponList: weapons
    }, {silent: true});
  }

  function getPlayerStrength() {
    var total = 0;
    if (!common.storage.userCardList ||
        !common.storage.userKnightmareFrameList) {
      state.lastCalculatedStrength = total;
      return total;
    }

    var cards = common.storage.userCardList.toJSON();
    for (var cardIndex = 0; cardIndex < cards.length; cardIndex++) {
      if (isFiniteNumber(cards[cardIndex].strength)) {
        total += cards[cardIndex].strength;
      }
    }

    var nightmareFrames = common.storage.userKnightmareFrameList.toJSON();
    for (var kmfIndex = 0; kmfIndex < nightmareFrames.length; kmfIndex++) {
      var weaponList = nightmareFrames[kmfIndex].weaponList;
      if (!Array.isArray(weaponList)) continue;
      for (var weaponIndex = 0; weaponIndex < weaponList.length; weaponIndex++) {
        var weapon = weaponList[weaponIndex];
        if (weapon && weapon.selected && isFiniteNumber(weapon.strength)) {
          total += weapon.strength;
          break;
        }
      }
    }

    state.lastCalculatedStrength = total;
    return total;
  }

  function install() {
    if (state.installed) return state;
    common.setUserKnightmareFrameModel = setUserKnightmareFrameModel;
    common.getPlayerStrength = getPlayerStrength;
    state.installed = true;
    return state;
  }

  return {
    install: install,
    state: state,
    setUserKnightmareFrameModel: setUserKnightmareFrameModel,
    getPlayerStrength: getPlayerStrength
  };
});
