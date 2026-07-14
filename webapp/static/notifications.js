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
