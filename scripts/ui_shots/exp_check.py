"""원정대·더보기 묶음 화면 점검 — 스크린샷(데스크톱 1280 + 모바일 390) + 상호작용(동기화 처리 중, 골드섬 스위치, 시세 채우기, 인라인 오류).
사용: SHOT_BOT_PORT=8787 SHOT_WEB_PORT=8788 python scripts/ui_shots/exp_check.py   → out/exp/*.jpg + 콘솔 결과"""
import base64, io, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
OUT = HERE / "out" / "exp"
OUT.mkdir(parents=True, exist_ok=True)
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8765")
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8766")
BASE = f"http://127.0.0.1:{WEB_PORT}"
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"{BASE}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "out" / "notif_exp.db"), "PYTHONIOENCODING": "utf-8"}


def wait(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=5).read()


PAGES = [("expedition", "/expedition"), ("ranking", "/ranking"), ("ranking-growth", "/ranking?metric=combat_power&role=dps&sort=growth"),
         ("ranking-weekly", "/ranking?metric=weekly_clears"), ("character", "/characters/발키리"), ("character-empty", "/characters/소서리스"),
         ("settings", "/settings"), ("more", "/more"), ("auction", "/tools/auction-calculator"), ("guide", "/guide")]

stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"],
                       cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


try:
    assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids") and wait(f"{BASE}/health")
    from itsdangerous import TimestampSigner
    session = {"user": {"discord_id": "111", "username": "발키리", "is_admin": True, "avatar_url": None, "admin_mode": True}}
    cookie = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps(session).encode())).decode()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        errors = []
        for vpname, vp in (("desktop", {"width": 1280, "height": 900}), ("mobile", {"width": 390, "height": 844})):
            ctx = browser.new_context(viewport=vp)
            ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
            page = ctx.new_page()
            page.on("console", lambda m: errors.append((m.type, m.text)) if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: errors.append(("pageerror", str(e))))
            for tag, path in PAGES:
                page.goto(BASE + path, wait_until="networkidle")
                page.wait_for_timeout(300)
                page.screenshot(path=str(OUT / f"{tag}-{vpname}.jpg"), full_page=True, type="jpeg", quality=70)
                over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if over > 0:
                    check(f"가로 넘침 없음 {vpname} {tag}", False, f"{over}px")
            ctx.close()
        check("콘솔 오류·경고 없음", not errors, str(errors[:3]))

        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        # 1) 동기화 — 눌리면 aria-busy, 끝나면 완료 토스트
        page.goto(BASE + "/expedition", wait_until="networkidle")
        btn = page.locator("[data-sync-form] button")
        # 이동이 시작되면 이 페이지의 JS 컨텍스트가 사라지므로, 처리 중 상태는 관찰자가 sessionStorage에 남겨 둔다
        page.evaluate("""() => { sessionStorage.removeItem('busySeen'); const b=document.querySelector('[data-sync-form] button');
          new MutationObserver(() => { if (b.getAttribute('aria-busy') === 'true') sessionStorage.setItem('busySeen', b.getAttribute('aria-label') || '1'); }).observe(b, {attributes: true}); }""")
        btn.click(no_wait_after=True)
        page.wait_for_selector(".toast", timeout=8000)
        check("동기화 버튼 aria-busy(처리 중 문구)", page.evaluate("sessionStorage.getItem('busySeen')") == "동기화 중", str(page.evaluate("sessionStorage.getItem('busySeen')")))
        check("동기화 완료 토스트", "3/3" in page.inner_text(".toast"), page.inner_text(".toast"))
        # 2) pending 응답
        post_json(f"http://127.0.0.1:{BOT_PORT}/__stub/sync-mode", {"mode": "pending"})
        page.goto(BASE + "/expedition", wait_until="networkidle")
        page.locator("[data-sync-form] button").click(no_wait_after=True)
        page.wait_for_selector(".toast.info", timeout=8000)
        check("pending 안내 토스트", "뒤에서 계속 진행" in page.inner_text(".toast.info"), page.inner_text(".toast.info"))
        page.screenshot(path=str(OUT / "expedition-pending-desktop.jpg"), type="jpeg", quality=70)
        post_json(f"http://127.0.0.1:{BOT_PORT}/__stub/sync-mode", {"mode": "ok"})
        # 3) 캐릭터 추가 인라인 오류
        page.goto(BASE + "/expedition", wait_until="networkidle")
        page.fill("form.exp-form-row input", "없는캐릭터")
        page.locator("form.exp-form-row button").click()
        page.wait_for_timeout(800)
        help_el = page.locator("#exp-add-help")
        check("캐릭터 추가 인라인 오류", "찾을 수 없습니다" in help_el.inner_text() and "is-error" in (help_el.get_attribute("class") or ""), help_el.inner_text())
        check("입력칸 aria-invalid", page.locator("form.exp-form-row input").get_attribute("aria-invalid") == "true")
        page.screenshot(path=str(OUT / "expedition-error-desktop.jpg"), type="jpeg", quality=70)
        # 4) 부계정 인라인 오류(키 칸으로)
        page.fill("input[name=api_key]", "bad")
        page.fill(".exp-acc-form input[name=character_name]", "아무개")
        page.locator(".exp-acc-form button[type=submit]").click()
        page.wait_for_timeout(800)
        check("부계정 오류가 키 칸에", page.locator("input[name=api_key]").get_attribute("aria-invalid") == "true" and "API 키" in page.inner_text("#exp-acc-help"), page.inner_text("#exp-acc-help"))
        page.screenshot(path=str(OUT / "expedition-acc-error-desktop.jpg"), type="jpeg", quality=70)
        # 5) 골드섬 스위치
        page.goto(BASE + "/settings", wait_until="networkidle")
        sw = page.locator('button[aria-labelledby="set-gold"]')
        before = sw.get_attribute("aria-checked")
        sw.click()
        page.wait_for_timeout(700)
        after = sw.get_attribute("aria-checked")
        check("골드섬 스위치 토글", before == "false" and after == "true", f"{before}->{after}")
        check("스위치 상태 글자", "켜짐" in page.locator("form[data-switch-json] [data-switch-state]").inner_text())
        page.reload(wait_until="networkidle")
        check("새로고침 후에도 켜짐", page.locator('button[aria-labelledby="set-gold"]').get_attribute("aria-checked") == "true")
        page.locator('button[aria-labelledby="set-gold"]').click()
        page.wait_for_timeout(500)
        # 6) 계산기 시세 채우기
        page.goto(BASE + "/tools/auction-calculator", wait_until="networkidle")
        page.locator(".themed-select-trigger").first.click()
        page.wait_for_timeout(200)
        page.locator(".themed-select-option", has_text="원한").click()
        page.wait_for_timeout(300)
        check("시세 가격 채움", page.input_value("#calc-price") == "143000", page.input_value("#calc-price"))
        check("계산 결과 갱신", page.inner_text("#calc-use-bid") == "125,125 골드", page.inner_text("#calc-use-bid"))
        page.screenshot(path=str(OUT / "auction-filled-desktop.jpg"), type="jpeg", quality=70)
        # 7) 랭킹 정렬 링크
        page.goto(BASE + "/ranking", wait_until="networkidle")
        page.locator(".exp-sort").click()
        page.wait_for_load_state("networkidle")
        first = page.locator("tbody tr").first.inner_text()
        check("7일 성장 큰 순 정렬", "건슬" in first, first.replace("\n", " ")[:50])
        check("aria-sort", page.locator("th[aria-sort=descending]").count() == 1)
        browser.close()
finally:
    web.terminate()
    stub.terminate()
    try:
        web.wait(5)
        stub.wait(5)
    except Exception:
        web.kill()
        stub.kill()
print("failed:", sum(1 for r in results if not r[1]))
