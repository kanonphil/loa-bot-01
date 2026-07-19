// 캘린더 레이드명 슬라이드 — 칸 폭보다 길어서 잘린 이름만 좌우로 천천히 왕복시켜
// hover 없이도 전체 이름을 읽을 수 있게 한다. 짧아서 다 보이는 이름은 건드리지 않는다.
// 스타일(키프레임/정지 구간)은 style.css의 .calendar-party-name.is-marquee 참고.
(function () {
  function applyMarquee() {
    document.querySelectorAll(".calendar-party-name").forEach(function (nameEl) {
      var inner = nameEl.querySelector(".marquee-inner");
      if (!inner) return;

      // 리사이즈로 재계산할 때를 위해 일단 초기화하고 실제 잘림 여부를 다시 측정
      nameEl.classList.remove("is-marquee");
      var overflow = inner.scrollWidth - nameEl.clientWidth;
      if (overflow <= 2) return; // 1~2px 오차는 잘린 걸로 안 침

      nameEl.classList.add("is-marquee");
      nameEl.style.setProperty("--marquee-distance", -overflow + "px");
      // 이동 구간이 사이클의 약 절반(키프레임 18~70%)이므로, 실제 흐르는 속도를
      // 약 25px/s로 맞추려면 잘린 길이/13초 — 정지·복귀 구간 포함 최소 4초.
      var duration = Math.max(4, overflow / 13);
      nameEl.style.setProperty("--marquee-duration", duration + "s");
    });
  }

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(applyMarquee, 200);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyMarquee);
  } else {
    applyMarquee();
  }
})();
