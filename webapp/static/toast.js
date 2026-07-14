(function () {
  var TOAST_DURATION_MS = 4000;

  function showToast(message, type) {
    var container = document.getElementById("toast-container");
    if (!container || !message) return;

    var toast = document.createElement("div");
    toast.className = "toast toast-" + (type || "info");
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(function () {
      toast.classList.add("toast-hide");
      setTimeout(function () {
        toast.remove();
      }, 300);
    }, TOAST_DURATION_MS);
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

  document.addEventListener("DOMContentLoaded", function () {
    var flashes = document.querySelectorAll(".flash-data");
    flashes.forEach(function (el) {
      showToast(el.getAttribute("data-message"), el.getAttribute("data-type"));
      el.remove();
    });
  });
})();
