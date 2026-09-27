(function () {
  var bell = document.getElementById("notif-bell");
  var mobileBell = document.getElementById("notif-bell-mobile");
  var panel = document.getElementById("notif-panel");
  var overlay = document.getElementById("notif-overlay");
  if (!panel || (!bell && !mobileBell)) return;
  var badges = document.querySelectorAll("[data-notif-badge]");
  var triggers = [bell, mobileBell].filter(Boolean);

  function setBadge(count) {
    badges.forEach(function (badge) {
      if (count > 0) {
        badge.textContent = count > 99 ? "99+" : String(count);
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }
    });
  }

  function refreshCount() {
    fetch("/notifications/count")
      .then(function (r) { return r.json(); })
      .then(function (data) { setBadge(data.count || 0); })
      .catch(function () {});
  }

  function loadPanel() {
    panel.innerHTML = "";
    fetch("/notifications/panel")
      .then(function (r) { return r.text(); })
      .then(function (html) { panel.innerHTML = html; })
      .catch(function () {});
  }

  function markAllRead() {
    fetch("/notifications/read-all", { method: "POST" })
      .then(function () { setBadge(0); })
      .catch(function () {});
  }

  // 데스크톱은 종 아래 드롭다운, 모바일 탭에서 열면 하단 시트(.is-sheet) — 같은 패널 하나를 쓴다
  function open(asSheet) {
    panel.classList.toggle("is-sheet", !!asSheet);
    panel.hidden = false;
    if (overlay) overlay.hidden = !asSheet;
    triggers.forEach(function (t) { t.setAttribute("aria-expanded", "true"); });
    // 패널을 먼저 렌더(현재 안 읽음 목록이 이번 열람에는 그대로 보이도록)한 뒤,
    // 종을 열었다는 것만으로 전부 읽음 처리하고 배지를 0으로 만든다.
    loadPanel();
    markAllRead();
  }
  function close() {
    panel.hidden = true;
    if (overlay) overlay.hidden = true;
    triggers.forEach(function (t) { t.setAttribute("aria-expanded", "false"); });
  }
  function toggle(asSheet) {
    if (panel.hidden) open(asSheet); else close();
  }

  if (bell) bell.addEventListener("click", function (e) { e.stopPropagation(); toggle(false); });
  if (mobileBell) mobileBell.addEventListener("click", function (e) { e.stopPropagation(); toggle(true); });
  if (overlay) overlay.addEventListener("click", close);

  // 패널 내용은 innerHTML로 주입되므로(스크립트 실행 안 됨) 탭 전환은 여기서 위임 처리
  panel.addEventListener("click", function (event) {
    var tab = event.target.closest ? event.target.closest("[data-notif-tab]") : null;
    if (!tab) return;
    var target = tab.getAttribute("data-notif-tab");
    panel.querySelectorAll("[data-notif-tab]").forEach(function (t) {
      t.classList.toggle("is-active", t === tab);
    });
    panel.querySelectorAll("[data-notif-pane]").forEach(function (p) {
      p.hidden = p.getAttribute("data-notif-pane") !== target;
    });
  });

  document.addEventListener("click", function (event) {
    if (panel.hidden) return;
    if (panel.contains(event.target)) return;
    if (triggers.some(function (t) { return t === event.target || t.contains(event.target); })) return;
    close();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) close();
  });

  refreshCount();

  var source = new EventSource("/events/notifications");
  source.addEventListener("notification", function (event) {
    var data = JSON.parse(event.data);
    if (window.showToast) window.showToast(data.text, "info");
    if (window.playNotifSound) window.playNotifSound();
    refreshCount();
    if (window.refreshNavBadges) window.refreshNavBadges(); // 초대 알림이면 초대 탭 배지도 같이
  });
})();
