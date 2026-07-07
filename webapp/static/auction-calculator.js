(function () {
  var bidInput = document.getElementById("calc-bid");
  var partySizeSelect = document.getElementById("calc-party-size");
  var feeInput = document.getElementById("calc-fee");
  var includeWinnerInput = document.getElementById("calc-include-winner");

  var netEl = document.getElementById("calc-result-net");
  var perPersonEl = document.getElementById("calc-result-per-person");
  var winnerCostEl = document.getElementById("calc-result-winner-cost");

  function formatGold(n) {
    return Math.round(n).toLocaleString("ko-KR") + " 골드";
  }

  function recalculate() {
    var bid = Number(bidInput.value) || 0;
    var partySize = Number(partySizeSelect.value) || 8;
    var feePercent = Number(feeInput.value) || 0;
    var includeWinner = includeWinnerInput.checked;

    var net = bid * (1 - feePercent / 100);
    var distributionCount = includeWinner ? partySize : partySize - 1;
    var perPerson = distributionCount > 0 ? Math.floor(net / distributionCount) : 0;
    var winnerCost = includeWinner ? bid - perPerson : bid;

    netEl.textContent = formatGold(net);
    perPersonEl.textContent = formatGold(perPerson);
    winnerCostEl.textContent = formatGold(winnerCost);
  }

  [bidInput, partySizeSelect, feeInput, includeWinnerInput].forEach(function (el) {
    el.addEventListener("input", recalculate);
  });

  recalculate();
})();
