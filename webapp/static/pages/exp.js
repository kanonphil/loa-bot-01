// 원정대 · 더보기 묶음 공용 동작.
//  1) form[data-inline]  — fetch로 보내 실패 사유를 입력칸 아래에 그린다(성공이면 서버가 준 주소로 이동해 토스트).
//                          JS가 없거나 JSON이 아닌 응답이면 그냥 폼을 제출한다.
//  2) [data-sync-form]   — 동기화가 6초 넘게 걸리면 안내 문구를 바꾼다(버튼 처리 중 표시는 form-busy.js).
//  3) form[data-switch-json] — 골드섬 알림처럼 즉시 저장되는 스위치. 실패하면 되돌리고 토스트.
(function () {
  "use strict";

  function toast(kind, msg) {
    if (window.showToast) window.showToast(kind, msg);
  }

  function setBusy(form, btn, on) {
    if (!btn) return;
    if (on) {
      btn.dataset.idleLabel = btn.getAttribute("aria-label") || "";
      btn.setAttribute("aria-label", btn.getAttribute("data-busy-text") || "처리 중");
      btn.setAttribute("aria-busy", "true");
      form.setAttribute("aria-busy", "true");
    } else {
      btn.removeAttribute("aria-busy");
      form.removeAttribute("aria-busy");
      if (btn.dataset.idleLabel) btn.setAttribute("aria-label", btn.dataset.idleLabel);
      else btn.removeAttribute("aria-label");
    }
  }

  // ── 1) 인라인 오류 폼 ──
  document.querySelectorAll("form[data-inline]").forEach(function (form) {
    var help = form.querySelector("[data-help]") || (form.nextElementSibling && form.nextElementSibling.matches("[data-help]") ? form.nextElementSibling : null);
    var idle = help ? help.textContent : "";

    function clear() {
      form.querySelectorAll("[aria-invalid]").forEach(function (el) { el.removeAttribute("aria-invalid"); });
      if (help) { help.textContent = idle; help.classList.remove("is-error"); }
    }
    function fail(message) {
      var fields = form.querySelectorAll("[data-field]");
      var target = fields[0];
      // 봇이 필드를 가리켜 주지 않으므로 문구로 짐작한다: 키 얘기면 키 칸, 아니면 이름 칸
      if (/API|키/.test(message)) target = form.querySelector('[data-field="api_key"]') || target;
      else target = form.querySelector('[data-field="character_name"]') || target;
      if (target) { target.setAttribute("aria-invalid", "true"); target.focus(); }
      if (help) { help.textContent = message; help.classList.add("is-error"); }
      else toast("err", message);
    }

    form.addEventListener("input", clear);
    form.addEventListener("submit", function (e) {
      if (e.defaultPrevented) return;
      e.preventDefault();
      var btn = e.submitter || form.querySelector("button[type=submit]");
      if (form.getAttribute("aria-busy") === "true") return;
      clear();
      var values = new FormData(form);
      for (var pair of values.entries()) {
        if (typeof pair[1] === "string" && pair[0] !== "api_key") values.set(pair[0], pair[1].trim());
      }
      setBusy(form, btn, true);
      fetch(form.action, {
        method: "POST",
        headers: { Accept: "application/json" },
        body: new URLSearchParams(values),
        credentials: "same-origin",
      }).then(function (res) {
        var type = res.headers.get("content-type") || "";
        if (type.indexOf("application/json") === -1) { form.submit(); return null; }
        return res.json();
      }).then(function (data) {
        if (!data) return;
        if (data.success && data.redirect) { window.location.href = data.redirect; return; }
        setBusy(form, btn, false);
        fail(data.reason || "처리하지 못했습니다. 잠시 후 다시 시도해주세요.");
      }).catch(function () {
        setBusy(form, btn, false);
        fail("서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.");
      });
    });
  });

  // ── 2) 오래 걸리는 동기화 안내 ──
  document.querySelectorAll("[data-sync-form]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (e.defaultPrevented) return;
      var note = form.querySelector("[data-sync-note]");
      if (!note) return;
      setTimeout(function () { note.textContent = "캐릭터가 많으면 시간이 걸립니다. 잠시만 기다려 주세요."; }, 6000);
    });
  });

  // ── 3) 즉시 저장 스위치 ──
  document.querySelectorAll("form[data-switch-json]").forEach(function (form) {
    var sw = form.querySelector('[role="switch"]');
    var field = form.querySelector('input[name="enabled"]');
    var state = form.querySelector("[data-switch-state]");
    if (!sw || !field) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (sw.disabled) return;
      var next = sw.getAttribute("aria-checked") !== "true";
      sw.disabled = true;
      fetch(form.action, {
        method: "POST",
        headers: { Accept: "application/json" },
        body: new URLSearchParams({ enabled: next ? "1" : "0" }),
        credentials: "same-origin",
      }).then(function (res) {
        var type = res.headers.get("content-type") || "";
        if (type.indexOf("application/json") === -1) throw new Error("not json");
        return res.json();
      }).then(function (data) {
        if (!data.success) { toast("err", data.reason || "저장하지 못했습니다."); return; }
        sw.setAttribute("aria-checked", next ? "true" : "false");
        field.value = next ? "0" : "1";
        if (state) state.textContent = next ? "켜짐" : "꺼짐";
        toast("ok", data.message || (next ? "알림을 켰습니다." : "알림을 껐습니다."));
      }).catch(function () {
        toast("err", "저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
      }).then(function () { sw.disabled = false; });
    });
  });

  // ── 4) 레이드를 고르면 그 레이드의 난이도 목록으로 바꾼다(설정의 레이드 필터·DM 구독) ──
  document.querySelectorAll("select[data-diff-target]").forEach(function (raidSelect) {
    var diffSelect = document.querySelector(raidSelect.getAttribute("data-diff-target"));
    if (!diffSelect) return;
    var allLabel = raidSelect.getAttribute("data-diff-all-label") || "전체";
    var allValue = raidSelect.getAttribute("data-diff-all-value") || "";
    raidSelect.addEventListener("change", function () {
      var opt = raidSelect.options[raidSelect.selectedIndex];
      var diffs = ((opt && opt.getAttribute("data-difficulties")) || "").split(",").filter(Boolean);
      diffSelect.innerHTML = "";
      [[allValue, allLabel]].concat(diffs.map(function (d) { return [d, d]; })).forEach(function (pair) {
        var o = document.createElement("option");
        o.value = pair[0];
        o.textContent = pair[1];
        diffSelect.appendChild(o);
      });
      diffSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  // ── 5) 알림 소리 — 이 브라우저(localStorage)에만 저장 ──
  var soundSwitch = document.getElementById("notif-sound-toggle");
  if (soundSwitch) {
    var soundState = document.getElementById("notif-sound-state");
    function paintSound(on) {
      soundSwitch.setAttribute("aria-checked", on ? "true" : "false");
      if (soundState) soundState.textContent = on ? "켜짐" : "꺼짐";
    }
    var on = true;
    try { on = localStorage.getItem("notifSoundOff") !== "1"; } catch (e) { /* 저장소가 막혀 있으면 켜진 채로 */ }
    paintSound(on);
    soundSwitch.addEventListener("click", function () {
      on = soundSwitch.getAttribute("aria-checked") !== "true";
      paintSound(on);
      try {
        if (on) localStorage.removeItem("notifSoundOff"); else localStorage.setItem("notifSoundOff", "1");
      } catch (e) { /* 이번 화면에서만 바뀐다 */ }
    });
    var testBtn = document.getElementById("notif-sound-test");
    if (testBtn) testBtn.addEventListener("click", function () { if (window.playNotifSound) window.playNotifSound(true); });
  }
})();
