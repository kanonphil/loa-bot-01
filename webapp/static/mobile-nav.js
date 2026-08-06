(function () {
  var menuBtn = document.getElementById("mobile-menu-btn");
  var overlay = document.getElementById("sidebar-overlay");
  if (!menuBtn || !overlay) return;

  // 모바일에서 메뉴를 연 상태로 기기 뒤로가기를 누르면 이전 화면 자체로 나가버리던
  // 문제 — pushState로 "메뉴 열림"을 기록해두고, popstate에서 페이지 이동 대신
  // 메뉴만 닫는다.
  var openedViaHistory = false;

  function open() {
    document.body.classList.add("sidebar-open");
    history.pushState({ sidebarOpen: true }, "");
    openedViaHistory = true;
  }

  function close() {
    document.body.classList.remove("sidebar-open");
    if (openedViaHistory) {
      openedViaHistory = false;
      history.back(); // 열 때 쌓아둔 기록을 그대로 소비 — 안 하면 다음 "앞으로가기"가 메뉴를 다시 연다
    }
  }

  menuBtn.addEventListener("click", function () {
    if (document.body.classList.contains("sidebar-open")) {
      close();
    } else {
      open();
    }
  });

  overlay.addEventListener("click", close);

  window.addEventListener("popstate", function () {
    if (document.body.classList.contains("sidebar-open")) {
      document.body.classList.remove("sidebar-open");
      openedViaHistory = false;
    }
  });
})();
