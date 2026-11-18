// data-tip 툴팁 — 네이티브 title 대신(터치·키보드에서 안 보이고 뜨는 데 1초 걸린다).
// 마우스 올림·키보드 포커스 즉시, 터치는 길게 누르면. 줄바꿈(\n)은 그대로 표시된다.
// 접힌 왼쪽 메뉴(.side-link)는 CSS 자체 툴팁을 쓰므로 여기서는 건너뛴다.
(function () {
  var tip = null;
  var owner = null;
  var pressTimer = null;

  function ensureTip() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "ui-tip";
      tip.id = "ui-tip";
      tip.setAttribute("role", "tooltip");
      tip.hidden = true;
      document.body.appendChild(tip);
    }
    return tip;
  }

  function target(el) {
    var t = el && el.closest ? el.closest("[data-tip]") : null;
    if (!t || t.classList.contains("side-link")) return null;
    return t;
  }

  function show(el) {
    var text = el.getAttribute("data-tip");
    if (!text) return;
    var t = ensureTip();
    owner = el;
    t.textContent = text;
    t.hidden = false;
    el.setAttribute("aria-describedby", "ui-tip");

    var rect = el.getBoundingClientRect();
    var tipRect = t.getBoundingClientRect();
    var left = rect.left + rect.width / 2 - tipRect.width / 2;
    var top = rect.top - tipRect.height - 8;
    var place = "top";
    // 위 공간이 없으면 아래로, 화면 밖이면 안쪽으로
    if (top < 8) { top = rect.bottom + 8; place = "bottom"; }
    if (left + tipRect.width > window.innerWidth - 8) left = window.innerWidth - tipRect.width - 8;
    if (left < 8) left = 8;
    t.setAttribute("data-place", place);
    var arrow = Math.min(Math.max(rect.left + rect.width / 2 - left, 10), tipRect.width - 10);
    t.style.setProperty("--tip-x", arrow + "px");
    t.style.left = left + "px";
    t.style.top = top + "px";
  }

  function hide() {
    if (tip) tip.hidden = true;
    if (owner) owner.removeAttribute("aria-describedby");
    owner = null;
  }

  document.addEventListener("mouseover", function (e) {
    var el = target(e.target);
    if (el && el !== owner) show(el);
  });
  document.addEventListener("mouseout", function (e) {
    var el = target(e.target);
    if (!el) return;
    if (e.relatedTarget && el.contains(e.relatedTarget)) return; // 같은 요소 안에서 이동
    if (document.activeElement === el && el.matches(":focus-visible")) return;
    hide();
  });
  document.addEventListener("focusin", function (e) {
    var el = target(e.target);
    if (el && el.matches(":focus-visible")) show(el);
  });
  document.addEventListener("focusout", function (e) {
    if (target(e.target) === owner) hide();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && owner) hide(); });

  // 터치: 길게 누르면(0.45초) 표시, 손을 떼고 잠시 뒤 숨김
  document.addEventListener("touchstart", function (e) {
    var el = target(e.target);
    clearTimeout(pressTimer);
    if (!el) { hide(); return; }
    pressTimer = setTimeout(function () { show(el); }, 450);
  }, { passive: true });
  document.addEventListener("touchend", function () {
    clearTimeout(pressTimer);
    if (owner) setTimeout(hide, 1500);
  }, { passive: true });
  document.addEventListener("touchmove", function () { clearTimeout(pressTimer); }, { passive: true });

  document.addEventListener("scroll", hide, true);
})();
