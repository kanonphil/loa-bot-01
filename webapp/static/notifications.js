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

  bell.addEventListener("click", function (event) {
    event.stopPropagation();
    var opening = panel.hidden;
    panel.hidden = !opening;
    if (opening) loadPanel();
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
