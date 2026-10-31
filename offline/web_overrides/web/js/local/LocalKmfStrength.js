define(function () {
  "use strict";

  var TIER_COUNT = 5;

  function finiteNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    var number = Number(value);
    return isFinite(number) ? number : null;
  }

  function selectedWeapon(kmf) {
    if (!kmf || !Array.isArray(kmf.weaponList)) return null;
    for (var index = 0; index < kmf.weaponList.length; index++) {
      if (kmf.weaponList[index] && kmf.weaponList[index].selected) {
        return kmf.weaponList[index];
      }
    }
    return null;
  }

  function matchingCustomization(kmf, customizations) {
    if (!kmf || !Array.isArray(customizations)) return null;
    var fallback = null;
    for (var index = 0; index < customizations.length; index++) {
      var row = customizations[index];
      if (!row || row.userKnightmareFrameId !== kmf.userKnightmareFrameId) {
        continue;
      }
      if (row.selected) return row;
      if (!fallback) fallback = row;
    }
    return fallback;
  }

  function strengthFor(kmf, customizations) {
    var weapon = selectedWeapon(kmf);
    var strength = weapon ? finiteNumber(weapon.strength) : null;
    if (strength !== null) return strength;

    strength = finiteNumber(kmf && kmf.strength);
    if (strength !== null) return strength;

    var customization = matchingCustomization(kmf, customizations);
    return customization ? finiteNumber(customization.strength) : null;
  }

  function thresholdsFor(strengths) {
    var unique = [];
    for (var index = 0; index < strengths.length; index++) {
      var strength = finiteNumber(strengths[index]);
      if (strength !== null && unique.indexOf(strength) === -1) {
        unique.push(strength);
      }
    }
    unique.sort(function (left, right) { return left - right; });
    if (!unique.length) return [];
    if (unique.length === 1) return [{value: unique[0], tier: 3}];

    var thresholds = [];
    for (var rank = 0; rank < unique.length; rank++) {
      var tier = Math.round(1 + rank * (TIER_COUNT - 1) /
        (unique.length - 1));
      thresholds.push({value: unique[rank], tier: tier});
    }
    return thresholds;
  }

  function tierFor(strength, thresholds) {
    var value = finiteNumber(strength);
    if (value === null || !Array.isArray(thresholds)) return 0;
    var tier = 0;
    for (var index = 0; index < thresholds.length; index++) {
      if (value < thresholds[index].value) break;
      tier = thresholds[index].tier;
    }
    return tier;
  }

  function decorate(kmfs, customizations) {
    var rows = Array.isArray(kmfs) ? kmfs : [];
    var strengths = rows.map(function (kmf) {
      return strengthFor(kmf, customizations);
    });
    var thresholds = thresholdsFor(strengths);
    return rows.map(function (kmf, index) {
      return {
        strength: strengths[index],
        tier: tierFor(strengths[index], thresholds)
      };
    });
  }

  return {
    decorate: decorate,
    strengthFor: strengthFor,
    tierFor: tierFor
  };
});
