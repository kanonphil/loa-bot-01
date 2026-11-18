// 공대 화면 스크립트 — 목록(참여 칸) · 공대 열기 · 상세(참여 줄, 팝오버)를 한 파일에서 data-pt 값으로 나눠 쓴다.
// party-live.js가 .page-content를 통째로 바꿔 끼우고 <script>를 다시 실행하므로, 이 파일은 여러 번 실행돼도
// document 전체에 리스너를 겹쳐 달지 않고 root 안의 요소에만 붙인다.
(function () {
  "use strict";
  var root = document.querySelector("[data-pt]");
  if (!root) return;
  var kind = root.getAttribute("data-pt");

  function $(sel, scope) { return (scope || root).querySelector(sel); }
  function $$(sel, scope) { return [].slice.call((scope || root).querySelectorAll(sel)); }
  function fire(el) { el.dispatchEvent(new Event("change", { bubbles: true })); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // ── 목록: 고른 캐릭터에 맞춰 역할·파티를 채운다 ───────────────
  function initList() {
    $$("[data-pt-join]").forEach(function (form) {
      var select = form.elements.character_name;
      var role = form.elements.role;
      var group = form.elements.party_group;
      function sync() {
        var opt = select.options[select.selectedIndex];
        if (!opt) return;
        role.value = opt.getAttribute("data-role") || "dps";
        var g = opt.getAttribute("data-group");
        group.value = g || "";
        group.disabled = !g; // 비활성 필드는 제출되지 않는다 — 분할 없는 공대는 party_group을 보내지 않는다
      }
      select.addEventListener("change", sync);
      sync();
    });
  }

  // ── 상세 ────────────────────────────────────────────────
  function initDetail() {
    // 참여 줄: 캐릭터 → 역할 → 파티 순으로 자동 채움
    var charSelect = $("#join-character-select");
    if (charSelect) {
      var roleSelect = $("#join-role-select");
      var groupSelect = $("#join-group-select");
      var mapEl = $("#join-support-map");
      var isSupport = {};
      try { isSupport = JSON.parse(mapEl.textContent); } catch (e) { /* 없으면 전부 딜러 */ }
      var supportOption = roleSelect.querySelector('option[value="support"]');
      var syncRole = function () {
        var sup = !!isSupport[charSelect.value];
        supportOption.disabled = !sup;
        if (sup) roleSelect.value = "support";
        else if (roleSelect.value === "support") roleSelect.value = "dps";
        fire(roleSelect);
      };
      // 서포터는 서포터 없는 파티를, 딜러는 서포터가 있는 파티를 먼저 — 직접 바꿀 수 있다(기본값일 뿐)
      var syncGroup = function () {
        if (!groupSelect) return;
        var open = [].slice.call(groupSelect.options).filter(function (o) { return !o.disabled; });
        var want = roleSelect.value === "support"
          ? open.filter(function (o) { return o.dataset.hasSupport !== "1"; })
          : open.filter(function (o) { return o.dataset.hasSupport === "1"; });
        var pick = (want[0] || open[0]);
        if (pick && groupSelect.value !== pick.value) { groupSelect.value = pick.value; fire(groupSelect); }
      };
      charSelect.addEventListener("change", function () { syncRole(); syncGroup(); });
      roleSelect.addEventListener("change", syncGroup);
      syncRole();
      syncGroup();

      // 빈 자리를 누르면 그 파티로 참여 칸을 채운다
      $$("[data-pick-group]").forEach(function (slot) {
        function pick() {
          if (!groupSelect) return;
          groupSelect.value = slot.getAttribute("data-pick-group");
          fire(groupSelect);
          $$("[data-pick-group]").forEach(function (s) { s.classList.remove("is-picked"); });
          slot.classList.add("is-picked");
          var bar = $("#join");
          if (bar && bar.scrollIntoView) bar.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }
        slot.classList.add("is-pickable");
        slot.addEventListener("click", pick);
        slot.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
      });
    }

    // 팝오버(일정 변경 · 초대) — 한 번에 하나, Esc·바깥 클릭으로 닫고 연 버튼으로 포커스가 돌아온다
    function place(pop, opener) {
      var base = root.getBoundingClientRect();
      var r = opener.getBoundingClientRect();
      var width = pop.offsetWidth || 320;
      var left = Math.max(0, Math.min(r.left - base.left, base.width - width));
      pop.style.left = left + "px";
      pop.style.top = (r.bottom - base.top + 6) + "px";
    }
    function openPop(pop, opener) {
      if (!pop) return;
      pop.hidden = false;
      opener.setAttribute("aria-expanded", "true");
      place(pop, opener);
      if (window.uiPopup) {
        window.uiPopup.open({
          el: pop, opener: opener,
          close: function () { pop.hidden = true; opener.setAttribute("aria-expanded", "false"); },
        });
      }
      var first = pop.querySelector("input:not([type=hidden]), select, button");
      if (first) first.focus();
    }
    $$("[data-pop-open]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var pop = document.getElementById(btn.getAttribute("data-pop-open"));
        if (pop && !pop.hidden && window.uiPopup) { window.uiPopup.close(true); return; }
        openPop(pop, btn);
      });
    });
    $$("[data-invite-slot]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var pop = $("#invite-pop");
        if (!pop) return;
        if (!pop.hidden && window.uiPopup) { window.uiPopup.close(true); return; }
        var slot = $("#invite-slot");
        if (slot) slot.value = btn.getAttribute("data-invite-slot");
        var title = $("#invite-title");
        if (title) title.textContent = btn.getAttribute("data-invite-label") + " 자리 초대";
        openPop(pop, btn);
      });
    });
    $$("[data-pop-close]").forEach(function (btn) {
      btn.addEventListener("click", function () { if (window.uiPopup) window.uiPopup.close(true); });
    });

    // 메뉴 항목이 확인 대화상자를 열면 메뉴가 닫혀 버려, 대화상자를 닫을 때 돌려줄 포커스 자리가 사라진다 —
    // 그때는 메뉴를 연 ⋯ 버튼으로 포커스를 돌려준다.
    $$(".pt-slot .menu").forEach(function (menu) {
      menu.addEventListener("click", function () {
        window.__ptMenuOpener = document.querySelector('[aria-controls="' + menu.id + '"]');
      }, true);
    });
    if (!window.__ptDialogReturn && window.MutationObserver) {
      window.__ptDialogReturn = true;
      new MutationObserver(function (records) {
        var closed = records.some(function (r) {
          return [].some.call(r.removedNodes, function (n) { return n.classList && n.classList.contains("dlg-back"); });
        });
        if (!closed) return;
        setTimeout(function () {
          var a = document.activeElement, t = window.__ptMenuOpener;
          if ((!a || a === document.body) && t && document.contains(t)) t.focus();
        }, 0);
      }).observe(document.body, { childList: true });
    }

    // 일정 변경 폼 — 날짜 선택기는 팝오버 안에 붙인다(static)
    var dtInput = $("#reschedule-datetime-input");
    if (dtInput && window.flatpickr && window.initPartyDatetimePicker) {
      var picker = window.initPartyDatetimePicker("#reschedule-datetime-input", { minDate: null, static: true });
      var initial = dtInput.getAttribute("data-initial");
      if (initial) picker.setDate(new Date(initial), true);
      window.attachQuickAdjustButtons(picker, "#reschedule-quick-adjust");
      var form = $("#reschedule-form");
      form.addEventListener("submit", function (e) {
        if (!dtInput.value) {
          e.preventDefault();
          if (window.showToast) window.showToast("error", "일정을 선택해 주세요.");
        }
      }, true);
    }
  }

  // ── 공대 열기 ───────────────────────────────────────────
  function initCreate() {
    var data = {};
    try { data = JSON.parse($("#pt-create-data").textContent); } catch (e) { /* 빈 값 */ }
    var form = $("#party-create-form");
    var raidIn = $("#raid-name-input"), diffIn = $("#difficulty-input"), profIn = $("#proficiency-input"), roleIn = $("#role-input");
    var memoIn = $("#memo-input");
    var dtIn = $("#scheduled-datetime-input");
    var submit = $("#party-create-submit"), hint = $("#submit-hint");
    var charList = $("#char-list");
    var picker = window.flatpickr ? window.initPartyDatetimePicker("#scheduled-datetime-input", { static: true }) : null;
    var state = { slots: 0, split: 0, min: 0, short: "", options: [], userPicked: false, custom: false };
    var checkTimer = null, checkCtl = null;

    function pad(n) { return String(n).padStart(2, "0"); }
    function formatValue(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes()); }
    function dtValue() { return dtIn.value || ""; }

    // 단계 번호 표시
    function markSteps() {
      $("#k1").classList.toggle("is-done", !!raidIn.value);
      $("#k2").classList.toggle("is-done", !!dtValue());
      var ready = !!(raidIn.value && diffIn.value && dtValue());
      submit.disabled = !ready;
      hint.hidden = ready;
    }

    // 레이드·난이도
    function pickDifficulty(btn) {
      $$(".pt-seg button[aria-pressed='true']").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
      $$(".pt-rcard.is-on").forEach(function (c) { c.classList.remove("is-on"); });
      btn.setAttribute("aria-pressed", "true");
      btn.closest(".pt-rcard").classList.add("is-on");
      raidIn.value = btn.dataset.raid;
      diffIn.value = btn.dataset.diff;
      state.slots = Number(btn.dataset.slots);
      state.split = Number(btn.dataset.split);
      state.min = Number(btn.dataset.min);
      state.short = btn.dataset.short;
      refresh();
    }
    $$(".pt-seg button").forEach(function (b) { b.addEventListener("click", function () { if (!b.disabled) pickDifficulty(b); }); });

    function findDiffButton(raid, diff) {
      return $$(".pt-seg button").filter(function (b) { return b.dataset.raid === raid && b.dataset.diff === diff && !b.disabled; })[0];
    }

    // 일정 프리셋
    var presetBtns = $$("[data-preset]");
    var customBtn = $("[data-preset-custom]");
    var customBox = $("#custom-when");
    function syncPresetUi() {
      var v = dtValue();
      var hit = false;
      presetBtns.forEach(function (b) {
        var on = !state.custom && b.dataset.preset === v;
        hit = hit || on;
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      var customOn = state.custom || (!!v && !hit);
      customBtn.classList.toggle("on", customOn);
      customBtn.setAttribute("aria-pressed", customOn ? "true" : "false");
      customBox.hidden = !customOn;
    }
    function setTime(value) {
      if (picker) picker.setDate(value, true); else dtIn.value = value;
      refresh();
    }
    presetBtns.forEach(function (b) {
      b.addEventListener("click", function () { state.custom = false; setTime(b.dataset.preset); });
    });
    customBtn.addEventListener("click", function () {
      state.custom = true;
      syncPresetUi();
      if (picker) picker.open();
    });
    if (picker) picker.config.onChange.push(function () { refresh(); });
    else dtIn.addEventListener("change", refresh);

    // 숙련도
    $$("[data-prof]", $(".pt-chips")).forEach(function (b) {
      b.addEventListener("click", function () { setProf(b.dataset.prof); });
    });
    function setProf(v) {
      profIn.value = v;
      $$(".pt-chips [data-prof]").forEach(function (b) {
        var on = b.dataset.prof === v;
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      renderPreview();
    }

    // 다시 열기
    $$("[data-reopen]").forEach(function (b) {
      b.addEventListener("click", function () {
        var btn = findDiffButton(b.dataset.raid, b.dataset.diff);
        if (btn) pickDifficulty(btn);
        if (b.dataset.prof) setProf(b.dataset.prof);
        memoIn.value = b.dataset.memo || "";
        state.custom = false;
        setTime(b.dataset.time);
        state.userPicked = false;
      });
    });

    // 캐릭터 목록(추천·불가 사유)
    function currentChoice() {
      var c = charList.querySelector("input:checked");
      return c ? c.value : "";
    }
    function renderChars(options) {
      var keep = state.userPicked ? currentChoice() : null;
      charList.textContent = "";
      var chosen = null;
      var ordered = options.slice();
      ordered.forEach(function (o) {
        var label = el("label", "pt-copt" + (o.ok ? "" : " is-dis"));
        var input = el("input");
        input.type = "radio"; input.name = "character_name"; input.value = o.name;
        input.disabled = !o.ok;
        input.dataset.role = o.role;
        var name = el("span", "pt-copt-name");
        name.appendChild(el("b", "", o.name));
        name.appendChild(el("span", "pt-meta", o.cls + " · " + (o.level != null ? Number(o.level).toFixed(1) : "-")));
        var why;
        if (!o.ok) why = o.reason;
        else {
          var parts = [];
          if (o.recommended) parts.push("추천");
          parts.push(o.is_support ? "서포터" : "딜러");
          if (o.note) parts.push(o.note);
          why = parts.join(" · ");
        }
        label.appendChild(input); label.appendChild(el("span", "pt-dot")); label.appendChild(name); label.appendChild(el("span", "pt-copt-why", why));
        charList.appendChild(label);
        if (o.ok && ((keep && keep === o.name) || (keep === null && o.recommended))) chosen = input;
      });
      var later = el("label", "pt-copt");
      var li = el("input"); li.type = "radio"; li.name = "character_name"; li.value = "";
      later.appendChild(li); later.appendChild(el("span", "pt-dot"));
      var ln = el("span", "pt-copt-name"); ln.appendChild(el("b", "", "나중에 직접 참여"));
      later.appendChild(ln); later.appendChild(el("span", "pt-copt-why", "파티장만 하고 자리는 비워 둠"));
      charList.appendChild(later);
      if (keep === "") chosen = li;
      if (!chosen) chosen = li;
      chosen.checked = true;
      syncChars();
    }
    function syncChars() {
      $$(".pt-copt", charList).forEach(function (l) {
        var i = l.querySelector("input");
        l.classList.toggle("is-on", i.checked);
      });
      var c = charList.querySelector("input:checked");
      roleIn.value = c && c.value && c.dataset.role ? c.dataset.role : "dps";
      renderPreview();
    }
    charList.addEventListener("change", function () { state.userPicked = true; syncChars(); });

    // 일정·중복 안내 + 추천 계산 — 서버가 한 번에 계산한다
    function refresh() {
      markSteps();
      syncPresetUi();
      renderPreview();
      clearTimeout(checkTimer);
      checkTimer = setTimeout(runCheck, 150);
    }
    function runCheck() {
      if (checkCtl) checkCtl.abort();
      var raid = raidIn.value, diff = diffIn.value, when = dtValue();
      if (!raid && !when) return;
      checkCtl = window.AbortController ? new AbortController() : null;
      var url = "/parties/create/check?raid_name=" + encodeURIComponent(raid) + "&difficulty=" + encodeURIComponent(diff) + "&scheduled_datetime=" + encodeURIComponent(when);
      fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" }, signal: checkCtl ? checkCtl.signal : undefined })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(applyCheck)
        .catch(function () { /* 안내가 없어도 열 수는 있다 */ });
    }
    function applyCheck(res) {
      $("#reset-label").textContent = res.reset.label;
      $("#warn-reset").hidden = !res.reset.next_week;
      var dup = $("#warn-dup");
      if (res.duplicates && res.duplicates.length) {
        var d = res.duplicates[0];
        var span = dup.querySelector("span");
        span.textContent = "";
        span.appendChild(el("b", "", "같은 시간대에 " + d.title + "이 이미 모집 중"));
        span.appendChild(document.createTextNode(" · " + (d.leader ? d.leader + " 님 공대 " : "") + d.filled + "/" + d.total + " · " + d.when + (res.duplicates.length > 1 ? " 외 " + (res.duplicates.length - 1) + "개" : "")));
        dup.querySelector("a").href = "/parties/" + encodeURIComponent(d.message_id);
        dup.hidden = false;
      } else {
        dup.hidden = true;
      }
      if (res.has_summary && raidIn.value) {
        state.options = res.options;
        renderChars(res.options);
      }
    }

    // 미리보기
    function renderPreview() {
      var title = $("#prev-title"), meta = $("#prev-meta"), slots = $("#prev-slots");
      var leader = $("#prev").dataset.leader;
      if (!raidIn.value) {
        title.textContent = "레이드를 고르세요";
        meta.textContent = "일정 · 최소 레벨 · 파티장";
        slots.textContent = "";
        $("#prev-comp").textContent = "딜 0/0 · 폿 0/0";
        $("#prev-bal").textContent = "";
        return;
      }
      title.textContent = raidIn.value + " " + diffIn.value + (profIn.value ? " · " + profIn.value : "");
      var when = "";
      if (picker && picker.selectedDates[0]) {
        var d = picker.selectedDates[0];
        when = (d.getMonth() + 1) + "/" + d.getDate() + " (" + "일월화수목금토"[d.getDay()] + ") " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + " · ";
      }
      meta.textContent = when + "최소 " + state.min + " · 파티장 " + leader;
      var choice = charList.querySelector("input:checked");
      var me = choice && choice.value ? { name: choice.value, role: choice.dataset.role || "dps" } : null;
      var total = state.slots, supTotal = Math.max(1, Math.floor(total / 4)), dpsTotal = total - supTotal;
      slots.textContent = "";
      for (var i = 0; i < total; i++) {
        var gno = state.split ? Math.floor(i / state.split) + 1 : null;
        var prefix = gno ? gno + " " : "";
        var span = el("span", i === 0 && me ? "is-me" : "", prefix + (i === 0 && me ? me.name + " (" + (me.role === "support" ? "폿" : "딜") + ")" : "빈 자리"));
        slots.appendChild(span);
      }
      var dps = me && me.role !== "support" ? 1 : 0, sup = me && me.role === "support" ? 1 : 0;
      $("#prev-comp").textContent = "딜 " + dps + "/" + dpsTotal + " · 폿 " + sup + "/" + supTotal;
      var bal = $("#prev-bal");
      bal.textContent = "";
      for (var k = 0; k < dpsTotal; k++) bal.appendChild(el("span", k < dps ? "is-dps" : ""));
      for (var s = 0; s < supTotal; s++) bal.appendChild(el("span", s < sup ? "is-sup" : ""));
    }

    form.addEventListener("submit", function (e) {
      // flatpickr가 원본 입력을 숨겨 브라우저 required 말풍선이 안 뜬다 — 직접 확인
      if (!raidIn.value) { e.preventDefault(); if (window.showToast) window.showToast("error", "레이드와 난이도를 골라 주세요."); return; }
      if (!dtValue()) { e.preventDefault(); if (window.showToast) window.showToast("error", "일정을 선택해 주세요."); }
    });

    // 처음 상태: 실패 후 되돌아온 값 → 없으면 비어 있음
    var preset = data.preset || {};
    if (preset.raid) {
      var btn = findDiffButton(preset.raid, preset.difficulty);
      if (btn) pickDifficulty(btn);
    }
    if (preset.scheduled_datetime) { setTime(preset.scheduled_datetime); }
    if (preset.character_name) state.userPicked = true;
    refresh();
    if (preset.character_name) {
      var want = [].slice.call(charList.querySelectorAll("input")).filter(function (i) { return i.value === preset.character_name; })[0];
      if (want && !want.disabled) { want.checked = true; syncChars(); }
    }
  }

  if (kind === "list") initList();
  else if (kind === "detail") initDetail();
  else if (kind === "create") initCreate();
})();
