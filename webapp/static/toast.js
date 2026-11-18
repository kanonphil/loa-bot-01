// 토스트 — 오른쪽 아래, 5초 뒤 사라짐(마우스를 올리거나 버튼에 포커스가 있으면 멈춤).
//   window.showToast(kind, message, {actionLabel, onAction, duration})   kind: "ok" | "err" | "info"
//   호출은 전부 이 순서(kind 먼저)로 쓴다. 옛 형식 showToast(message, "success"|"error"|"info")와
//   kind 별칭("success"/"error")도 하위 호환으로만 받는다.
// ?toast= 플래시(webapp/flash.py)와 htmx X-Toast 헤더도 여기서 띄운다.
(function () {
  var DURATION_MS = 5000;
  var EXIT_MS = 200;
  var KINDS = { ok: "ok", success: "ok", err: "err", error: "err", info: "info" };
  var MARK = { ok: "✓", err: "!", info: "i" };

  function showToast(a, b, opts) {
    var kind, message;
    if (KINDS[a] && typeof b === "string") { kind = KINDS[a]; message = b; }
    else { message = a; kind = KINDS[b] || "info"; }
    opts = opts || {};
    var container = document.getElementById("toast-container");
    if (!container || !message) return null;

    var duration = opts.duration || DURATION_MS;
    var toast = document.createElement("div");
    toast.className = "toast" + (kind === "ok" ? "" : " " + kind);
    toast.style.setProperty("--toast-ms", duration + "ms");
    if (kind === "err") toast.setAttribute("role", "alert");

    var mark = document.createElement("b");
    mark.className = "toast-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = MARK[kind];
    var msg = document.createElement("span");
    msg.className = "toast-msg";
    msg.textContent = message;
    toast.appendChild(mark);
    toast.appendChild(msg);
    if (opts.actionLabel) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn sm ghost";
      btn.textContent = opts.actionLabel;
      btn.addEventListener("click", function () {
        dismiss();
        if (typeof opts.onAction === "function") opts.onAction();
      });
      toast.appendChild(btn);
    }
    var bar = document.createElement("span");
    bar.className = "toast-bar";
    bar.setAttribute("aria-hidden", "true");
    toast.appendChild(bar);
    container.appendChild(toast);

    // 남은 시간은 막대 애니메이션이 아니라 타이머로 센다(움직임 줄이기 설정에서는 막대가 없다)
    var remaining = duration, startedAt = Date.now(), timer = null, dismissed = false;
    function start() { startedAt = Date.now(); timer = setTimeout(dismiss, remaining); }
    function pause() { if (!timer) return; clearTimeout(timer); timer = null; remaining -= Date.now() - startedAt; }
    function resume() { if (timer || dismissed) return; if (toast.matches(":hover") || toast.contains(document.activeElement)) return; start(); }
    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      clearTimeout(timer);
      toast.classList.add("toast-hide");
      setTimeout(function () { toast.remove(); }, EXIT_MS);
    }
    toast.addEventListener("mouseenter", pause);
    toast.addEventListener("mouseleave", resume);
    toast.addEventListener("focusin", pause);
    toast.addEventListener("focusout", function () { setTimeout(resume, 0); });
    start();
    return { dismiss: dismiss };
  }

  window.showToast = showToast;

  // ── 알림음 — 파일 에셋 없이 WebAudio로 만드는 짧은 2음 차임.
  // 브라우저 자동재생 정책상 사용자가 페이지와 상호작용하기 전엔 소리가 안 날 수 있다
  // (그 경우 조용히 무시). force=true는 설정 페이지 "미리 듣기"용으로 끔 상태여도 재생.
  var audioCtx = null;
  function playNotifSound(force) {
    try {
      if (!force && localStorage.getItem("notifSoundOff") === "1") return;
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioCtx = audioCtx || new Ctx();
      if (audioCtx.state === "suspended") audioCtx.resume();
      var now = audioCtx.currentTime;
      [880, 1174.66].forEach(function (freq, i) {
        var start = now + i * 0.09;
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.12, start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.35);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start(start);
        osc.stop(start + 0.4);
      });
    } catch (e) {
      /* 소리는 부가 기능 — 실패해도 toast 표시는 계속돼야 한다 */
    }
  }

  window.playNotifSound = playNotifSound;

  // htmx 부분 갱신(레이드 체크 토글 등)은 페이지가 다시 그려지지 않아 .flash-data를
  // 못 쓴다 — 서버가 X-Toast 헤더(percent-encoding)로 결과 문구를 실어 보내면 띄운다.
  document.body.addEventListener("htmx:afterRequest", function (event) {
    var xhr = event.detail && event.detail.xhr;
    if (!xhr || !xhr.getResponseHeader) return;
    var raw = xhr.getResponseHeader("X-Toast");
    if (!raw) return;
    var type = xhr.getResponseHeader("X-Toast-Type") || "success";
    var text;
    try { text = decodeURIComponent(raw); } catch (e) { text = raw; }
    showToast(KINDS[type] || "info", text);
  });

  document.addEventListener("DOMContentLoaded", function () {
    var flashes = document.querySelectorAll(".flash-data");
    var strip = false;
    flashes.forEach(function (el) {
      var type = el.getAttribute("data-type");
      showToast(KINDS[type] || "info", el.getAttribute("data-message") || "");
      if (el.hasAttribute("data-strip-url")) strip = true;
      el.remove();
    });
    // ?toast= 는 1회성 — 남겨두면 F5/뒤로가기마다 같은 토스트가 다시 뜬다
    if (strip && window.history && window.history.replaceState) {
      try {
        var url = new URL(window.location.href);
        url.searchParams.delete("toast");
        url.searchParams.delete("toast_type");
        window.history.replaceState(null, "", url.pathname + (url.search || "") + url.hash);
      } catch (e) { /* URL 정리는 부가 기능 */ }
    }
  });
})();
