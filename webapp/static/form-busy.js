// 시간이 걸리는 폼 제출 버튼에 진행 상태를 보여준다.
// 원정대 동기화처럼 캐릭터 수만큼 외부 API를 도는 동작은 응답이 몇 초씩 걸리는데,
// 눌린 티가 안 나면 사용자가 계속 다시 누른다(그만큼 API 호출이 늘어난다).
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (!(form instanceof HTMLFormElement)) return;

  var button = form.querySelector("button[data-busy-text]");
  if (!button || button.disabled) return;

  button.dataset.idleText = button.textContent;
  button.textContent = button.dataset.busyText;
  button.disabled = true;

  // 제출이 막힌 경우(검증 실패 등)를 대비해 원래 상태로 되돌린다.
  setTimeout(function () {
    if (!button.disabled) return;
    button.disabled = false;
    button.textContent = button.dataset.idleText;
  }, 30000);
});
