(function () {
  var path = window.location.pathname;
  var isRelevant = path === "/main" || path === "/parties" || path === "/calendar";
  if (!isRelevant) return;

  var source = new EventSource("/events/parties");
  source.addEventListener("parties-changed", function () {
    window.location.reload();
  });
})();
