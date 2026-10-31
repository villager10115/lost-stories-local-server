define(["backboneCommon"], function (common) {
  "use strict";
  function failed(event) {
    var image = event.target;
    if (!image || image.tagName !== "IMG") return;
    var path = image.getAttribute("src") || "";
    var parent, label;
    if (/image\/quest\/main\/chapter\/pnl_story_main_\d+\.webp/.test(path)) {
      parent = image.closest(".chapterBanner");
    } else if (/image\/quest\/main\/part\/btn_part_/.test(path)) {
      parent = image.closest(".partWrap");
      if (parent) {
        var id = Number(parent.getAttribute("data-part-id"));
        var row = common.storage.partList && common.storage.partList.findWhere({partId: id});
        label = row ? "第" + row.get("partNo") + "部　" + row.get("title") : "部 " + id;
        parent.setAttribute("data-local-label", label);
      }
    }
    if (!parent) return;
    // Keep the original image's dimensions and the official click target.
    // Chapter numbers/titles remain the original template's text.
    image.style.visibility = "hidden";
    parent.classList.add("localMissingArtwork");
  }
  function install() {
    document.addEventListener("error", failed, true);
    Array.prototype.forEach.call(document.images, function (image) {
      if (image.complete && !image.naturalWidth) failed({target: image});
    });
  }
  return {install: install};
});
