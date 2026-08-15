/* 네이티브 <select>는 닫힌 상태는 CSS로 꾸밀 수 있지만, 펼쳐진 목록(옵션 하이라이트 등)은
 * 브라우저가 그리는 네이티브 팝업이라 CSS로 손댈 수 없다. 이 스크립트는 select 하나를
 * 그대로 둔 채(폼 제출은 여전히 이 select가 처리) 그 위에 버튼+커스텀 목록을 씌워서
 * 펼쳐진 상태까지 테마에 맞게 그린다.
 *
 * 사용법: <select class="js-themed-select">에 자동으로 적용된다. select의 옵션을
 * 스크립트로 바꾸는 화면(예: disabled 토글)은 select.dispatchEvent(new Event("change"))를
 * 호출해줘야 트리거 라벨/목록이 다시 그려진다 — .value를 직접 대입하는 것만으로는
 * 네이티브 change 이벤트가 발생하지 않기 때문이다. */
(function () {
  function buildDropdown(select) {
    if (select.dataset.themedSelectInit) return;
    select.dataset.themedSelectInit = "1";

    var wrap = document.createElement("div");
    wrap.className = "themed-select";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.classList.add("themed-select-native");
    select.setAttribute("tabindex", "-1");
    select.setAttribute("aria-hidden", "true");

    var button = document.createElement("button");
    button.type = "button";
    button.className = "themed-select-trigger";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    wrap.appendChild(button);

    var label = document.createElement("span");
    label.className = "themed-select-label";
    button.appendChild(label);

    var list = document.createElement("ul");
    var listId = "themed-select-list-" + Math.random().toString(36).slice(2, 9);
    list.id = listId;
    list.className = "themed-select-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    wrap.appendChild(list);
    button.setAttribute("aria-controls", listId);

    function renderOptions() {
      list.innerHTML = "";
      Array.prototype.forEach.call(select.options, function (opt, i) {
        var li = document.createElement("li");
        li.className = "themed-select-option";
        if (opt.selected) li.classList.add("is-selected");
        if (opt.disabled) {
          li.classList.add("is-disabled");
          li.setAttribute("aria-disabled", "true");
        }
        li.textContent = opt.textContent;
        li.setAttribute("role", "option");
        li.id = listId + "-opt-" + i;
        li.dataset.index = String(i);
        list.appendChild(li);
      });
    }

    function syncLabel() {
      var opt = select.options[select.selectedIndex];
      label.textContent = opt ? opt.textContent : "";
    }

    function setActive(li) {
      var prev = list.querySelector(".is-active");
      if (prev) prev.classList.remove("is-active");
      if (li) {
        li.classList.add("is-active");
        list.setAttribute("aria-activedescendant", li.id);
        li.scrollIntoView({ block: "nearest" });
      }
    }

    function openList() {
      renderOptions();
      list.hidden = false;
      wrap.classList.add("is-open");
      button.setAttribute("aria-expanded", "true");
      setActive(list.querySelector(".is-selected") || list.querySelector(".themed-select-option:not(.is-disabled)"));
    }

    function closeList() {
      list.hidden = true;
      wrap.classList.remove("is-open");
      button.setAttribute("aria-expanded", "false");
    }

    function choose(li) {
      if (!li || li.classList.contains("is-disabled")) return;
      select.selectedIndex = parseInt(li.dataset.index, 10);
      select.dispatchEvent(new Event("change", { bubbles: true }));
      syncLabel();
      closeList();
      button.focus();
    }

    button.addEventListener("click", function () {
      if (list.hidden) openList();
      else closeList();
    });

    list.addEventListener("click", function (e) {
      var li = e.target.closest(".themed-select-option");
      if (li) choose(li);
    });

    document.addEventListener("click", function (e) {
      if (!wrap.contains(e.target)) closeList();
    });

    /* 목록의 <li>는 포커스를 받지 않는다 — 포커스는 계속 버튼에 두고
       aria-activedescendant로 "지금 고른 항목"만 시각적으로 옮긴다(콤보박스 패턴). */
    button.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (list.hidden) {
          openList();
          return;
        }
        var items = Array.prototype.slice.call(list.querySelectorAll(".themed-select-option:not(.is-disabled)"));
        var current = list.querySelector(".is-active");
        var idx = items.indexOf(current);
        if (e.key === "ArrowDown") setActive(items[Math.min(items.length - 1, idx + 1)]);
        else setActive(items[Math.max(0, idx - 1)]);
      } else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (list.hidden) {
          openList();
        } else {
          choose(list.querySelector(".is-active"));
        }
      } else if (e.key === "Escape") {
        if (!list.hidden) {
          e.preventDefault();
          closeList();
        }
      } else if (e.key === "Tab") {
        closeList();
      }
    });

    select.addEventListener("change", syncLabel);

    syncLabel();
  }

  function init() {
    document.querySelectorAll("select.js-themed-select").forEach(buildDropdown);
  }

  document.addEventListener("DOMContentLoaded", init);
  window.initThemedSelects = init;
})();
