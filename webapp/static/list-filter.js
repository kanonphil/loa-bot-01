// 목록 페이지 공통 "타이핑하면 걸러지는" 검색 — data-filter-* 속성만 붙이면
// 서버 왕복 없이 화면에서 필터링된다. party_list.html에 있던 인라인 스크립트를
// party_history.html/admin_parties.html에도 똑같이 붙이기 위해 공용화했다.
(function () {
  document.querySelectorAll(".js-list-filter").forEach(function (input) {
    var list = document.querySelector(input.dataset.filterTarget);
    if (!list) return;
    var itemSel = input.dataset.filterItem;
    var textSel = input.dataset.filterText;
    var noResult = input.dataset.filterNoResult
      ? document.querySelector(input.dataset.filterNoResult)
      : null;
    var items = Array.prototype.slice.call(list.querySelectorAll(itemSel));

    input.addEventListener("input", function () {
      var q = input.value.trim().toLowerCase();
      var visible = 0;
      items.forEach(function (item) {
        var textEl = textSel ? item.querySelector(textSel) : item;
        var text = (textEl ? textEl.textContent : "").toLowerCase();
        var show = !q || text.includes(q);
        item.hidden = !show;
        if (show) visible++;
      });
      if (noResult) noResult.hidden = visible > 0;
    });
  });
})();
