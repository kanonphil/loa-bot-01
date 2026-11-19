"""홈(/main) 점검 — 잘린 글자·밖으로 삐져나온 버튼·가로 스크롤을 폭마다 세고, 숙제 칸 동작(체크·난이도 ▾·키보드·실패)을 확인한다.

사용:
  python scripts/ui_shots/home_check.py                       # 스텁 데이터: 배치 점검 + 동작 점검
  SHOT_REAL_HOME=<real_home.txt> python .../home_check.py      # 운영 응답으로 배치 점검(동작 점검은 스텁일 때만)
  SHOT_BOT_PORT=8831 SHOT_WEB_PORT=8832 로 포트를 나눌 수 있다. 실패가 하나라도 있으면 종료 코드 1.

배치 점검(카드 = 할 일·숙제·공대·오늘의 콘텐츠·이벤트·시세·골드·숫자 카드):
  - 글자 잘림: 카드 안 요소의 scrollWidth > clientWidth(말줄임·넘침 모두)
  - 버튼 이탈: 버튼·링크 버튼이 overflow가 visible이 아닌 조상 상자 밖으로 나감
  - 가로 스크롤: 문서 폭 > 화면 폭
  보기마다(캐릭터별/레이드별, 다 끝낸 캐릭터 펼침, 공대 두 탭) 다시 잰다."""
import base64, json, os, subprocess, sys, time, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
OUT = HERE / "out" / "home_check"
OUT.mkdir(parents=True, exist_ok=True)
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8765")
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8766")
REAL = bool(os.environ.get("SHOT_REAL_HOME"))
BASE = f"http://127.0.0.1:{WEB_PORT}"
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"{BASE}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "out" / "notif.db"), "PYTHONIOENCODING": "utf-8"}
WIDTHS = [(1280, 1), (1366, 1), (1536, 1.25), (1920, 1), (2560, 1), (390, 1)]

LAYOUT_JS = r"""() => {
  const out = [];
  const cards = [...document.querySelectorAll('.home .ui-card, .home .hs-stat')].filter(c => c.getClientRects().length);
  const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const name = el => (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : el.tagName.toLowerCase());
  for (const card of cards) {
    const cardName = name(card);
    for (const el of card.querySelectorAll('*')) {
      if (!visible(el) || el.closest('svg') || el.closest('.menu') || el.closest('[hidden]')) continue;
      if (el.matches('.table-scroll, .table-scroll *')) continue;
      if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1 && el.textContent.trim())
        out.push(`글자 잘림 ${cardName} > ${name(el)} "${el.textContent.trim().slice(0, 30)}" (${el.scrollWidth}>${el.clientWidth})`);
    }
    for (const b of card.querySelectorAll('button, a.btn, .hw-dd, .hw-badge, .chip')) {
      if (!visible(b) || b.closest('.menu') || b.matches('.hw-hit')) continue;
      const r = b.getBoundingClientRect();
      for (let p = b.parentElement; p && p !== document.body; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
        const pr = p.getBoundingClientRect();
        if (r.left < pr.left - 1 || r.right > pr.right + 1 || r.top < pr.top - 1 || r.bottom > pr.bottom + 1)
          out.push(`버튼 이탈 ${cardName} > ${name(b)} "${b.textContent.trim().slice(0, 20)}" in ${name(p)}`);
        break;
      }
      // 카드 밖으로 나가는 것도 이탈
      const cr = card.getBoundingClientRect();
      if (r.right > cr.right + 1 || r.left < cr.left - 1) out.push(`카드 밖 ${cardName} > ${name(b)} "${b.textContent.trim().slice(0, 20)}"`);
    }
  }
  const de = document.documentElement;
  if (de.scrollWidth > de.clientWidth + 1) out.push(`가로 스크롤 ${de.scrollWidth}>${de.clientWidth}`);
  return out;
}"""

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))


def wait(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1); return True
        except Exception:
            time.sleep(0.5)
    return False


stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"],
                       cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids"), "stub down"
    assert wait(f"{BASE}/health"), "web down"
    from itsdangerous import TimestampSigner
    cookie = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps({"user": {"discord_id": "111", "username": "발키리", "is_admin": True, "avatar_url": None, "admin_mode": True}}).encode())).decode()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        errors = []

        # ── 1) 배치 점검: 폭마다, 보기마다 ──
        for w, dpr in WIDTHS:
            ctx = browser.new_context(viewport={"width": w, "height": 844 if w <= 640 else 900}, device_scale_factor=dpr, has_touch=w <= 640)
            ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(BASE + "/main", wait_until="networkidle"); page.wait_for_timeout(250)
            issues = []
            states = [("캐릭터별", None), ("다 끝낸 캐릭터 펼침", "document.querySelectorAll('.hw-fin').forEach(d => d.open = true)"),
                      ("레이드별", "document.querySelector('[data-hw-view=raid]')?.click()"),
                      ("공대 내 일정", "document.querySelector('[data-hp-tab=mine]')?.click()"),
                      ("공대 참여 가능", "document.querySelector('[data-hp-tab=open]')?.click()")]
            for label, js in states:
                if js:
                    page.evaluate(js); page.wait_for_timeout(120)
                issues += [f"[{label}] {i}" for i in page.evaluate(LAYOUT_JS)]
            page.evaluate("document.querySelector('[data-hw-view=char]')?.click(); localStorage.clear()")
            if w == 1280:  # 검사기 자체 점검: 일부러 자른 글자를 찾아내야 한다
                page.evaluate("""() => { const b = document.querySelector('#hw .hw-nm b'); b.dataset.orig = b.textContent;
                    b.style.whiteSpace = 'nowrap'; b.style.overflow = 'hidden'; b.textContent = '아주아주아주아주긴레이드이름'.repeat(4); }""")
                check("검사기 자체 점검: 일부러 자른 글자를 찾아냄", any("글자 잘림" in i for i in page.evaluate(LAYOUT_JS)))
            uniq = sorted(set(issues))
            check(f"{w}px{'@' + str(dpr) if dpr != 1 else ''}: 잘림·이탈·가로 스크롤 없음", not uniq, "; ".join(uniq[:8]) + (f" … 외 {len(uniq) - 8}" if len(uniq) > 8 else ""))
            ctx.close()

        # ── 2) 동작 점검(스텁 데이터) ──
        if not REAL:
            ctx = browser.new_context(viewport={"width": 1536, "height": 900})
            ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(BASE + "/main", wait_until="networkidle"); page.wait_for_timeout(250)
            tile = lambda c, r: page.locator(f'#hw [data-hw-panel=char] .hw-tile[data-char="{c}"][data-raid="{r}"]')

            # 키보드: 칸 → (모집 배지) → 난이도 ▾
            t = tile("발키리", "종막")
            t.locator(".hw-hit").focus()
            page.keyboard.press("Tab")
            f1 = page.evaluate("document.activeElement.className")
            page.keyboard.press("Tab")
            f2 = page.evaluate("document.activeElement.className")
            check("Tab 순서: 칸 → 모집 배지 → 난이도", f1 == "hw-badge" and f2 == "hw-dd", f"{f1} → {f2}")

            # 난이도 메뉴: Enter로 열고 ↓, Esc로 닫으면 ▾로 포커스 복귀
            page.keyboard.press("Enter"); page.wait_for_timeout(120)
            first = page.evaluate("document.activeElement.dataset.hwPick")
            page.keyboard.press("ArrowDown")
            second = page.evaluate("document.activeElement.dataset.hwPick")
            check("▾ Enter → 메뉴 첫 항목, ↓ → 다음", first == "노말" and second == "하드", f"{first},{second}")
            page.screenshot(path=str(OUT / "menu-open.png"), clip={"x": 300, "y": 400, "width": 1236, "height": 420})
            page.keyboard.press("Escape"); page.wait_for_timeout(80)
            check("Esc → 메뉴 닫힘·▾로 포커스 복귀", page.evaluate("document.activeElement.className") == "hw-dd"
                  and page.locator(".hw-dd-menu:visible").count() == 0)

            # 난이도 고르기 → 저장(새로고침 뒤에도 유지)
            t.locator(".hw-dd").click(); page.wait_for_timeout(80)
            page.locator(f'#{t.locator(".hw-dd").get_attribute("aria-controls")} [data-hw-pick="노말"]').click(); page.wait_for_timeout(400)
            check("난이도 고르면 바로 바뀜", t.get_attribute("data-diff") == "노말" and t.locator("[data-dd-label]").inner_text() == "노말")
            page.reload(wait_until="networkidle")
            check("고른 난이도는 새로고침해도 유지", tile("발키리", "종막").get_attribute("data-diff") == "노말")

            # 난이도 저장 실패 → 되돌림 + 흔들기 + 토스트
            page.route("**/raid-check/difficulty-pref", lambda r: r.fulfill(status=400, content_type="application/json", body=json.dumps({"success": False, "reason": "저장 실패 테스트"})))
            t = tile("발키리", "종막")
            t.locator(".hw-dd").click(); page.wait_for_timeout(80)
            page.locator(f'#{t.locator(".hw-dd").get_attribute("aria-controls")} [data-hw-pick="하드"]').click(); page.wait_for_timeout(300)
            check("난이도 저장 실패 → 원래대로 + 빨간 흔들림 + 토스트",
                  t.get_attribute("data-diff") == "노말" and "is-err" in t.get_attribute("class") and "저장 실패 테스트" in page.inner_text("body"))
            page.unroute("**/raid-check/difficulty-pref")

            # 칸 체크: 처리 중 원이 돌고, 완료되면 "노말 클리어" + 카운트 갱신
            held = []
            page.route("**/raid-check/toggle", lambda r: held.append(r))  # 응답을 붙잡아 두고 처리 중 모양을 본다
            done0 = page.inner_text("[data-hw-done]")
            t.locator(".hw-hit").click(); page.wait_for_timeout(150)
            check("체크 누르면 바로 완료 모양 + 처리 중 표시", "is-done" in t.get_attribute("class") and "is-busy" in t.get_attribute("class"))
            page.screenshot(path=str(OUT / "busy.png"), clip={"x": 300, "y": 400, "width": 1236, "height": 300})
            for r in held:
                r.continue_()
            page.wait_for_timeout(900)
            page.unroute("**/raid-check/toggle")
            check("체크 완료 → 클리어 표시·숫자 카드·머리줄 갱신",
                  "is-busy" not in t.get_attribute("class") and t.locator("[data-done-label]").inner_text() == "노말 클리어"
                  and int(page.inner_text("[data-hw-done]")) == int(done0) + 1
                  and page.inner_text('[data-stat="homework"] [data-stat-value]') == str(int(done0) + 1))
            chip = page.locator('.hw-chip[data-char="발키리"][data-raid="종막"]')
            check("레이드별 칩도 같이 체크됨", "is-done" in chip.get_attribute("class"))
            # 키보드 Space로 해제
            t.locator(".hw-hit").focus(); page.keyboard.press("Space"); page.wait_for_timeout(900)
            check("Space로 체크 해제", "is-done" not in t.get_attribute("class") and t.locator(".hw-hit").get_attribute("aria-pressed") == "false")

            # 체크 실패 → 되돌림 + 흔들기 + 토스트
            page.route("**/raid-check/toggle", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"success": False, "reason": "체크 실패 테스트"})))
            t.locator(".hw-hit").click(); page.wait_for_timeout(300)
            check("체크 실패 → 원래대로 + 빨간 흔들림 + 토스트",
                  "is-done" not in t.get_attribute("class") and "is-err" in t.get_attribute("class") and "체크 실패 테스트" in page.inner_text("body"))
            page.screenshot(path=str(OUT / "error.png"), clip={"x": 300, "y": 400, "width": 1236, "height": 300})
            page.unroute("**/raid-check/toggle")

            # 보기 전환·남은 것만(기억)
            page.click("[data-hw-view=raid]")
            check("레이드별 보기", page.is_visible("[data-hw-panel=raid]") and not page.is_visible("[data-hw-panel=char]"))
            page.click("[data-hw-left]")
            page.reload(wait_until="networkidle")
            check("보기·남은 것만 설정 기억", page.is_visible("[data-hw-panel=raid]") and page.get_attribute("[data-hw-left]", "aria-pressed") == "true"
                  and page.locator(".hw-chip.is-done:visible").count() == 0)
            page.screenshot(path=str(OUT / "raid-view.png"), full_page=True)
            page.click("[data-hw-view=char]"); page.click("[data-hw-left]")

            # 호버는 마우스 기기에서만: 터치 기기에서 칸 테두리가 안 바뀌어야
            m = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
            m.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
            mp = m.new_page(); mp.goto(BASE + "/main", wait_until="networkidle")
            hover_rule = mp.evaluate("matchMedia('(hover: hover)').matches")
            check("휴대폰: (hover: hover) 아님 → 올림 효과 없음", hover_rule is False)
            m.close()
            ctx.close()

        check("페이지 스크립트 오류 없음", not errors, "; ".join(errors[:3]))
        browser.close()
finally:
    web.terminate(); stub.terminate()
    try:
        web.wait(5); stub.wait(5)
    except Exception:
        web.kill(); stub.kill()
fails = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)
