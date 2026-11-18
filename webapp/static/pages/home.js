// 홈(/main) 동작 — 숙제 체크·익스트림·골드섬 스위치·탭·초대 수락 보조.
// 모든 핸들러는 document 위임이다: party-live.js가 SSE로 .page-content를 통째로 바꿔 끼워도 그대로 동작한다.
(function () {
  if (window.__homeInit) return;
  window.__homeInit = true;

  var ERR_NET = "연결하지 못했습니다. 잠시 후 다시 시도해주세요.";
  var busy = {};

  // ── 공통 ──────────────────────────────────────────────
  function toast(kind, msg, opts) { if (window.showToast) window.showToast(kind, msg, opts); }
  function esc(v) { return String(v).replace(/"/g, '\\"'); }

  // 응답을 {success, reason, ...}로 통일한다. 네트워크·로그인 만료·서버 오류도 같은 모양으로.
  function post(url, body, asJson) {
    var headers = { "Accept": "application/json", "X-Requested-With": "fetch" };
    var payload;
    if (asJson) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    else { payload = new URLSearchParams(body); }
    return fetch(url, { method: "POST", headers: headers, body: payload, credentials: "same-origin" })
      .then(function (resp) {
        if (resp.status === 401) return { success: false, reason: "로그인이 풀렸습니다. 새로고침한 뒤 다시 시도해주세요." };
        return resp.json().catch(function () { return {}; }).then(function (data) {
          if (data && typeof data.success === "boolean") return data;
          return { success: false, reason: (data && (data.reason || data.detail)) || "처리하지 못했습니다." };
        });
      })
      .catch(function () { return { success: false, reason: ERR_NET }; });
  }

  function setBusy(btns, on) {
    btns.forEach(function (b) {
      if (!b) return;
      if (on) b.setAttribute("aria-busy", "true"); else b.removeAttribute("aria-busy");
    });
  }

  function flashError(btns) {
    btns.forEach(function (b) {
      if (!b) return;
      b.classList.add("err");
      setTimeout(function () { b.classList.remove("err"); }, 900);
    });
  }

  // party-live.js와 같은 방식으로 .page-content만 새로 받아 바꾼다(익스트림처럼 여러 칸이 한꺼번에 바뀔 때).
  function refreshContent() {
    return fetch("/main", { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = doc.querySelector(".page-content");
        var old = document.querySelector(".page-content");
        if (!fresh || !old) { window.location.reload(); return; }
        old.replaceWith(fresh);
        if (window.refreshNavBadges) window.refreshNavBadges();
        if (window.initThemedSelects) window.initThemedSelects();
      })
      .catch(function () { window.location.reload(); });
  }

  // ── 숙제 체크 ─────────────────────────────────────────
  function segsFor(char, raid) {
    return [].filter.call(document.querySelectorAll(".seg[data-char]"), function (s) {
      return s.dataset.char === char && s.dataset.raid === raid;
    });
  }
  function btnIn(seg, diff) { return seg.querySelector('[data-diff="' + esc(diff) + '"]'); }
  function currentDiff(seg) { var on = seg.querySelector("button.on"); return on ? on.dataset.diff : null; }

  function applyState(char, raid, completions) {
    segsFor(char, raid).forEach(function (seg) {
      [].forEach.call(seg.querySelectorAll("button[data-diff]"), function (b) {
        var on = completions.indexOf(raid + "_" + b.dataset.diff) >= 0;
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
    });
  }

  function updateCounts(char, done, total) {
    if (typeof done !== "number" || typeof total !== "number") return;
    [].forEach.call(document.querySelectorAll('[data-row="' + esc(char) + '"]'), function (row) {
      row.dataset.done = done; row.dataset.total = total;
    });
    [].forEach.call(document.querySelectorAll('[data-char-count="' + esc(char) + '"]'), function (el) {
      el.textContent = done + "/" + total;
    });
    var d = 0, t = 0;
    [].forEach.call(document.querySelectorAll(".hw-desktop [data-row]"), function (row) {
      d += Number(row.dataset.done) || 0; t += Number(row.dataset.total) || 0;
    });
    var dEl = document.querySelector("[data-hw-done]"), tEl = document.querySelector("[data-hw-total]");
    if (dEl) dEl.textContent = d;
    if (tEl) tEl.textContent = t;
    var gauge = document.querySelector("#hw .ui-gauge");
    if (gauge) {
      gauge.firstElementChild.style.width = (t ? Math.round(d / t * 100) : 0) + "%";
      gauge.classList.toggle("is-ok", t > 0 && d >= t);
    }
  }

  function refreshGold() {
    var card = document.getElementById("home-gold");
    if (!card) return;
    fetch("/main/gold", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        if (!html || !html.trim()) return;
        var tpl = document.createElement("template");
        tpl.innerHTML = html.trim();
        var fresh = tpl.content.firstElementChild;
        var cur = document.getElementById("home-gold");
        if (fresh && cur) cur.replaceWith(fresh);
      })
      .catch(function () { /* 골드 카드는 부가 정보 — 실패해도 체크 결과는 그대로 */ });
  }

  function toggleRequest(char, raid, diff) {
    return post("/raid-check/toggle", { character_name: char, raid_name: raid, difficulty: diff });
  }

  function commit(char, raid, res) {
    if (res.completions) applyState(char, raid, res.completions);
    updateCounts(char, res.done, res.total);
    refreshGold();
  }

  // 다른 난이도로 바꾸면 봇이 기존 체크를 대체한다 — 되돌리기는 새 체크를 끄고 이전 난이도를 다시 켠다.
  function undoToggle(char, raid, diff, prev, completed, label) {
    var chain = toggleRequest(char, raid, diff);
    if (completed && prev && prev !== diff) {
      chain = chain.then(function (res) { return res.success ? toggleRequest(char, raid, prev) : res; });
    }
    chain.then(function (res) {
      if (!res.success) { toast("err", res.reason || "되돌리지 못했습니다."); return; }
      commit(char, raid, res);
      toast("info", label + " 되돌렸습니다.");
    });
  }

  function doToggle(seg, diff) {
    var char = seg.dataset.char, raid = seg.dataset.raid, short = seg.dataset.short || raid;
    var key = char + "\n" + raid;
    if (busy[key]) return;
    busy[key] = true;
    var prev = currentDiff(seg);
    var btns = segsFor(char, raid).map(function (s) { return btnIn(s, diff); });
    setBusy(btns, true);
    toggleRequest(char, raid, diff).then(function (res) {
      setBusy(btns, false);
      delete busy[key];
      if (!res.success) {
        flashError(btns);
        toast("err", res.reason || "체크하지 못했습니다.");
        return;
      }
      commit(char, raid, res);
      var label = char + " · " + short + " " + diff;
      toast(res.completed ? "ok" : "info", label + (res.completed ? " 완료" : " 완료 취소"), {
        actionLabel: "되돌리기",
        onAction: function () { undoToggle(char, raid, diff, prev, res.completed, label); },
      });
    });
  }

  // ── 익스트림(원정대 주 1회) ───────────────────────────
  function extremeSet(seg, diff, char, quiet) {
    var raid = seg.dataset.xRaid, short = seg.dataset.short || raid;
    var key = "x\n" + raid;
    if (busy[key]) return;
    busy[key] = true;
    var btn = btnIn(seg, diff);
    setBusy([btn], true);
    post("/raid-check/extreme/set", { raid_name: raid, difficulty: diff, character_name: char }).then(function (res) {
      setBusy([btn], false);
      delete busy[key];
      if (!res.success) { flashError([btn]); toast("err", res.reason || "체크하지 못했습니다."); return; }
      refreshContent().then(function () {
        if (quiet) { toast("info", short + " " + diff + " 클리어를 다시 기록했습니다."); return; }
        toast("ok", short + " " + diff + " 원정대 클리어 — " + char, {
          actionLabel: "되돌리기",
          onAction: function () {
            post("/raid-check/extreme/clear", { raid_name: raid }).then(function (r) {
              if (!r.success) { toast("err", r.reason || "되돌리지 못했습니다."); return; }
              refreshContent().then(function () { toast("info", short + " 클리어를 되돌렸습니다."); });
            });
          },
        });
      });
    });
  }

  function extremeClear(seg, btn) {
    var raid = seg.dataset.xRaid, short = seg.dataset.short || raid;
    var prevDiff = btn.dataset.diff, prevChar = seg.dataset.xBy;
    var key = "x\n" + raid;
    if (busy[key]) return;
    busy[key] = true;
    setBusy([btn], true);
    post("/raid-check/extreme/clear", { raid_name: raid }).then(function (res) {
      setBusy([btn], false);
      delete busy[key];
      if (!res.success) { flashError([btn]); toast("err", res.reason || "해제하지 못했습니다."); return; }
      refreshContent().then(function () {
        toast("info", short + " 클리어 기록을 해제했습니다.", {
          actionLabel: "되돌리기",
          onAction: function () {
            var fresh = [].filter.call(document.querySelectorAll(".seg[data-x-raid]"), function (s) { return s.dataset.xRaid === raid; })[0];
            if (fresh && prevChar) extremeSet(fresh, prevDiff, prevChar, true);
          },
        });
      });
    });
  }

  // ── 메뉴(레이드 고르기·익스트림 캐릭터 선택) ───────────
  // ui.js의 [data-menu-trigger]는 처음 한 번만 묶여서, 페이지 일부를 새로 그리면 죽는다 — 위임으로 직접 연다.
  function menuItems(menu) {
    return [].filter.call(menu.querySelectorAll(".menu-item"), function (i) { return !i.disabled; });
  }
  function toggleMenu(trigger) {
    var menu = document.getElementById(trigger.getAttribute("aria-controls"));
    if (!menu || !window.uiPopup) return;
    if (!menu.hidden) { window.uiPopup.close(true); return; }
    function close() { menu.hidden = true; trigger.setAttribute("aria-expanded", "false"); }
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    window.uiPopup.open({ el: menu, opener: trigger, close: close });
    var items = menuItems(menu);
    if (items.length) items[0].focus();
  }

  // ── 클릭 위임 ─────────────────────────────────────────
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t.closest) return;

    var trigger = t.closest("[data-home-menu]");
    if (trigger) { toggleMenu(trigger); return; }

    var pick = t.closest("[data-x-pick]");
    if (pick) {
      var wrap = pick.closest(".hw-menu-wrap");
      var xseg = wrap && wrap.querySelector(".seg[data-x-raid]");
      if (window.uiPopup) window.uiPopup.close(false);
      if (xseg) extremeSet(xseg, pick.dataset.xDiff, pick.dataset.xPick);
      return;
    }

    var btn = t.closest(".seg button[data-diff]");
    if (btn) {
      var seg = btn.parentNode;
      if (btn.classList.contains("locked")) return;
      if (seg.hasAttribute("data-x-raid")) {
        if (btn.hasAttribute("data-x-clear")) extremeClear(seg, btn);
        else if (btn.dataset.xChar) extremeSet(seg, btn.dataset.diff, btn.dataset.xChar);
      } else if (seg.dataset.char) {
        doToggle(seg, btn.dataset.diff);
      }
      return;
    }

    var filter = t.closest("[data-hw-filter]");
    if (filter) {
      var on = filter.getAttribute("aria-pressed") !== "true";
      filter.setAttribute("aria-pressed", on ? "true" : "false");
      [].forEach.call(document.querySelectorAll("[data-row]"), function (row) {
        var remaining = (Number(row.dataset.total) || 0) - (Number(row.dataset.done) || 0);
        row.hidden = on && remaining <= 0;
      });
      return;
    }

    var tab = t.closest("[data-today-tab]");
    if (tab) {
      var card = tab.closest(".hc-today");
      [].forEach.call(card.querySelectorAll("[data-today-tab]"), function (b) {
        b.setAttribute("aria-pressed", b === tab ? "true" : "false");
      });
      [].forEach.call(card.querySelectorAll("[data-today-panel]"), function (p) {
        p.hidden = p.dataset.todayPanel !== tab.dataset.todayTab;
      });
      return;
    }

    var sw = t.closest("[data-gold-switch]");
    if (sw) { toggleGoldSwitch(sw); return; }

    var inv = t.closest("[data-inv-toggle]");
    if (inv) {
      var form = inv.closest(".inv-form"), panel = form.querySelector(".inv-pick");
      panel.hidden = !panel.hidden;
      inv.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
      syncInvite(form);
      return;
    }

    if (t.closest("#home-reload")) refreshContent();
  });

  document.addEventListener("keydown", function (e) {
    var menu = e.target.closest && e.target.closest(".menu[id^='hw-'], .hw-x-menu");
    if (!menu) return;
    var items = menuItems(menu), i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    } else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
    else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
  });

  // ── 골드섬 알림 ───────────────────────────────────────
  function toggleGoldSwitch(sw) {
    if (sw.getAttribute("aria-busy") === "true") return;
    var next = sw.getAttribute("aria-checked") !== "true";
    sw.setAttribute("aria-busy", "true");
    post("/loa/gold-island-subscription", { enabled: next }, true).then(function (res) {
      sw.removeAttribute("aria-busy");
      if (!res.success) { toast("err", res.reason || "알림 설정을 바꾸지 못했습니다."); return; }
      var on = res.enabled !== false && next;
      sw.classList.toggle("on", on);
      sw.setAttribute("aria-checked", on ? "true" : "false");
      toast(on ? "ok" : "info", on ? "골드섬이 열리기 10분 전에 디스코드로 알려드립니다." : "골드섬 알림을 껐습니다.");
    });
  }

  // ── 초대 수락: 캐릭터에 맞춰 역할 기본값 ───────────────
  function syncInvite(form) {
    var map = {};
    try { map = JSON.parse(form.dataset.supports || "{}"); } catch (err) { map = {}; }
    var cs = form.querySelector('select[name="character_name"]'), rs = form.querySelector('select[name="role"]');
    if (!cs || !rs) return;
    var isSupport = !!map[cs.value];
    var opt = rs.querySelector('option[value="support"]');
    if (opt) opt.disabled = !isSupport;
    if (!form.dataset.roleTouched) rs.value = isSupport ? "support" : "dps";
    else if (!isSupport && rs.value === "support") rs.value = "dps";
    form.__syncing = true;
    rs.dispatchEvent(new Event("change"));
    form.__syncing = false;
    var label = form.parentNode.querySelector("[data-inv-char]");
    if (label) label.textContent = cs.value;
  }
  document.addEventListener("change", function (e) {
    var form = e.target.closest && e.target.closest(".inv-form");
    if (!form) return;
    if (e.target.name === "role" && !form.__syncing) form.dataset.roleTouched = "1";
    if (e.target.name === "character_name") syncInvite(form);
  });
  // 선택칸을 한 번도 안 열고 바로 수락해도 역할이 캐릭터에 맞게 들어간다
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.classList && form.classList.contains("inv-form")) syncInvite(form);
  }, true);
})();
