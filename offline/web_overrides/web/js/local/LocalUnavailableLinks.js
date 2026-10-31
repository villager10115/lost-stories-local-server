define(["backboneCommon", "command"], function (common, command) {
  "use strict";

  var BLOCKED = [
    { prefix: "#/KmfColoring", label: "KMFカラーリング" },
    { prefix: "#/ChallengeQuestTop", label: "チャレンジクエスト" },
    { prefix: "#/ExpeditionTop", label: "遠征" },
    { prefix: "#/AnotherQuestTop", label: "アナザーストーリー" },
    { prefix: "#/SideQuestTop", label: "サイドストーリー" },
    { prefix: "#/EventMultiFrontTop", label: "多方面作戦イベント" },
    { prefix: "#/EventHighStrategicCommandTop", label: "高難度イベント" }
  ];
  var EVENTS = [
    "pointerdown",
    "mousedown",
    "pointerup",
    "mouseup",
    "touchend",
    "click"
  ];
  var PAGE_ROOTS = [
    "MyPage",
    "QuestTop",
    "DailyQuestTop",
    "MainStoryTop",
    "MissionTop",
    "RootEntangleTop",
    "EventStoryTop"
  ];
  var lastNoticeAt = 0;

  function blockedFor(href) {
    for (var i = 0; i < BLOCKED.length; i++) {
      var item = BLOCKED[i];
      if (href === item.prefix || href.indexOf(item.prefix + "/") === 0) {
        return item;
      }
    }
    return null;
  }

  function activeRoot() {
    return (window.location.hash || "")
      .replace(/^#\//, "")
      .split(/[/?]/, 1)[0];
  }

  function cleanupPageRoots() {
    var current = activeRoot();
    for (var i = 0; i < PAGE_ROOTS.length; i++) {
      var pageRoot = PAGE_ROOTS[i];
      var nodes = document.querySelectorAll('[id="' + pageRoot + '"]');
      for (var j = 0; j < nodes.length; j++) {
        if (pageRoot !== current || j < nodes.length - 1) {
          var node = nodes[j];
          if (node.parentNode) node.parentNode.removeChild(node);
        }
      }
    }
  }

  function schedulePageCleanup() {
    var delays = [0, 150, 800, 2000];
    for (var i = 0; i < delays.length; i++) {
      window.setTimeout(cleanupPageRoots, delays[i]);
    }
  }

  function install() {
    if (window.__localUnavailableLinksInstalled) return;
    window.__localUnavailableLinksInstalled = true;
    // Quest movies belong to the native scene, not the page DOM. A late
    // background callback must not recreate one after its route has left.
    var movieActive = activeRoot() === "QuestTop";
    var showMovie = command.showQuestMovie;
    var hideMovie = command.removeQuestMovie;
    command.showQuestMovie = function () {
      if (activeRoot() !== "QuestTop") return;
      movieActive = true;
      return showMovie.apply(command, arguments);
    };
    command.removeQuestMovie = function () {
      movieActive = false;
      return hideMovie.apply(command, arguments);
    };
    window.addEventListener("hashchange", function () {
      if (activeRoot() !== "QuestTop" && movieActive) {
        command.removeQuestMovie();
      }
    });
    function showNotice(item) {
      var now = Date.now();
      if (now - lastNoticeAt < 400) return;
      lastNoticeAt = now;
      new common.PopupClass({
        title: "ローカル版",
        content: item.label + "は、このローカル版では未対応です。",
        closeBtnText: "閉じる",
        canClose: true
      });
    }
    function intercept(event) {
      var element = event.target instanceof Element
        ? event.target.closest("[data-href]")
        : null;
      if (!element) return;
      var item = blockedFor(element.getAttribute("data-href") || "");
      if (!item) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      showNotice(item);
    }
    for (var i = 0; i < EVENTS.length; i++) {
      document.addEventListener(EVENTS[i], intercept, true);
    }
    window.addEventListener("hashchange", schedulePageCleanup);
    schedulePageCleanup();
  }

  return {
    BLOCKED: BLOCKED,
    PAGE_ROOTS: PAGE_ROOTS,
    blockedFor: blockedFor,
    cleanupPageRoots: cleanupPageRoots,
    install: install
  };
});
