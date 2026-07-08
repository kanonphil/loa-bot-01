(function () {
  var popover = document.getElementById("party-member-popover");
  if (!popover) return;

  var cache = {};
  var showTimer = null;
  var hideTimer = null;
  var currentSlot = null;

  function cacheKey(discordId, name) {
    return discordId + "::" + name;
  }

  function positionNear(el) {
    var rect = el.getBoundingClientRect();
    var left = Math.min(rect.left, window.innerWidth - 280);
    popover.style.left = Math.max(left, 8) + "px";
    popover.style.top = rect.bottom + 8 + "px";
  }

  function show(slot) {
    var discordId = slot.dataset.discordId;
    var name = slot.dataset.characterName;
    if (!discordId || !name) return;

    positionNear(slot);
    popover.style.display = "block";

    var key = cacheKey(discordId, name);
    if (cache[key]) {
      popover.innerHTML = cache[key];
      return;
    }

    popover.innerHTML = '<div class="member-card-error">불러오는 중...</div>';
    fetch(
      "/party-member-card?discord_id=" + encodeURIComponent(discordId) +
        "&character_name=" + encodeURIComponent(name)
    )
      .then(function (res) {
        return res.text();
      })
      .then(function (html) {
        cache[key] = html;
        if (currentSlot === slot) {
          popover.innerHTML = html;
        }
      })
      .catch(function () {
        popover.innerHTML = '<div class="member-card-error">정보를 불러오지 못했습니다.</div>';
      });
  }

  function hide() {
    popover.style.display = "none";
    currentSlot = null;
  }

  document.querySelectorAll(".party-slot.filled[data-character-name]").forEach(function (slot) {
    slot.addEventListener("mouseenter", function () {
      clearTimeout(hideTimer);
      currentSlot = slot;
      showTimer = setTimeout(function () {
        if (currentSlot === slot) show(slot);
      }, 250);
    });
    slot.addEventListener("mouseleave", function () {
      clearTimeout(showTimer);
      hideTimer = setTimeout(hide, 200);
    });
  });

  popover.addEventListener("mouseenter", function () {
    clearTimeout(hideTimer);
  });
  popover.addEventListener("mouseleave", function () {
    hideTimer = setTimeout(hide, 200);
  });
})();
