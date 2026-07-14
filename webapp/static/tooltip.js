// data-tip 속성이 있는 요소에 마우스를 올리면 네이티브 title 대신
// 카드 스타일 툴팁(.ui-tip)을 띄운다. 줄바꿈(\n)은 그대로 표시된다.
(function () {
  var tip = null;

  function ensureTip() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "ui-tip";
      tip.hidden = true;
      document.body.appendChild(tip);
    }
    return tip;
  }

  function show(el) {
    var text = el.getAttribute("data-tip");
    if (!text) return;
    var t = ensureTip();
    t.textContent = text;
    t.hidden = false;

    var rect = el.getBoundingClientRect();
    var tipRect = t.getBoundingClientRect();
    var left = rect.left;
    var top = rect.bottom + 8;
    // 화면 밖으로 나가면 안쪽으로 밀고, 아래 공간이 없으면 위로 띄운다
    if (left + tipRect.width > window.innerWidth - 12) {
      left = window.innerWidth - tipRect.width - 12;
    }
    if (left < 12) left = 12;
    if (top + tipRect.height > window.innerHeight - 12) {
      top = rect.top - tipRect.height - 8;
    }
    if (top < 12) top = 12;
    t.style.left = left + "px";
    t.style.top = top + "px";
  }

  function hide() {
    if (tip) tip.hidden = true;
  }

  document.addEventListener("mouseover", function (event) {
    var el = event.target.closest ? event.target.closest("[data-tip]") : null;
    if (el) show(el);
  });

  document.addEventListener("mouseout", function (event) {
    var el = event.target.closest ? event.target.closest("[data-tip]") : null;
    if (!el) return;
    // 같은 data-tip 요소 내부 이동이면 유지
    if (event.relatedTarget && el.contains(event.relatedTarget)) return;
    hide();
  });

  document.addEventListener("scroll", hide, true);
})();
