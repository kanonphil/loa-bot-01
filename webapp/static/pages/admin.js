// 관리 화면 공용 스크립트 — 대화상자, 검색·필터, 난이도 편집, 유저 내보내기, 전체 공지, 시세 아이템.
// 순서 변경은 /static/admin-reorder.js. 확인 대화상자(uiConfirm)·토스트(showToast)는 공용 foundation을 쓴다.
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return [].slice.call((root || document).querySelectorAll(sel)); }
  function toast(kind, msg) { if (window.showToast) window.showToast(kind, msg); }
  function text(el, v) { if (el) el.textContent = v; }

  // 대화상자 안의 드롭다운은 입력칸처럼 폭을 꽉 채우는 게 의도다(늘어난 버튼이 아니라 폼 필드) — 규격 실측이 구분할 수 있게 표시
  // (themed-select는 DOMContentLoaded에서 트리거를 만든다 — 그 뒤에 붙도록 같은 이벤트에 등록)
  document.addEventListener("DOMContentLoaded", function () {
    $$(".ad-dlg .themed-select-trigger").forEach(function (t) { t.classList.add("is-block"); });
  });

  // ── 모달: data-dlg-open="#id" / [data-dlg-close] / Esc / 바깥 클릭 ──
  var openDlg = null;    // 열려 있는 .dlg-back(body에 붙은 래퍼)
  var openHolder = null; // 닫혀 있을 때 .dlg를 보관하는 .ad-modal
  var openerEl = null;
  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])';

  function visibleFocusables(root) {
    return $$(FOCUSABLE, root).filter(function (el) {
      return el.offsetParent !== null && !el.classList.contains("themed-select-native");
    });
  }
  function openModal(holder, from) {
    if (!holder || openDlg) return;
    if (window.uiPopup) window.uiPopup.close(false);
    var dlg = $(".dlg", holder);
    var wrap = document.createElement("div");
    wrap.className = "dlg-back";
    wrap.appendChild(dlg);
    document.body.appendChild(wrap);
    openDlg = wrap;
    openHolder = holder;
    openerEl = from || document.activeElement;
    var first = $("input:not([type=hidden]):not([disabled]), textarea, .themed-select-trigger", wrap) ||
      visibleFocusables(wrap).filter(function (b) { return !b.hasAttribute("data-dlg-close"); })[0] ||
      visibleFocusables(wrap)[0];
    if (first) first.focus();
  }
  function closeModal() {
    if (!openDlg) return;
    openHolder.appendChild($(".dlg", openDlg));
    openDlg.parentNode.removeChild(openDlg);
    openDlg = null;
    openHolder = null;
    if (openerEl && document.contains(openerEl) && openerEl.focus) openerEl.focus();
    openerEl = null;
  }
  window.adminModal = { open: openModal, close: closeModal };

  var downOnBackdrop = false;
  document.addEventListener("mousedown", function (e) { downOnBackdrop = !!openDlg && e.target === openDlg; });
  document.addEventListener("click", function (e) {
    var opener = e.target.closest && e.target.closest("[data-dlg-open]");
    if (opener) { e.preventDefault(); openModal($(opener.getAttribute("data-dlg-open")), opener); return; }
    if (e.target.closest && e.target.closest("[data-dlg-close]")) { closeModal(); return; }
    if (openDlg && e.target === openDlg && downOnBackdrop) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (!openDlg || e.defaultPrevented) return;
    if (e.key === "Escape") {
      // 그 위에 확인 대화상자가 떠 있으면 그쪽 Esc가 먼저 처리한다(캡처 단계에서 이미 막았다)
      var stack = $$(".dlg-back");
      if (stack[stack.length - 1] !== openDlg) return;
      e.preventDefault();
      closeModal();
    } else if (e.key === "Tab") {
      var f = visibleFocusables(openDlg);
      if (!f.length) return;
      var i = f.indexOf(document.activeElement);
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && (i === f.length - 1)) { e.preventDefault(); f[0].focus(); }
    }
  });

  // ── 검색 + KPI/역할 필터(표·목록 공통) ──
  var filters = new Map(); // root → {q, key, role}
  function stateFor(root) {
    if (!filters.has(root)) filters.set(root, { q: "", key: "", role: "" });
    return filters.get(root);
  }
  function applyFilter(root) {
    var st = stateFor(root);
    var itemSel = root.getAttribute("data-ad-item-sel") || "[data-row]";
    var q = st.q.trim().toLowerCase();
    var visible = 0;
    $$(itemSel, root).forEach(function (item) {
      var hay = (item.getAttribute("data-text") || item.textContent).toLowerCase();
      var show = !q || hay.indexOf(q) >= 0;
      if (show && st.key) {
        show = st.key === "problem" ? item.getAttribute("data-problem") === "1" : item.getAttribute("data-status") === st.key;
      }
      if (show && st.role) show = item.getAttribute("data-role") === st.role;
      item.hidden = !show;
      var next = item.nextElementSibling;
      if (next && next.classList.contains("ad-details-row") && !show) next.hidden = true;
      if (show) visible++;
    });
    var groupSel = root.getAttribute("data-ad-group-sel");
    if (groupSel) $$(groupSel, root).forEach(function (g) { g.hidden = !$$(itemSel, g).some(function (i) { return !i.hidden; }); });
    var card = root.closest(".ad-card") || root;
    var none = $(".ad-noresult", card);
    if (none) none.hidden = visible > 0;
  }
  $$("[data-ad-filter]").forEach(function (input) {
    var root = $(input.getAttribute("data-ad-filter"));
    if (!root) return;
    root.setAttribute("data-ad-item-sel", input.getAttribute("data-ad-item") || "[data-row]");
    if (input.hasAttribute("data-ad-group")) root.setAttribute("data-ad-group-sel", input.getAttribute("data-ad-group"));
    input.addEventListener("input", function () { stateFor(root).q = input.value; applyFilter(root); });
  });
  $$("[data-ad-kpi]").forEach(function (box) {
    var root = $(box.getAttribute("data-ad-kpi"));
    if (!root) return;
    box.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-key]");
      if (!btn) return;
      var st = stateFor(root);
      var on = btn.getAttribute("aria-pressed") !== "true";
      $$("button[data-key]", box).forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      st.key = on ? btn.getAttribute("data-key") : "";
      applyFilter(root);
    });
  });
  $$("[data-ad-role]").forEach(function (btn) {
    var root = $("#class-table");
    if (!root) return;
    btn.addEventListener("click", function () {
      $$("[data-ad-role]").forEach(function (b) {
        var on = b === btn;
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      stateFor(root).role = btn.getAttribute("data-ad-role");
      applyFilter(root);
    });
  });

  // ── 레이드: 난이도 추가/수정 대화상자 ──
  var diffForm = $("#diff-form");
  if (diffForm) {
    var confirmAttrs = ["data-confirm", "data-confirm-title", "data-confirm-skip-same", "data-confirm-original", "data-confirm-ok"];
    var savedAttrs = {};
    confirmAttrs.forEach(function (a) { savedAttrs[a] = diffForm.getAttribute(a); });
    var dlg = $("#dlg-diff");
    var f = function (name) { return diffForm.elements[name]; };
    var openDiff = function (tr, opener) {
      var edit = !!tr;
      text($("#dlg-diff-t"), edit ? tr.dataset.name + " 수정" : "난이도 추가");
      diffForm.action = edit ? "/admin/raids/difficulties/save" : "/admin/raids/difficulties/add";
      confirmAttrs.forEach(function (a) {
        if (edit && savedAttrs[a] !== null) diffForm.setAttribute(a, savedAttrs[a]); else diffForm.removeAttribute(a);
      });
      if (edit) diffForm.setAttribute("data-confirm-original", tr.dataset.name);
      f("old_difficulty").value = edit ? tr.dataset.name : "";
      f("difficulty").value = edit ? tr.dataset.name : "";
      f("min_level").value = edit ? tr.dataset.minLevel : "";
      f("total_slots").value = edit ? tr.dataset.totalSlots : "";
      f("party_split").value = edit ? tr.dataset.partySplit : "";
      f("gates").value = edit ? tr.dataset.gates : "1";
      f("clear_gold").value = edit ? tr.dataset.clearGold : "";
      openModal(dlg, opener);
    };
    document.addEventListener("click", function (e) {
      var editBtn = e.target.closest("[data-diff-edit]");
      if (editBtn) { openDiff(editBtn.closest("tr"), editBtn); return; }
      var addBtn = e.target.closest("[data-diff-add], #diff-add-empty");
      if (addBtn) openDiff(null, addBtn);
    });
  }

  // ── 유저: 상세 펼치기 / 내보내기 영향 범위 ──
  document.addEventListener("click", function (e) {
    var det = e.target.closest("[data-user-details]");
    if (!det) return;
    var id = det.getAttribute("data-user-details");
    var row = document.getElementById("ud-" + id);
    if (!row) return;
    var open = row.hidden;
    row.hidden = !open;
    det.setAttribute("aria-expanded", open ? "true" : "false");
    var cell = row.firstElementChild;
    if (open && !cell.getAttribute("data-loaded")) {
      cell.textContent = "불러오는 중…";
      fetch("/admin/users/" + encodeURIComponent(id) + "/details", { credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) { cell.innerHTML = html; cell.setAttribute("data-loaded", "1"); })
        .catch(function () { cell.textContent = "불러오지 못했습니다. 잠시 후 다시 눌러 주세요."; });
    }
  });

  var kickSeq = 0;
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-user-kick]");
    if (!btn) return;
    var id = btn.getAttribute("data-user-kick");
    var name = btn.getAttribute("data-name") || id;
    var box = $("#kick-impact");
    text($("#dlg-kick-t"), name + " 님을 길드 도구에서 내보낼까요?");
    $("#kick-form").action = "/admin/users/" + encodeURIComponent(id) + "/delete";
    box.innerHTML = '<span class="ad-meta">영향 범위를 불러오는 중…</span>';
    openModal($("#dlg-kick"), btn);
    var mine = ++kickSeq;
    fetch("/admin/users/" + encodeURIComponent(id) + "/impact", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) { if (mine === kickSeq) box.innerHTML = html; })
      .catch(function () {
        if (mine === kickSeq) box.innerHTML = "<div><span>영향 범위를 불러오지 못했습니다. 내보내면 캐릭터·API 키와 참여 중인 공대의 자리가 삭제됩니다.</span></div>";
      });
  });

  // ── 전체 공지: 미리보기 · 확인 · 진행률 ──
  var bc = $("#bc-form");
  if (bc) {
    var area = $("#bc-content"), preview = $("#bc-preview"), send = $("#bc-send");
    var progress = $("#bc-progress");
    var emptyText = preview.getAttribute("data-empty");
    var recipients = $("#broadcast").getAttribute("data-recipients");
    var update = function () {
      var v = area.value;
      text($("[data-bc-len]"), String(v.length));
      preview.textContent = v.trim() ? v : emptyText;
      preview.classList.toggle("is-empty", !v.trim());
      send.disabled = !v.trim() || progress.getAttribute("data-running") === "1";
    };
    area.addEventListener("input", update);
    update();

    var timer = null;
    var showProgress = function (sent, total, done) {
      progress.hidden = false;
      progress.classList.toggle("is-done", !!done);
      progress.setAttribute("data-running", done ? "0" : "1");
      text($("[data-bc-sent]", progress), String(sent));
      text($("[data-bc-total]", progress), String(total));
      text($("b", progress), done ? "발송 완료" : "발송 중");
      var bar = $(".ui-gauge i", progress);
      if (bar) bar.style.width = (total ? Math.min(100, Math.round(sent / total * 100)) : 0) + "%";
    };
    var poll = function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        fetch("/admin/notifications/broadcast-status", { credentials: "same-origin", headers: { Accept: "application/json" } })
          .then(function (r) { return r.json(); })
          .then(function (s) {
            showProgress(s.sent || 0, s.total || 0, !!s.done);
            if (s.done) {
              toast("ok", (s.total || 0) + "명 중 " + (s.sent || 0) + "명에게 DM을 보냈습니다. (DM을 막아둔 유저에게는 전달되지 않습니다)");
              update();
            } else poll();
          })
          .catch(function () { poll(); });
      }, 2000);
    };
    if (progress.getAttribute("data-running") === "1") poll();

    bc.addEventListener("submit", function (e) {
      e.preventDefault();
      if (send.getAttribute("aria-busy") === "true") return;
      var body = area.value.trim();
      if (!body) return;
      var shown = body.length > 160 ? body.slice(0, 160) + "…" : body;
      var n = recipients || "등록";
      window.uiConfirm({
        title: "등록 유저 " + n + "명 전원에게 DM을 보낼까요?",
        message: "\"" + shown + "\"\n보낸 DM은 되돌릴 수 없습니다.",
        ok: "보내기",
      }).then(function (ok) {
        if (!ok) return;
        send.setAttribute("aria-busy", "true");
        fetch(bc.action, {
          method: "POST", credentials: "same-origin",
          headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ content: body }).toString(),
        })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (!res.success) { toast("err", res.reason || "공지를 보내지 못했습니다."); return; }
            if (res.queued) {
              showProgress(res.sent || 0, res.total || 0, false);
              poll();
            } else {
              showProgress(res.sent || 0, res.total || 0, true);
              toast("ok", (res.total || 0) + "명 중 " + (res.sent || 0) + "명에게 DM을 보냈습니다. (DM을 막아둔 유저에게는 전달되지 않습니다)");
            }
          })
          .catch(function () { toast("err", "공지를 보내지 못했습니다. 잠시 후 상태를 확인해 주세요."); })
          .then(function () { send.removeAttribute("aria-busy"); update(); });
      });
    });
  }

  // ── 시세로 볼 아이템 ──
  var tracked = $("#tracked-form");
  if (tracked) {
    var chips = $("#tracked-chips"), input = $("#tracked-input"), empty = $("#tracked-empty");
    var max = parseInt($("#tracked").getAttribute("data-max") || "8", 10);
    var names = function () { return $$(".ad-tchip", chips).map(function (c) { return c.getAttribute("data-name"); }); };
    var refresh = function () {
      var n = names().length;
      text($("#tracked-count .num"), String(n));
      empty.hidden = n > 0;
      $("#tracked-add").disabled = n >= max;
    };
    var add = function () {
      var v = input.value.trim();
      if (!v) return;
      if (names().indexOf(v) >= 0) { toast("info", "이미 추가한 아이템입니다."); input.select(); return; }
      if (names().length >= max) { toast("err", "시세로 볼 아이템은 최대 " + max + "개입니다."); return; }
      var chip = document.createElement("span");
      chip.className = "ad-tchip";
      chip.setAttribute("data-name", v);
      var hidden = document.createElement("input");
      hidden.type = "hidden"; hidden.name = "names"; hidden.value = v;
      var label = document.createElement("span");
      label.textContent = v;
      var rm = document.createElement("button");
      rm.type = "button"; rm.setAttribute("data-remove", ""); rm.setAttribute("aria-label", v + " 빼기"); rm.innerHTML = "&times;";
      chip.appendChild(hidden); chip.appendChild(label); chip.appendChild(rm);
      chips.appendChild(chip);
      input.value = "";
      input.focus();
      refresh();
    };
    $("#tracked-add").addEventListener("click", add);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); add(); } });
    chips.addEventListener("click", function (e) {
      var rm = e.target.closest("[data-remove]");
      if (!rm) return;
      rm.closest(".ad-tchip").remove();
      refresh();
      input.focus();
    });
    refresh();
  }
})();
