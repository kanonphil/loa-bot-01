// 홈(/main) 동작 — 숙제 칸 체크·난이도(▾) 저장·보기 전환·익스트림·공대 탭·골드섬 스위치·초대 수락 보조.
// 메뉴(난이도·레이드 고르기·익스트림 캐릭터·공대 참여 캐릭터)는 ui.js의 [data-menu-trigger] 위임(↑↓·Esc·포커스 복귀)을 쓴다.
// 모든 핸들러는 document 위임이다: party-live.js가 SSE로 .page-content를 통째로 바꿔 끼워도 그대로 동작한다.
// 바꿔 끼우면 이 스크립트가 다시 실행되므로 보기 설정(applyPrefs)은 가드 앞에서 매번 다시 적용한다.
(function () {
  var PREF_KEY = "loa.homeHw"; // {view: "char"|"raid", left: bool} — 이 브라우저에서만 기억하는 보기 설정

  function readPrefs() {
    try { return JSON.parse(localStorage.getItem(PREF_KEY) || "{}") || {}; } catch (e) { return {}; }
  }
  function writePrefs(p) {
    try { localStorage.setItem(PREF_KEY, JSON.stringify(p)); } catch (e) { /* 저장 못 해도 이번 화면에서는 바뀐다 */ }
  }
  function setView(view) {
    var hw = document.getElementById("hw");
    if (!hw) return;
    [].forEach.call(hw.querySelectorAll("[data-hw-view]"), function (b) {
      b.setAttribute("aria-pressed", b.dataset.hwView === view ? "true" : "false");
    });
    [].forEach.call(hw.querySelectorAll("[data-hw-panel]"), function (p) { p.hidden = p.dataset.hwPanel !== view; });
  }
  function setLeft(on) {
    var hw = document.getElementById("hw");
    if (!hw) return;
    hw.classList.toggle("is-left", on);
    var b = hw.querySelector("[data-hw-left]");
    if (b) b.setAttribute("aria-pressed", on ? "true" : "false");
  }
  function applyPrefs() {
    var p = readPrefs();
    setView(p.view === "raid" ? "raid" : "char");
    setLeft(!!p.left);
  }
  window.homeApplyPrefs = applyPrefs;
  applyPrefs();

  if (window.__homeInit) return;
  window.__homeInit = true;

  var ERR_NET = "연결하지 못했습니다. 잠시 후 다시 시도해주세요.";
  var busy = {};

  // ── 공통 ──────────────────────────────────────────────
  function toast(kind, msg, opts) { if (window.showToast) window.showToast(kind, msg, opts); }
  function esc(v) { return String(v).replace(/\\/g, "\\\\").replace(/"/g, '\\"'); }
  function all(sel, root) { return [].slice.call((root || document).querySelectorAll(sel)); }

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

  function shake(els) {
    els.forEach(function (el) {
      el.classList.remove("is-err");
      void el.offsetWidth; // 연달아 실패해도 다시 흔들리게
      el.classList.add("is-err");
      setTimeout(function () { el.classList.remove("is-err"); }, 900);
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
        applyPrefs();
        if (window.refreshNavBadges) window.refreshNavBadges();
        if (window.initThemedSelects) window.initThemedSelects();
      })
      .catch(function () { window.location.reload(); });
  }

  // ── 숙제 칸·칩 상태 ───────────────────────────────────
  // 같은 캐릭터·레이드의 칸(캐릭터별)과 칩(레이드별)은 항상 같이 바뀐다.
  function itemsFor(char, raid) {
    return all("[data-hw-item]").filter(function (el) { return el.dataset.char === char && el.dataset.raid === raid; });
  }
  function hitOf(el) { return el.matches("[data-hw-hit]") ? el : el.querySelector("[data-hw-hit]"); }

  function hitLabel(el, diff) {
    return el.dataset.char + " · " + el.dataset.raid + " " + diff + " 완료";
  }

  function setDone(char, raid, doneDiff) {
    itemsFor(char, raid).forEach(function (el) {
      if (doneDiff) el.dataset.diff = doneDiff;
      el.dataset.done = doneDiff || "";
      el.classList.toggle("is-done", !!doneDiff);
      var hit = hitOf(el);
      if (hit) hit.setAttribute("aria-pressed", doneDiff ? "true" : "false");
      var diff = el.dataset.diff;
      var lbl = el.querySelector("[data-done-label]");
      if (lbl) lbl.textContent = diff + " 클리어";
      syncDiffLabels(el, diff);
    });
    syncRaidRow(raid);
  }

  function syncDiffLabels(el, diff) {
    var small = el.querySelector("[data-chip-diff]");
    if (small) small.textContent = diff;
    var dd = el.querySelector(".hw-dd");
    if (dd) {
      var l = dd.querySelector("[data-dd-label]");
      if (l) l.textContent = diff; else dd.textContent = diff;
      if (dd.tagName === "BUTTON") dd.setAttribute("aria-label", el.dataset.raid + " 난이도: " + diff);
      var menu = dd.getAttribute("aria-controls") && document.getElementById(dd.getAttribute("aria-controls"));
      if (menu) all("[data-hw-pick]", menu).forEach(function (m) {
        m.setAttribute("aria-checked", m.dataset.hwPick === diff ? "true" : "false");
      });
    }
    var hit = el.classList.contains("hw-tile") ? hitOf(el) : null;
    if (hit) hit.setAttribute("aria-label", hitLabel(el, diff));
  }

  function setDiff(char, raid, diff) {
    itemsFor(char, raid).forEach(function (el) {
      el.dataset.diff = diff;
      syncDiffLabels(el, diff);
    });
  }

  function setBusy(char, raid, on) {
    itemsFor(char, raid).forEach(function (el) {
      // aria-busy는 쓰지 않는다 — 공용 규칙이 버튼(칩)의 글자를 숨기고 자체 스피너를 그린다. 원 스피너는 .is-busy로.
      el.classList.toggle("is-busy", on);
    });
  }

  function doneFromCompletions(raid, completions) {
    for (var i = 0; i < completions.length; i++) {
      var k = completions[i], cut = k.lastIndexOf("_");
      if (cut > 0 && k.slice(0, cut) === raid) return k.slice(cut + 1);
    }
    return "";
  }

  // 레이드별 보기 한 줄의 "남은 캐릭터 N"과 다 끝남 표시
  function syncRaidRow(raid) {
    all("[data-hw-raid]").forEach(function (row) {
      if (row.dataset.hwRaid !== raid) return;
      var chips = all(".hw-chip", row), left = chips.filter(function (c) { return !c.dataset.done; }).length;
      var n = row.querySelector("[data-left]");
      if (n) n.textContent = left;
      row.classList.toggle("is-clear", left === 0);
    });
  }

  // 캐릭터 줄의 점·숫자, 카드 머리줄·게이지, 위 숫자 카드
  function updateCounts(char, done, total) {
    all("[data-row]").forEach(function (row) {
      if (row.dataset.row !== char) return;
      if (typeof done !== "number" || typeof total !== "number") {
        var tiles = all(".hw-tile[data-hw-item]", row);
        total = tiles.length;
        done = tiles.filter(function (t) { return !!t.dataset.done; }).length;
      }
      row.dataset.done = done; row.dataset.total = total;
      all("[data-hw-dots] i", row).forEach(function (dot, i) { dot.classList.toggle("on", i < done); });
      var c = row.querySelector("[data-char-count]");
      if (c) c.textContent = done + "/" + total;
    });
    var d = 0, t = 0;
    all("[data-hw-panel='char'] [data-row]").forEach(function (row) {
      d += Number(row.dataset.done) || 0; t += Number(row.dataset.total) || 0;
    });
    var dEl = document.querySelector("[data-hw-done]"), tEl = document.querySelector("[data-hw-total]");
    if (dEl) dEl.textContent = d;
    if (tEl) tEl.textContent = t;
    var gauge = document.querySelector("#hw .ui-gauge");
    if (gauge && gauge.firstElementChild) {
      gauge.firstElementChild.style.width = (t ? Math.round(d / t * 100) : 0) + "%";
      gauge.classList.toggle("is-ok", t > 0 && d >= t);
    }
    var stat = document.querySelector('[data-stat="homework"]');
    if (stat) {
      stat.querySelector("[data-stat-value]").textContent = d;
      stat.querySelector("[data-stat-unit]").textContent = "/ " + t;
      stat.classList.toggle("is-ok", t > 0 && d >= t);
    }
  }

  function refreshGold() {
    if (!document.getElementById("home-gold")) return;
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
    if (res.completions) setDone(char, raid, doneFromCompletions(raid, res.completions));
    updateCounts(char, res.done, res.total);
    refreshGold();
  }

  // 다른 난이도로 바꾸면 봇이 기존 체크를 대체한다 — 되돌리기는 새 체크를 끄고 이전 난이도를 다시 켠다.
  function undoToggle(char, raid, diff, prevDone, completed, label) {
    var chain = toggleRequest(char, raid, diff);
    if (completed && prevDone && prevDone !== diff) {
      chain = chain.then(function (res) { return res.success ? toggleRequest(char, raid, prevDone) : res; });
    }
    chain.then(function (res) {
      if (!res.success) { toast("err", res.reason || "되돌리지 못했습니다."); return; }
      commit(char, raid, res);
      toast("info", label + " 되돌렸습니다.");
    });
  }

  // 칸을 누르면 바로 체크된 모양으로 바꾸고(처리 중엔 원이 돈다), 실패하면 되돌리고 흔든 뒤 토스트.
  function doToggle(item) {
    var char = item.dataset.char, raid = item.dataset.raid, short = item.dataset.short || raid;
    var key = char + "\n" + raid;
    if (busy[key]) return;
    busy[key] = true;
    var prevDone = item.dataset.done || "";
    var diff = prevDone || item.dataset.diff;
    setDone(char, raid, prevDone ? "" : diff);
    setBusy(char, raid, true);
    toggleRequest(char, raid, diff).then(function (res) {
      setBusy(char, raid, false);
      delete busy[key];
      if (!res.success) {
        setDone(char, raid, prevDone);
        shake(itemsFor(char, raid));
        toast("err", res.reason || "체크하지 못했습니다.");
        return;
      }
      commit(char, raid, res);
      var label = char + " · " + short + " " + diff;
      toast(res.completed ? "ok" : "info", label + (res.completed ? " 완료" : " 완료 취소"), {
        actionLabel: "되돌리기",
        onAction: function () { undoToggle(char, raid, diff, prevDone, res.completed, label); },
      });
    });
  }

  // ── 난이도(▾) 고르기 — 바로 바꾸고 저장, 실패하면 되돌린다 ──
  function pickDifficulty(item, diff) {
    var menu = item.closest(".menu");
    var trigger = menu && document.querySelector('[aria-controls="' + esc(menu.id) + '"]');
    var tile = trigger && trigger.closest("[data-hw-item]");
    if (window.uiPopup) window.uiPopup.close(true);
    if (!tile) return;
    var char = tile.dataset.char, raid = tile.dataset.raid, prev = tile.dataset.diff;
    if (prev === diff) return;
    var key = "d\n" + char + "\n" + raid;
    if (busy[key]) return;
    busy[key] = true;
    setDiff(char, raid, diff);
    post("/raid-check/difficulty-pref", { character_name: char, raid_name: raid, difficulty: diff }, true).then(function (res) {
      delete busy[key];
      if (!res.success) {
        setDiff(char, raid, prev);
        shake(itemsFor(char, raid));
        toast("err", res.reason || "난이도를 저장하지 못했습니다.");
      }
    });
  }

  // ── 익스트림(원정대 주 1회) ───────────────────────────
  function extremeSet(tile, diff, char, quiet) {
    var raid = tile.dataset.xRaid, short = tile.dataset.short || raid;
    var key = "x\n" + raid;
    if (busy[key]) return;
    busy[key] = true;
    tile.classList.add("is-busy");
    post("/raid-check/extreme/set", { raid_name: raid, difficulty: diff, character_name: char }).then(function (res) {
      tile.classList.remove("is-busy");
      delete busy[key];
      if (!res.success) { shake([tile]); toast("err", res.reason || "체크하지 못했습니다."); return; }
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

  function extremeClear(tile) {
    var raid = tile.dataset.xRaid, short = tile.dataset.short || raid;
    var prevDiff = tile.dataset.diff, prevChar = tile.dataset.xBy;
    var key = "x\n" + raid;
    if (busy[key]) return;
    busy[key] = true;
    tile.classList.add("is-busy");
    post("/raid-check/extreme/clear", { raid_name: raid }).then(function (res) {
      tile.classList.remove("is-busy");
      delete busy[key];
      if (!res.success) { shake([tile]); toast("err", res.reason || "해제하지 못했습니다."); return; }
      refreshContent().then(function () {
        toast("info", short + " 클리어 기록을 해제했습니다.", {
          actionLabel: "되돌리기",
          onAction: function () {
            var fresh = all(".hw-tile[data-x-raid]").filter(function (s) { return s.dataset.xRaid === raid && s.dataset.diff === prevDiff; })[0];
            if (fresh && prevChar) extremeSet(fresh, prevDiff, prevChar, true);
          },
        });
      });
    });
  }

  // ── 클릭 위임 ─────────────────────────────────────────
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t.closest) return;

    var pick = t.closest("[data-hw-pick]");
    if (pick) { pickDifficulty(pick, pick.dataset.hwPick); return; }

    var xpick = t.closest("[data-x-pick]");
    if (xpick) {
      var xm = xpick.closest(".menu");
      var xtrig = xm && document.querySelector('[aria-controls="' + esc(xm.id) + '"]');
      if (window.uiPopup) window.uiPopup.close(false);
      var xt = xtrig && xtrig.closest(".hw-tile");
      if (xt) extremeSet(xt, xpick.dataset.xDiff, xpick.dataset.xPick);
      return;
    }

    var xhit = t.closest(".hw-tile[data-x-raid] .hw-hit");
    if (xhit) {
      var xtile = xhit.closest(".hw-tile");
      if (xhit.getAttribute("aria-disabled") === "true") return;
      if (xhit.hasAttribute("data-x-clear")) extremeClear(xtile);
      else if (xhit.dataset.xChar) extremeSet(xtile, xtile.dataset.diff, xhit.dataset.xChar);
      return; // 캐릭터가 여럿이면 ui.js가 메뉴를 연다
    }

    var hit = t.closest("[data-hw-hit]");
    if (hit) { doToggle(hit.closest("[data-hw-item]")); return; }

    var view = t.closest("[data-hw-view]");
    if (view) {
      setView(view.dataset.hwView);
      var p = readPrefs(); p.view = view.dataset.hwView; writePrefs(p);
      return;
    }

    var left = t.closest("[data-hw-left]");
    if (left) {
      var on = left.getAttribute("aria-pressed") !== "true";
      setLeft(on);
      var lp = readPrefs(); lp.left = on; writePrefs(lp);
      return;
    }

    var ptab = t.closest("[data-hp-tab]");
    if (ptab) {
      var card = ptab.closest(".hc-party");
      all("[data-hp-tab]", card).forEach(function (b) { b.setAttribute("aria-pressed", b === ptab ? "true" : "false"); });
      all("[data-hp-panel]", card).forEach(function (pn) { pn.hidden = pn.dataset.hpPanel !== ptab.dataset.hpTab; });
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

  // ── 골드섬 알림 ───────────────────────────────────────
  function toggleGoldSwitch(sw) {
    if (sw.getAttribute("aria-busy") === "true") return;
    var next = sw.getAttribute("aria-checked") !== "true";
    sw.setAttribute("aria-busy", "true");
    post("/loa/gold-island-subscription", { enabled: next }, true).then(function (res) {
      sw.removeAttribute("aria-busy");
      if (!res.success) { toast("err", res.reason || "알림 설정을 바꾸지 못했습니다."); return; }
      var on = res.enabled !== false && next;
      window.uiSwitch(sw, on);
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
