(function () {
  var menuBtn = document.getElementById("mobile-menu-btn");
  var overlay = document.getElementById("sidebar-overlay");
  if (!menuBtn || !overlay) return;

  function close() {
    document.body.classList.remove("sidebar-open");
  }

  menuBtn.addEventListener("click", function () {
    document.body.classList.toggle("sidebar-open");
  });

  overlay.addEventListener("click", close);
})();
