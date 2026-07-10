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

  document.addEventListener("DOMContentLoaded", function () {
    var flashes = document.querySelectorAll(".flash-data");
    flashes.forEach(function (el) {
      showToast(el.getAttribute("data-message"), el.getAttribute("data-type"));
      el.remove();
    });
  });
})();
