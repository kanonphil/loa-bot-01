// 관리 화면 순서 변경 — 끌기(HTML5 drag&drop) 또는 손잡이에서 ↑↓ 키로 로컬에서만 순서를 바꾸고,
// 바뀌었을 때만 "순서 저장" 바가 나타난다. 최종 배열을 한 번에 POST한다(항목마다 저장하면 중간 상태가 남는다).
//
// 마크업:
//   <section data-reorder-group> 안의 [data-key="…"] 항목(li·div·tr), 항목 안의 [data-drag-handle] 버튼
//   같은 카드/대화상자 안의 <form data-reorder-bar hidden>
//     data-reorder-array → <input name="order">에 이 그룹의 배열 JSON
//     data-reorder-map   → <input name="orders">에 {그룹의 data-category: 배열} JSON(바뀐 그룹만)
//     [data-reorder-reset] 버튼 = 처음 순서로
(function () {
  "use strict";

  function barFor(group) {
    var a = group.parentElement;
    while (a && a !== document.body) {
      var b = a.querySelector("[data-reorder-bar]");
      if (b) return b;
      a = a.parentElement;
    }
    return null;
  }

  var barState = new Map(); // bar → [{group, original}]

  function keys(group) {
    return [].slice.call(group.children).filter(function (el) { return el.dataset && el.dataset.key !== undefined; })
      .map(function (el) { return el.dataset.key; });
  }
  function itemsOf(group) {
    return [].slice.call(group.children).filter(function (el) { return el.dataset && el.dataset.key !== undefined; });
  }

  function sync(bar) {
    var states = barState.get(bar) || [];
    var changed = states.filter(function (s) { return keys(s.group).join("\u0001") !== s.original.join("\u0001"); });
    bar.hidden = changed.length === 0;
    if (bar.hasAttribute("data-reorder-map")) {
      var map = {};
      changed.forEach(function (s) { map[s.group.dataset.category || ""] = keys(s.group); });
      bar.querySelector('input[name="orders"]').value = JSON.stringify(map);
    } else if (states[0]) {
      bar.querySelector('input[name="order"]').value = JSON.stringify(keys(states[0].group));
    }
  }

  [].slice.call(document.querySelectorAll("[data-reorder-group]")).forEach(function (group) {
    var bar = barFor(group);
    if (!bar) return;
    if (!barState.has(bar)) barState.set(bar, []);
    var state = { group: group, original: keys(group) };
    barState.get(bar).push(state);

    var dragging = null;
    itemsOf(group).forEach(function (item) {
      var handle = item.querySelector("[data-drag-handle]");
      if (handle) {
        handle.addEventListener("dragstart", function (e) {
          dragging = item;
          item.classList.add("is-dragging");
          try { e.dataTransfer.setData("text/plain", item.dataset.key); e.dataTransfer.setDragImage(item, 12, 12); } catch (_) { /* 일부 브라우저 */ }
          e.dataTransfer.effectAllowed = "move";
        });
        handle.addEventListener("dragend", function () {
          item.classList.remove("is-dragging");
          dragging = null;
          sync(bar);
        });
        handle.addEventListener("keydown", function (e) {
          if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
          e.preventDefault();
          if (e.key === "ArrowUp" && item.previousElementSibling && item.previousElementSibling.dataset.key !== undefined) {
            group.insertBefore(item, item.previousElementSibling);
          } else if (e.key === "ArrowDown" && item.nextElementSibling && item.nextElementSibling.dataset.key !== undefined) {
            group.insertBefore(item.nextElementSibling, item);
          }
          handle.focus();
          sync(bar);
        });
      }
      item.addEventListener("dragover", function (e) {
        if (!dragging || dragging === item || dragging.parentNode !== group) return;
        e.preventDefault();
        var rect = item.getBoundingClientRect();
        var before = e.clientY - rect.top < rect.height / 2;
        group.insertBefore(dragging, before ? item : item.nextSibling);
      });
    });
  });

  barState.forEach(function (states, bar) {
    var reset = bar.querySelector("[data-reorder-reset]");
    if (reset) {
      reset.addEventListener("click", function () {
        states.forEach(function (s) {
          s.original.forEach(function (key) {
            var item = itemsOf(s.group).find(function (el) { return el.dataset.key === key; });
            if (item) s.group.appendChild(item);
          });
        });
        sync(bar);
      });
    }
    sync(bar);
  });

  // 순서를 바꿔 놓고 다른 레이드를 누르면 바뀐 순서가 사라진다 — 한 번 묻는다
  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("a.ad-ri-link");
    if (!link || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey) return;
    var dirty = false;
    barState.forEach(function (_, bar) { if (!bar.hidden) dirty = true; });
    if (!dirty || !window.uiConfirm) return;
    e.preventDefault();
    window.uiConfirm({
      title: "바꾼 순서를 저장하지 않았습니다", message: "이대로 이동하면 바뀐 순서는 사라집니다.", ok: "이동",
    }).then(function (ok) { if (ok) window.location.href = link.href; });
  });
})();
