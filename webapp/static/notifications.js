// 알림 종 + 팝오버(전체/안 읽음, 오늘/이번 주 묶음) + 실시간 토스트(SSE).
// 패널을 여는 GET /notifications/panel 이 그 자리에서 읽음 처리까지 한다 — 열 때 따로 read-all을 부르지 않는다.
// "모두 읽음" 버튼만 명시적으로 POST /notifications/read-all.
(function () {
  var panel = document.getElementById("notif-panel");
  var triggers = [document.getElementById("notif-bell"), document.getElementById("notif-bell-mobile")].filter(Boolean);
  if (!panel || !triggers.length) return;
  var badges = document.querySelectorAll("[data-notif-badge]");
  var opener = null;

  function setBadge(count) {
    badges.forEach(function (badge) {
      if (count > 0) {
        badge.textContent = count > 99 ? "99+" : String(count);
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }
    });
    triggers.forEach(function (t) { t.setAttribute("aria-label", count > 0 ? "알림, 안 읽음 " + count + "개" : "알림"); });
    if (window.uiSetUnread) window.uiSetUnread(count);
  }

  function refreshCount() {
    fetch("/notifications/count", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) setBadge(data.count || 0); })
      .catch(function () {});
  }

  // 오늘 / 이번 주 / 이전 — 서버는 UTC ISO(created_at)를 내려주고, 묶음은 보는 사람 시계 기준
  function groupItems() {
    var list = panel.querySelector("[data-notif-list]");
    if (!list) return;
    var now = new Date();
    var startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    var weekAgo = startToday - 6 * 86400000;
    var last = null;
    [].slice.call(list.children).forEach(function (li) {
      var raw = li.getAttribute("data-created") || "";
      // 시간대 표시가 없으면 UTC로 읽는다(서버 저장 형식)
      var t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(raw) ? raw : raw + "Z");
      var g = isNaN(t) ? "이전" : t >= startToday ? "오늘" : t >= weekAgo ? "이번 주" : "이전";
      li.setAttribute("data-group", g);
      if (g !== last) {
        var h = document.createElement("li");
        h.className = "notif-pop-g";
        h.setAttribute("role", "presentation");
        h.setAttribute("data-group-head", g);
        h.textContent = g;
        list.insertBefore(h, li);
        last = g;
      }
    });
  }

  function applyFilter(which) {
    panel.querySelectorAll("[data-notif-tab]").forEach(function (t) {
      var on = t.getAttribute("data-notif-tab") === which;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
    });
    var list = panel.querySelector("[data-notif-list]");
    var shown = {};
    var any = false;
    if (list) {
      list.querySelectorAll("li[data-group]").forEach(function (li) {
        var show = which === "all" || li.classList.contains("is-unread");
        li.hidden = !show;
        if (show) { shown[li.getAttribute("data-group")] = true; any = true; }
      });
      list.querySelectorAll("[data-group-head]").forEach(function (h) { h.hidden = !shown[h.getAttribute("data-group-head")]; });
    }
    var empty = panel.querySelector("[data-notif-empty-unread]");
    if (empty) empty.hidden = !(which === "unread" && !any);
  }

  function place() {
    if (!opener) return;
    var r = opener.getBoundingClientRect();
    if (window.innerWidth <= 760) {
      panel.style.left = "8px";
      panel.style.right = "8px";
      panel.style.width = "auto";
    } else {
      panel.style.left = "auto";
      panel.style.right = Math.max(8, window.innerWidth - r.right) + "px";
      panel.style.width = "";
    }
    panel.style.top = r.bottom + 8 + "px";
  }

  var HEAD = '<div class="notif-pop-h"><h2>알림</h2></div>';
  function load() {
    panel.setAttribute("aria-busy", "true");
    panel.innerHTML = HEAD + '<div style="padding:14px;display:flex;flex-direction:column;gap:12px"><span class="sk" style="width:60%"></span><span class="sk"></span><span class="sk" style="width:80%"></span></div>';
    fetch("/notifications/panel", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        panel.innerHTML = html;
        panel.removeAttribute("aria-busy");
        groupItems();
        applyFilter("all");
        setBadge(0); // 패널을 연 것으로 서버가 읽음 처리한다
      })
      .catch(function () {
        panel.removeAttribute("aria-busy");
        panel.innerHTML = HEAD + '<p class="notif-pop-note" style="padding-bottom:14px">알림을 불러오지 못했습니다. 잠시 후 다시 열어 주세요.</p>';
      });
  }

  function close() {
    panel.hidden = true;
    triggers.forEach(function (t) { t.setAttribute("aria-expanded", "false"); });
  }
  function open(trigger) {
    opener = trigger;
    panel.hidden = false;
    triggers.forEach(function (t) { t.setAttribute("aria-expanded", t === trigger ? "true" : "false"); });
    place();
    if (window.uiPopup) window.uiPopup.open({ el: panel, opener: trigger, close: close });
    load();
    panel.setAttribute("tabindex", "-1");
    panel.focus({ preventScroll: true });
  }

  triggers.forEach(function (t) {
    t.addEventListener("click", function () {
      if (!panel.hidden && opener === t) {
        if (window.uiPopup) window.uiPopup.close(true); else close();
      } else {
        open(t);
      }
    });
  });
  window.addEventListener("resize", function () { if (!panel.hidden) place(); });

  // 패널 내용은 innerHTML로 들어오므로(스크립트 실행 안 됨) 탭·모두 읽음은 위임 처리
  panel.addEventListener("click", function (e) {
    var tab = e.target.closest && e.target.closest("[data-notif-tab]");
    if (tab) { applyFilter(tab.getAttribute("data-notif-tab")); return; }
    var all = e.target.closest && e.target.closest("[data-notif-read-all]");
    if (!all) return;
    all.setAttribute("aria-busy", "true");
    fetch("/notifications/read-all", { method: "POST", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        panel.querySelectorAll(".n-item:not(.read)").forEach(function (a) { a.classList.add("read"); });
        panel.querySelectorAll("li.is-unread").forEach(function (li) { li.classList.remove("is-unread"); });
        setBadge(0);
        all.removeAttribute("aria-busy");
        all.disabled = true;
      })
      .catch(function () {
        all.removeAttribute("aria-busy");
        if (window.showToast) window.showToast("err", "읽음 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.");
      });
  });
  panel.addEventListener("keydown", function (e) {
    var tab = e.target.closest && e.target.closest("[data-notif-tab]");
    if (!tab || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) return;
    var tabs = [].slice.call(panel.querySelectorAll("[data-notif-tab]"));
    var next = tabs[(tabs.indexOf(tab) + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
    e.preventDefault();
    e.stopPropagation();
    next.focus();
    applyFilter(next.getAttribute("data-notif-tab"));
  });

  refreshCount();

  var source = new EventSource("/events/notifications");
  source.addEventListener("notification", function (event) {
    var data = JSON.parse(event.data);
    if (window.showToast) window.showToast("info", data.text);
    if (window.playNotifSound) window.playNotifSound();
    refreshCount();
    if (window.refreshNavBadges) window.refreshNavBadges(); // 초대 알림이면 홈 배지도 같이
  });
})();
