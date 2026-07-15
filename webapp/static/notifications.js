(function () {
  var bell = document.getElementById("notif-bell");
  var badge = document.getElementById("notif-badge");
  var panel = document.getElementById("notif-panel");
  if (!bell || !badge || !panel) return;

  function setBadge(count) {
    if (count > 0) {
      badge.textContent = count > 99 ? "99+" : String(count);
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
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

  bell.addEventListener("click", function (event) {
    event.stopPropagation();
    var opening = panel.hidden;
    panel.hidden = !opening;
    if (opening) {
      // 패널을 먼저 렌더(현재 안 읽음 목록이 이번 열람에는 그대로 보이도록)한 뒤,
      // 종을 열었다는 것만으로 전부 읽음 처리하고 배지를 0으로 만든다.
      loadPanel();
      markAllRead();
    }
  });

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
    if (!panel.hidden && !panel.contains(event.target) && event.target !== bell) {
      panel.hidden = true;
    }
  });

  refreshCount();

  var source = new EventSource("/events/notifications");
  source.addEventListener("notification", function (event) {
    var data = JSON.parse(event.data);
    if (window.showToast) window.showToast(data.text, "info");
    if (window.playNotifSound) window.playNotifSound();
    refreshCount();
  });
})();
