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

function initPartyDatetimePicker(selector) {
  flatpickr(selector, {
    enableTime: true,
    dateFormat: "Y-m-d\\TH:i",
    time_24hr: true,
    minDate: "today",
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
