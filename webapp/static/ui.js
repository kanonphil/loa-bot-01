// 공용 UI 동작 — 메뉴 접기, 팝업 메뉴(↑↓·Esc), 확인 대화상자, 탭 화살표 이동, 탭 제목의 안 읽은 수.
// 페이지 코드가 쓰는 API:
//   window.uiConfirm({title, message, ok, danger}) → Promise<boolean>
//   window.uiConfirm.guardForm(form, fn)  — 제출 직전 fn()이 옵션을 돌려주면 확인을 받고, null이면 그냥 제출
//   window.uiPopup.open({el, opener, close}) / window.uiPopup.close()  — 한 번에 하나만 열리는 팝업 관리
//   window.uiSetUnread(n)  — 브라우저 탭 제목 앞에 "(n) "
// 마크업 API: <form data-confirm="문장" data-confirm-title="질문" data-confirm-ok="삭제" data-confirm-danger>
(function () {
  "use strict";

  // ── 메뉴 접기(데스크톱) — 상태는 기억하되 저장소가 막혀 있어도 동작은 해야 한다 ──
  var RAIL_KEY = "loa.navRail";
  function syncFold(btn) {
    var rail = document.documentElement.classList.contains("nav-rail");
    btn.setAttribute("aria-pressed", rail ? "true" : "false");
    btn.setAttribute("aria-label", rail ? "메뉴 펼치기" : "메뉴 접기");
    btn.setAttribute("data-tip", rail ? "메뉴 펼치기" : "메뉴 접기");
    var lbl = btn.querySelector(".side-lbl");
    if (lbl) lbl.textContent = rail ? "메뉴 펼치기" : "메뉴 접기";
  }
  // <head>에서 읽히므로(페이지 인라인 스크립트가 uiConfirm을 바로 쓸 수 있게) DOM에 붙는 초기화는 파싱이 끝난 뒤에
  function initDom() {
  document.querySelectorAll("[data-nav-fold]").forEach(function (btn) {
    syncFold(btn);
    btn.addEventListener("click", function () {
      var rail = document.documentElement.classList.toggle("nav-rail");
      try { localStorage.setItem(RAIL_KEY, rail ? "1" : "0"); } catch (e) { /* 저장 못 해도 이번 화면에서는 접힌다 */ }
      syncFold(btn);
    });
  });

  initMenus();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initDom); else initDom();

  // ── 팝업 공통: 한 번에 하나, Esc·바깥 클릭으로 닫고 연 버튼으로 포커스 복귀 ──
  var current = null; // {el, opener, close}
  function closePopup(restoreFocus) {
    if (!current) return;
    var p = current;
    current = null;
    p.close();
    if (restoreFocus !== false && p.opener && document.contains(p.opener)) p.opener.focus();
  }
  function openPopup(p) {
    if (current && current.el !== p.el) closePopup(false);
    current = p;
  }
  window.uiPopup = { open: openPopup, close: closePopup, current: function () { return current; } };

  document.addEventListener("click", function (e) {
    if (!current) return;
    if (current.el.contains(e.target)) return;
    if (current.opener && current.opener.contains(e.target)) return;
    if (e.target.closest && e.target.closest(".dlg-back")) return;
    closePopup(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && current && !document.querySelector(".dlg-back")) {
      e.preventDefault();
      closePopup(true);
    }
  });

  // ── 메뉴(role=menu): [data-menu-trigger] aria-controls="메뉴 id" ──
  function menuItems(menu) {
    return [].slice.call(menu.querySelectorAll(".menu-item")).filter(function (b) { return !b.disabled && b.offsetParent !== null; });
  }
  function initMenus() {
  document.querySelectorAll("[data-menu-trigger]").forEach(function (trigger) {
    var menu = document.getElementById(trigger.getAttribute("aria-controls"));
    if (!menu) return;
    function close() { menu.hidden = true; trigger.setAttribute("aria-expanded", "false"); }
    function open(focusLast) {
      menu.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      openPopup({ el: menu, opener: trigger, close: close });
      var items = menuItems(menu);
      if (items.length) items[focusLast ? items.length - 1 : 0].focus();
    }
    trigger.addEventListener("click", function () {
      if (menu.hidden) open(false); else closePopup(true);
    });
    trigger.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(e.key === "ArrowUp"); }
    });
    menu.addEventListener("keydown", function (e) {
      var items = menuItems(menu), i = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
      } else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
      else if (e.key === "Tab") { closePopup(false); }
    });
  });
  }

  // ── 탭 묶음: ← → 로 이동 ──
  document.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    var list = e.target.closest && e.target.closest('.utabs, [role="tablist"]');
    if (!list) return;
    var tabs = [].slice.call(list.querySelectorAll("a, button")).filter(function (t) { return !t.disabled; });
    var i = tabs.indexOf(e.target);
    if (i < 0) return;
    e.preventDefault();
    var next = tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
    next.focus();
    if (next.tagName === "BUTTON") next.click();
  });

  // ── 확인 대화상자 ──
  var dlgSeq = 0;
  function uiConfirm(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var opener = document.activeElement;
      var id = "dlg-" + (++dlgSeq);
      var back = document.createElement("div");
      back.className = "dlg-back";
      var dlg = document.createElement("div");
      dlg.className = "dlg";
      dlg.setAttribute("role", "alertdialog");
      dlg.setAttribute("aria-modal", "true");
      dlg.setAttribute("aria-labelledby", id + "-t");
      var h = document.createElement("h2");
      h.id = id + "-t";
      h.textContent = opts.title || opts.message || "계속할까요?";
      dlg.appendChild(h);
      if (opts.title && opts.message) {
        var p = document.createElement("p");
        p.id = id + "-d";
        p.textContent = opts.message;
        dlg.appendChild(p);
        dlg.setAttribute("aria-describedby", p.id);
      }
      var acts = document.createElement("div");
      acts.className = "acts";
      var cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "btn";
      cancel.textContent = opts.cancel || "취소";
      var ok = document.createElement("button");
      ok.type = "button";
      ok.className = "btn " + (opts.danger ? "danger" : "pri");
      ok.textContent = opts.ok || "확인";
      acts.appendChild(cancel);
      acts.appendChild(ok);
      dlg.appendChild(acts);
      back.appendChild(dlg);
      document.body.appendChild(back);
      closePopup(false);

      var done = false;
      function finish(result) {
        if (done) return;
        done = true;
        back.remove();
        document.removeEventListener("keydown", onKey, true);
        if (opener && opener.focus && document.contains(opener)) opener.focus();
        resolve(result);
      }
      function onKey(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); return; }
        if (e.key !== "Tab") return;
        var f = [cancel, ok], i = f.indexOf(document.activeElement);
        if (i < 0) { e.preventDefault(); cancel.focus(); return; }
        if (e.shiftKey && i === 0) { e.preventDefault(); ok.focus(); }
        else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); cancel.focus(); }
      }
      document.addEventListener("keydown", onKey, true);
      back.addEventListener("mousedown", function (e) { if (e.target === back) back.dataset.down = "1"; });
      back.addEventListener("click", function (e) {
        if (e.target === back && back.dataset.down === "1") finish(false);
        back.dataset.down = "";
      });
      cancel.addEventListener("click", function () { finish(false); });
      ok.addEventListener("click", function () { finish(true); });
      cancel.focus();
    });
  }

  // 폼 필드 값으로 {필드명} 자리를 채운다(값은 textContent로만 들어가 스크립트가 될 수 없다)
  function fill(text, form) {
    if (!text || !form) return text || "";
    return text.replace(/\{([a-zA-Z0-9_]+)\}/g, function (m, name) {
      var f = form.elements && form.elements[name];
      return f && "value" in f ? String(f.value).trim() : m;
    });
  }
  function optionsFrom(host, form) {
    var message = fill(host.getAttribute("data-confirm"), form);
    var extraSel = host.getAttribute("data-confirm-extra");
    if (extraSel && form && form.parentNode) {
      var extra = form.parentNode.querySelector(extraSel);
      var t = extra ? extra.textContent.trim() : "";
      if (t) message = message ? t + "\n" + message : t;
    }
    var title = fill(host.getAttribute("data-confirm-title"), form);
    return {
      title: title || message,
      message: title ? message : "",
      ok: host.getAttribute("data-confirm-ok") || "확인",
      danger: host.hasAttribute("data-confirm-danger"),
    };
  }
  function skipBecauseSame(host, form) {
    var field = host.getAttribute("data-confirm-skip-same");
    if (!field || !form || !form.elements[field]) return false;
    return String(form.elements[field].value).trim() === (host.getAttribute("data-confirm-original") || "");
  }
  function resubmit(form, submitter) {
    form.__uiConfirmed = true;
    if (form.requestSubmit) {
      if (submitter && submitter.form === form) form.requestSubmit(submitter); else form.requestSubmit();
    } else {
      form.submit();
    }
  }

  // data-confirm 폼/제출 버튼 — 캡처 단계에서 먼저 잡아 form-busy·htmx·인라인 핸들러보다 앞선다
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    var sub = e.submitter;
    var host = sub && sub.hasAttribute && sub.hasAttribute("data-confirm") ? sub : (form.hasAttribute("data-confirm") ? form : null);
    if (!host) return;
    if (form.__uiConfirmed) { form.__uiConfirmed = false; return; }
    e.preventDefault();
    e.stopImmediatePropagation();
    if (skipBecauseSame(host, form)) { resubmit(form, sub); return; }
    uiConfirm(optionsFrom(host, form)).then(function (ok) { if (ok) resubmit(form, sub); });
  }, true);

  // 폼 밖의 링크/버튼에 붙은 data-confirm
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest("a[data-confirm], button[data-confirm]");
    if (!el) return;
    if (el.tagName === "BUTTON" && el.form && (el.type || "submit") === "submit") return; // submit 경로에서 처리
    if (el.__uiConfirmed) { el.__uiConfirmed = false; return; }
    e.preventDefault();
    e.stopImmediatePropagation();
    uiConfirm(optionsFrom(el, el.form)).then(function (ok) {
      if (!ok) return;
      if (el.tagName === "A" && el.href) { window.location.href = el.href; return; }
      el.__uiConfirmed = true;
      el.click();
    });
  }, true);

  // htmx hx-confirm도 같은 대화상자로
  document.addEventListener("htmx:confirm", function (e) {
    var q = e.detail && e.detail.question;
    if (!q) return;
    e.preventDefault();
    var elt = e.detail.elt;
    var title = elt.getAttribute("data-confirm-title");
    uiConfirm({
      title: title || q,
      message: title ? q : "",
      ok: elt.getAttribute("data-confirm-ok") || "확인",
      danger: elt.hasAttribute("data-confirm-danger"),
    }).then(function (ok) { if (ok) e.detail.issueRequest(true); });
  });

  // 페이지 스크립트용: 조건부 확인(대상 이름이 select에서 오는 경우 등)
  uiConfirm.guardForm = function (form, getOptions) {
    if (!form) return;
    form.addEventListener("submit", function (e) {
      if (form.__uiGuardOk) { form.__uiGuardOk = false; return; }
      var opts = getOptions();
      if (!opts) return;
      e.preventDefault();
      var sub = e.submitter;
      uiConfirm(opts).then(function (ok) {
        if (!ok) return;
        form.__uiGuardOk = true;
        if (form.requestSubmit) { if (sub && sub.form === form) form.requestSubmit(sub); else form.requestSubmit(); } else form.submit();
      });
    });
  };
  window.uiConfirm = uiConfirm;

  // ── 브라우저 탭 제목: "(2) 홈 · 길드명" ──
  var baseTitle = document.title.replace(/^\(\d+\+?\)\s*/, "");
  window.uiSetUnread = function (n) {
    document.title = (n > 0 ? "(" + (n > 99 ? "99+" : n) + ") " : "") + baseTitle;
  };
})();
