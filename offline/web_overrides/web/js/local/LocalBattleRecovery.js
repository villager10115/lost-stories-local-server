define(["backboneCommon", "ajaxControl"], function (common, ajax) {
  "use strict";
  var installed = false;
  var button;
  function remove() {
    if (button && button.parentNode) button.parentNode.removeChild(button);
    button = null;
  }
  function render(active) {
    remove();
    if (!active || !/^#\/DeckFormation(?:\/|$)/.test(location.hash)) return;
    button = document.createElement("button");
    button.id = "localInterruptedBattle";
    button.textContent = "中断したバトルを終了";
    button.style.cssText = "position:fixed;right:20px;bottom:18px;z-index:10000;padding:10px 18px;background:#302544;color:white;border:1px solid #d1b8ff;border-radius:4px;font-size:15px;cursor:pointer";
    button.addEventListener("click", function () {
      new common.PopupClass({
        title: "中断したバトル",
        content: "進行中のバトルをリタイアすると、スタミナが" +
          Number(active.returnStaminaOnFail) + "戻ります。報酬は獲得しません。<br>終了しますか？",
        closeBtnText: "キャンセル", decideBtnText: "リタイア",
        decideBtnEvent: function (event) {
          if (event) event.preventDefault();
          if (common.isScrolled()) return;
          ajax.ajaxPost("/api/local/battle/retire", {userQuestResultId:active.userQuestResultId}, function (response) {
            if (response.resultCode === "error") {
              new common.PopupClass({title:response.title, content:response.errorTxt, closeBtnText:"OK"});
              return;
            }
            common.setResponseStorage(response);
            if (common.g_popup_instance) common.g_popup_instance.popupView.close();
            remove();
          });
        }
      });
    });
    document.body.appendChild(button);
  }
  return {install:function () {
    if (installed) return;
    installed = true;
    // DeckFormation's last/single skip callback assumes success. Keep business
    // errors out of that callback so it cannot read an absent battleResult or
    // enter QuestResult with an error response.
    var originalPost = ajax.ajaxPost;
    ajax.ajaxPost = function (url, data, callback) {
      var args = Array.prototype.slice.call(arguments);
      if (url === "/api/battle/skip") {
        args[2] = function (response) {
          if (response && response.resultCode === "error") {
            common.isBattleSkip = false;
            common.tapBlock(false);
            common.loading.hide();
            common.ready.hide();
            if (common.g_popup_instance) common.g_popup_instance.popupView.close();
            var completed = (common.allSkipResponse || []).length;
            var detail = completed ? "<br>" + completed + "回分の報酬は保存されています。" : "";
            new common.PopupClass({title:response.title, content:response.errorTxt + detail, closeBtnText:"OK",
              closeEvent:function () {
                common.ready.show();
                common.pageTransition("#/DailyQuestTop");
              }});
            return;
          }
          return callback.apply(this, arguments);
        };
      }
      return originalPost.apply(this, args);
    };
    $(document).ajaxComplete(function (_, xhr, settings) {
      if (settings.url.split("?")[0] === "/api/page/DeckFormation" && xhr.status === 200) {
        render(xhr.responseJSON && xhr.responseJSON.localActiveBattle);
      }
    });
    window.addEventListener("hashchange", remove);
  }, render:render};
});
