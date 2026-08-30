const KOREAN_LOCALE = {
  weekdays: {
    shorthand: ["일", "월", "화", "수", "목", "금", "토"],
    longhand: ["일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"],
  },
  months: {
    shorthand: ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"],
    longhand: ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"],
  },
  rangeSeparator: " ~ ",
  time_24hr: true,
};

function initPartyDatetimePicker(selector, options) {
  options = options || {};
  return flatpickr(selector, {
    enableTime: true,
    dateFormat: "Y-m-d\\TH:i", // 실제 폼 제출값 — 서버가 파싱하는 형식, 화면엔 안 보임
    altInput: true,
    altFormat: "Y-m-d (D) H:i", // 화면에 보여주는 값만 사람이 읽기 편하게
    time_24hr: true,
    // 새 파티 생성은 과거 날짜를 막는 게 맞지만, 이미 지난 시각으로 예약돼 있던
    // 파티를 재조정할 때는 그 값을 그대로 보여줘야 하므로(서버가 실제 저장은
    // 여전히 막는다) 리스케줄 쪽에서 minDate: null을 넘겨 끌 수 있게 한다.
    minDate: options.minDate !== undefined ? options.minDate : "today",
    hourIncrement: 1,
    minuteIncrement: 10,
    locale: KOREAN_LOCALE,
    onReady: attachPartyDatetimeStepButtons,
  });
}

function attachPartyDatetimeStepButtons(selectedDates, dateStr, instance) {
  const timeContainer = instance.calendarContainer.querySelector(".flatpickr-time");
  if (!timeContainer || timeContainer.dataset.stepButtonsAdded) return;
  timeContainer.dataset.stepButtonsAdded = "1";

  function step(el, delta, min, max) {
    const span = max - min + 1;
    let val = parseInt(el.value || String(min), 10);
    val = (((val - min + delta) % span) + span) % span + min;
    el.value = String(val).padStart(2, "0");
    // flatpickr는 change가 아니라 blur에서 시간 값을 동기화한다
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function makeStepButton(label, onClick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "fp-step-btn";
    btn.textContent = label;
    btn.tabIndex = -1;
    btn.addEventListener("click", onClick);
    return btn;
  }

  const hourWrapper = instance.hourElement.parentElement;
  hourWrapper.insertBefore(
    makeStepButton("−", () => step(instance.hourElement, -1, 0, 23)),
    instance.hourElement
  );
  hourWrapper.appendChild(makeStepButton("+", () => step(instance.hourElement, 1, 0, 23)));

  const minuteWrapper = instance.minuteElement.parentElement;
  minuteWrapper.insertBefore(
    makeStepButton("−", () => step(instance.minuteElement, -10, 0, 59)),
    instance.minuteElement
  );
  minuteWrapper.appendChild(makeStepButton("+", () => step(instance.minuteElement, 10, 0, 59)));
}

// 일정을 완전히 새로 고르는 대신, "조금만 미루기"를 달력을 열지 않고 끝내기 위한
// 버튼 — 현재 선택된 값(없으면 지금 시각)에 분 단위 오프셋을 더해 다시 세팅한다.
function attachQuickAdjustButtons(picker, containerSelector) {
  const container = document.querySelector(containerSelector);
  if (!container || !picker) return;

  container.querySelectorAll("[data-adjust-minutes]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const deltaMinutes = parseInt(btn.dataset.adjustMinutes, 10);
      const base = picker.selectedDates[0] || new Date();
      picker.setDate(new Date(base.getTime() + deltaMinutes * 60000), true);
    });
  });
}
