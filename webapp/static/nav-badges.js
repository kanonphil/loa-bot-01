// 사이드바/하단 탭의 숫자 배지.
// 페이지 렌더를 붙잡지 않으려고 서버 템플릿이 아니라 로드 후 따로 가져온다 —
// 배지 하나 때문에 모든 페이지가 봇 서버 응답을 기다리면 안 된다.
(function () {
  function paint(counts) {
    document.querySelectorAll(".nav-badge[data-badge]").forEach(function (el) {
      var value = counts[el.dataset.badge];
      if (!value) {
        el.hidden = true;
        return;
      }
      el.textContent = value > 99 ? "99+" : value;
      el.hidden = false;
    });
  }

  fetch("/nav-badges", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (counts) { if (counts) paint(counts); })
    .catch(function () { /* 배지는 부가 정보 — 실패해도 화면은 그대로 */ });
})();
