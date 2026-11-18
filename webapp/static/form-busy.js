// 시간이 걸리는 폼 제출 버튼에 처리 중 상태(aria-busy 스피너)를 보여준다.
// 원정대 동기화처럼 캐릭터 수만큼 외부 API를 도는 동작은 응답이 몇 초씩 걸리는데,
// 눌린 티가 안 나면 사용자가 계속 다시 누른다(그만큼 API 호출이 늘어난다).
// 글자를 '처리 중…'으로 바꾸면 버튼 폭이 변해 줄이 흔들렸다 — 글자 자리에 스피너만 띄우고 폭은 그대로 둔다.
// 대상: data-busy-text가 붙은 버튼, 또는 data-busy-form 폼의 제출 버튼.
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (event.defaultPrevented) return; // 확인 취소·검증 실패 등으로 실제 제출이 아닌 경우

  var button = null;
  var sub = event.submitter;
  if (sub && sub.form === form && (sub.hasAttribute("data-busy-text") || form.hasAttribute("data-busy-form"))) button = sub;
  if (!button) button = form.querySelector("button[data-busy-text]");
  if (!button && form.hasAttribute("data-busy-form")) {
    button = form.querySelector("button[type=submit]") || form.querySelector("button");
  }
  if (!button || button.disabled || button.getAttribute("aria-busy") === "true") return;

  // 스피너를 그리는 동안에도 읽어 줄 문구(스크린리더)
  var busyLabel = button.getAttribute("data-busy-text") || "처리 중";
  button.dataset.idleLabel = button.getAttribute("aria-label") || "";
  button.setAttribute("aria-label", busyLabel);
  button.setAttribute("aria-busy", "true");
  // 같은 폼의 다른 제출 버튼도 중복 제출을 막는다(disabled는 폼 값 전송에서 빠지므로 클릭만 막는다)
  form.setAttribute("aria-busy", "true");

  function restore() {
    button.removeAttribute("aria-busy");
    form.removeAttribute("aria-busy");
    if (button.dataset.idleLabel) button.setAttribute("aria-label", button.dataset.idleLabel);
    else button.removeAttribute("aria-label");
  }
  // 제출이 막힌 경우(새 페이지로 안 넘어감)나 뒤로가기로 돌아온 경우를 대비해 원래 상태로 되돌린다
  setTimeout(restore, 30000);
  window.addEventListener("pageshow", function (e) { if (e.persisted) restore(); }, { once: true });
  // htmx 폼은 페이지가 바뀌지 않는다 — 요청이 끝나면 되돌린다
  if (form.hasAttribute("hx-post") || form.hasAttribute("hx-get")) {
    form.addEventListener("htmx:afterRequest", restore, { once: true });
  }
});
