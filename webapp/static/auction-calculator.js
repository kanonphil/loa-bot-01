(function () {
  var FEE_RATE = 0.05; // 경매장 수수료 5% (템 가격 기준 고정, 인원수와 무관)

  var priceInput = document.getElementById("calc-price");
  var partySizeRadios = document.querySelectorAll('input[name="calc-party-size"]');
  var customRadio = document.getElementById("calc-party-size-custom-radio");
  var customInput = document.getElementById("calc-party-size-custom");

  var useBidEl = document.getElementById("calc-use-bid");
  var useDistributionEl = document.getElementById("calc-use-distribution");
  var sellFeeEl = document.getElementById("calc-sell-fee");
  var sellBreakevenEl = document.getElementById("calc-sell-breakeven");
  var sellDistributionEl = document.getElementById("calc-sell-distribution");
  var sellProfitEl = document.getElementById("calc-sell-profit");

  function formatGold(n) {
    return Math.round(n).toLocaleString("ko-KR") + " 골드";
  }

  function getPartySize() {
    var checked = null;
    partySizeRadios.forEach(function (r) {
      if (r.checked) checked = r;
    });
    if (!checked) return 8;
    if (checked.value === "custom") {
      return Number(customInput.value) || 0;
    }
    return Number(checked.value);
  }

  function recalculate() {
    customInput.disabled = !customRadio.checked;

    var price = Number(priceInput.value) || 0;
    var partySize = getPartySize();

    // 직접사용 — 자신은 분배금을 못 받으므로, 템 가격에서 1인분(템가격/인원수)을
    // 뺀 만큼만 입찰해야 시장에서 직접 사는 것과 비교해 손해를 안 본다.
    var useDistribution = partySize > 0 ? price / partySize : 0;
    var useBid = price - useDistribution;

    // 판매 — 되팔 때는 경매 수수료를 뗀 실수령액을 기준으로 같은 계산을 한다.
    var fee = price * FEE_RATE;
    var netValue = price - fee;
    var sellDistribution = partySize > 0 ? netValue / partySize : 0;
    var breakeven = netValue - sellDistribution;
    var sellProfit = price - breakeven;

    useBidEl.textContent = formatGold(useBid);
    useDistributionEl.textContent = formatGold(useDistribution);
    sellFeeEl.textContent = formatGold(fee);
    sellBreakevenEl.textContent = formatGold(breakeven);
    sellDistributionEl.textContent = formatGold(sellDistribution);
    sellProfitEl.textContent = formatGold(sellProfit);
  }

  priceInput.addEventListener("input", recalculate);
  customInput.addEventListener("input", recalculate);
  partySizeRadios.forEach(function (r) {
    r.addEventListener("change", recalculate);
  });

  recalculate();
})();
