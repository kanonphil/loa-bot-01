(function () {
  var path = window.location.pathname;
  var isRelevant = path === "/main" || path === "/parties" || path === "/calendar";
  if (!isRelevant) return;

  var source = new EventSource("/events/parties");
  source.addEventListener("parties-changed", function () {
    refresh();
  });

  // 예전엔 여기서 window.location.reload()를 했다 — 길드 전체 공대 변경 하나에
  // 접속 중인 모든 탭이 전체 페이지를 다시 받았고(CSS/JS 재다운로드, 알림 SSE
  // 재연결, nav-badges 재조회까지 전부 다시 발생), SSE 폴링 루프를 하나로 합쳐
  // 서버 부하를 줄이려던 의도가 클라이언트에서 무효화되고 있었다. 대신 같은
  // URL을 한 번만 다시 받아서 .page-content만 교체한다 — 요청은 1개로 그대로고
  // 나머지 페이지(사이드바·알림 연결 등)는 안 건드린다.
  function refresh() {
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
        if (window.applyMarquee) window.applyMarquee();
        if (window.initThemedSelects) window.initThemedSelects();
      })
      .catch(function () {
        window.location.reload(); // 부분 갱신이 실패하면 기존 동작(전체 새로고침)으로 안전하게 폴백
      });
  }
})();
