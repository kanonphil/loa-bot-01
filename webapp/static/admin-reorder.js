// 관리자 목록 순서 변경 — 드래그(HTML5 drag&drop) + ▲▼ 버튼으로 로컬에서만 순서를
// 바꾸고, "순서 저장"을 눌러야 최종 배열이 통째로 POST된다(항목마다 저장하면 중간
// 상태가 남아 순서가 깨진다). 되돌리기는 페이지 로드 시점 순서로 복원.
//
// 사용법: <ul data-reorder-group data-reorder-form="#form-id"> 안의 <li data-key="...">
//        폼 안에 <input type="hidden" name="order"> + [data-reorder-reset] 버튼.
(function () {
  document.querySelectorAll("[data-reorder-group]").forEach(function (list) {
    var form = document.querySelector(list.dataset.reorderForm);
    if (!form) return;
    var input = form.querySelector('input[name="order"]');
    var items = function () {
      return Array.prototype.slice.call(list.querySelectorAll(":scope > [data-key]"));
    };
    var keys = function () {
      return items().map(function (li) { return li.dataset.key; });
    };
    var original = keys();

    function sync() {
      var current = keys();
      var changed = current.join("\u0001") !== original.join("\u0001");
      form.hidden = !changed;
      input.value = JSON.stringify(current);
    }

    list.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-move]");
      if (!btn || !list.contains(btn)) return;
      e.preventDefault();
      var li = btn.closest("[data-key]");
      if (btn.dataset.move === "up" && li.previousElementSibling) {
        list.insertBefore(li, li.previousElementSibling);
      } else if (btn.dataset.move === "down" && li.nextElementSibling) {
        list.insertBefore(li.nextElementSibling, li);
      }
      sync();
    });

    var dragging = null;
    items().forEach(function (li) {
      var handle = li.querySelector("[data-drag-handle]") || li;
      handle.setAttribute("draggable", "true");
      handle.addEventListener("dragstart", function (e) {
        dragging = li;
        li.classList.add("is-dragging");
        try { e.dataTransfer.setData("text/plain", li.dataset.key); } catch (_) {}
        e.dataTransfer.effectAllowed = "move";
      });
      handle.addEventListener("dragend", function () {
        li.classList.remove("is-dragging");
        dragging = null;
        sync();
      });
      li.addEventListener("dragover", function (e) {
        if (!dragging || dragging === li) return;
        e.preventDefault();
        var rect = li.getBoundingClientRect();
        var before = e.clientY - rect.top < rect.height / 2;
        list.insertBefore(dragging, before ? li : li.nextSibling);
      });
    });

    var reset = form.querySelector("[data-reorder-reset]");
    if (reset) {
      reset.addEventListener("click", function (e) {
        e.preventDefault();
        original.forEach(function (key) {
          var li = items().find(function (el) { return el.dataset.key === key; });
          if (li) list.appendChild(li);
        });
        sync();
      });
    }

    sync();
  });
})();
