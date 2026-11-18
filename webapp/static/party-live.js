(function () {
  var path = window.location.pathname;
  // 파티 상세(/parties/<id>)도 포함 — 목록/캘린더만 갱신되고 상세는 F5를 눌러야
  // 슬롯/댓글이 보이던 문제. /parties/create, /parties/history는 폼/이력 화면이라 제외.
  var detailMatch = path.match(/^\/parties\/([^/]+)$/);
  var detailId = detailMatch && path !== "/parties/create" && path !== "/parties/history" ? detailMatch[1] : null;
  // /invites: 파티장이 초대하거나 슬롯이 채워지면 바뀜, /raid-check: 파티장이 클리어하면 자동 체크가 들어옴
  var isList = path === "/main" || path === "/parties" || path === "/calendar" || path === "/admin/parties" || path === "/invites";
  var isRaidCheck = path === "/raid-check";
  if (!isList && !isRaidCheck && !detailId) return;

  // 서버(party_events.py)가 보내는 이벤트 종류 — { type, message_id }
  //   created / reopened / slots / status / details : 공대 목록·참가자·상태·일정이 바뀜
  //   comments : 댓글 수만 바뀜(상세 화면에서만 의미 있음)
  //   cleared / removed : 목록에서 사라짐(클리어 / 취소·종료)
  var LIST_TYPES = { created: 1, reopened: 1, slots: 1, status: 1, details: 1, cleared: 1, removed: 1 };

  // 이 페이지가 이 이벤트를 신경 써야 하는지. 예전엔 어떤 변경이든 열린 모든 탭이 전체 페이지를 다시
  // 받았다(댓글 하나에 탭 10개 × 요청 수십 개).
  function isRelevant(event) {
    if (!event) return true; // 형식을 모르면 안전하게 갱신
    if (detailId) return String(event.message_id) === detailId;
    if (isRaidCheck) return event.type === "cleared";
    return !!LIST_TYPES[event.type];
  }

  var source = new EventSource("/events/parties");
  var timer = null;
  var hiddenPending = false;

  source.addEventListener("parties-changed", function (e) {
    var event = null;
    try { event = JSON.parse(e.data); } catch (err) { /* 옛 형식 → 항상 갱신 */ }
    if (!isRelevant(event)) return;
    // 한 폴링에서 여러 이벤트가 몰려도 한 번만 갱신한다
    clearTimeout(timer);
    timer = setTimeout(requestRefresh, 300);
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && hiddenPending) {
      hiddenPending = false;
      requestRefresh();
    }
  });

  // 폼 입력 추적 — 한 글자라도 입력/변경한 폼은 "작성 중"이다.
  document.addEventListener("input", markDirty, true);
  document.addEventListener("change", markDirty, true);
  function markDirty(e) {
    var form = e.target && e.target.closest ? e.target.closest(".page-content form") : null;
    if (form) form.dataset.liveDirty = "1";
  }

  // 작성 중이거나 폼 안에 포커스가 있으면 화면을 갈아엎지 않는다 — 쓰던 글·선택이 사라지기 때문.
  function isEditing() {
    var el = document.activeElement;
    if (el && el.closest && el.closest(".page-content form")) return true;
    return !!document.querySelector(".page-content form[data-live-dirty]");
  }

  function requestRefresh() {
    if (document.hidden) {
      hiddenPending = true; // 안 보는 탭은 돌아왔을 때 한 번만
      return;
    }
    if (isEditing()) {
      showBanner();
      return;
    }
    refresh();
  }

  function showBanner() {
    var content = document.querySelector(".page-content");
    if (!content || content.querySelector("[data-live-banner]")) return;
    var banner = document.createElement("div");
    banner.className = "banner info";
    banner.setAttribute("data-live-banner", "");
    var text = document.createElement("span");
    text.textContent = "바뀐 내용이 있습니다";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn sm pri";
    button.textContent = "지금 반영";
    button.addEventListener("click", function () {
      banner.remove();
      refresh();
    });
    banner.appendChild(text);
    banner.appendChild(button);
    content.insertBefore(banner, content.firstChild);
  }

  // 예전엔 여기서 window.location.reload()를 했다 — 길드 전체 공대 변경 하나에
  // 접속 중인 모든 탭이 전체 페이지를 다시 받았고(CSS/JS 재다운로드, 알림 SSE
  // 재연결, nav-badges 재조회까지 전부 다시 발생), SSE 폴링 루프를 하나로 합쳐
  // 서버 부하를 줄이려던 의도가 클라이언트에서 무효화되고 있었다. 대신 같은
  // URL을 한 번만 다시 받아서 .page-content만 교체한다 — 요청은 1개로 그대로고
  // 나머지 페이지(사이드바·알림 연결 등)는 안 건드린다.
  function refresh() {
    var drafts = collectDrafts();
    fetch(window.location.href, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (resp) {
        if (!resp.ok) throw new Error("refresh failed: " + resp.status);
        return resp.text();
      })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var newContent = doc.querySelector(".page-content");
        var oldContent = document.querySelector(".page-content");
        if (!newContent || !oldContent) {
          window.location.reload();
          return;
        }
        // 요청을 보내고 기다리는 사이에 입력을 시작했을 수 있다 — 그러면 덮어쓰지 않고 배너로 알린다.
        if (isEditing()) {
          showBanner();
          return;
        }
        oldContent.replaceWith(newContent);
        // innerHTML/replaceWith로 넣은 <script>는 브라우저가 실행하지 않으므로
        // (검색창 필터 스크립트 등) 새 <script> 엘리먼트로 다시 만들어 붙여준다.
        newContent.querySelectorAll("script").forEach(function (oldScript) {
          var newScript = document.createElement("script");
          Array.prototype.forEach.call(oldScript.attributes, function (attr) {
            newScript.setAttribute(attr.name, attr.value);
          });
          newScript.textContent = oldScript.textContent;
          oldScript.replaceWith(newScript);
        });
        restoreDrafts(newContent, drafts);
        if (window.htmx) window.htmx.process(newContent);
        if (window.refreshNavBadges) window.refreshNavBadges();
        if (window.applyMarquee) window.applyMarquee();
        if (window.initThemedSelects) window.initThemedSelects();
      })
      .catch(function () {
        window.location.reload(); // 부분 갱신이 실패하면 기존 동작(전체 새로고침)으로 안전하게 폴백
      });
  }

  // 폼 밖에서 쓰던 textarea 내용도 같은 이름의 새 입력창에 되돌린다(폼 안은 위에서 갱신 자체를 막는다).
  function collectDrafts() {
    var drafts = {};
    document.querySelectorAll(".page-content textarea[name]").forEach(function (el) {
      if (el.value) drafts[el.name] = el.value;
    });
    return drafts;
  }
  function restoreDrafts(root, drafts) {
    Object.keys(drafts).forEach(function (name) {
      var el = root.querySelector('textarea[name="' + name + '"]');
      if (el && !el.value) el.value = drafts[name];
    });
  }
})();
