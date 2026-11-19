"""셸·팝업·확인 대화상자 키보드 동작 점검 — Tab 순서, Esc 닫힘·포커스 복귀, 포커스 가둠, 접기 기억.
사용: python interact.py  → out/interact/*.jpg + 콘솔에 PASS/FAIL"""
import base64, io, json, os, subprocess, sys, time, urllib.request
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
OUT = HERE / "out" / "interact"
OUT.mkdir(parents=True, exist_ok=True)
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8765")
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8766")
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"http://127.0.0.1:{WEB_PORT}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "out" / "notif-interact.db"), "PYTHONIOENCODING": "utf-8"}
BASE = f"http://127.0.0.1:{WEB_PORT}"
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def wait(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1); return True
        except Exception:
            time.sleep(0.5)
    return False


FOCUS = "() => { const a = document.activeElement; if (!a) return ''; return (a.id ? '#' + a.id + ' ' : '') + a.tagName.toLowerCase() + '.' + (a.className && a.className.baseVal === undefined ? a.className : '') + ' [' + (a.getAttribute('aria-label') || a.innerText || '').trim().slice(0, 20) + ']'; }"

stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"],
                       cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids") and wait(f"{BASE}/health")
    # 알림 팝오버를 채울 예시 알림(오늘 2 + 이번 주 2, 그중 1개는 읽음)
    import asyncio, sqlite3
    os.environ.update({k: v for k, v in ENV.items() if k not in os.environ or k == "NOTIFICATION_DB_PATH"})
    sys.path.insert(0, ROOT)
    from webapp import notification_store as ns
    async def seed():
        await ns.init_db()
        await ns.set_subscribed("111", True)
        await ns.add_notification("invited", "p2", "종막 노말 공대에 초대됐습니다", target_discord_id="111")
        await ns.add_notification("party_starting", "p1", "세르카 하드 일정이 지났습니다. 클리어 처리해 주세요", target_discord_id="111")
        await ns.add_notification("rescheduled", "p1", "아르모체(4막) 하드 일정이 내일 01:46으로 바뀌었습니다", target_discord_id="111")
        n = await ns.add_notification("created", "p3", "카멘 익스트림 노말 공대 모집이 시작됐습니다")
        await ns.mark_read("111", n["id"])
    con = sqlite3.connect(ENV["NOTIFICATION_DB_PATH"]); con.execute("DELETE FROM notifications"); con.commit(); con.close()
    asyncio.run(seed())
    con = sqlite3.connect(ENV["NOTIFICATION_DB_PATH"])
    con.execute("UPDATE notifications SET created_at = datetime(created_at, '-2 days') || '+00:00' WHERE type IN ('rescheduled', 'created')")
    con.commit(); con.close()
    from itsdangerous import TimestampSigner
    cookie = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps({"user": {"discord_id": "111", "username": "발키리", "is_admin": True, "avatar_url": None, "admin_mode": True}}).encode())).decode()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1) Tab 순서: 건너뛰기 → 길드 → 메뉴 4 + 관리 → 접기 → 프로필 → 종
        page.goto(BASE + "/main", wait_until="networkidle"); page.wait_for_timeout(300)
        check("안 읽은 알림 수가 탭 제목 앞에", page.title().startswith("("), page.title())
        order = []
        # 건너뛰기 → (위 머리줄) 길드 · 테마 · 종 · 프로필 → (왼쪽 메뉴) 메인 3 · 도구 3 · 관리 → 접기
        for _ in range(13):
            page.keyboard.press("Tab"); order.append(page.evaluate(FOCUS))
        print("  tab order:", *order, sep="\n    ")
        check("Tab 1 = 본문으로 건너뛰기", "skip-link" in order[0])
        check("Tab 순서: 머리줄(테마·종·프로필)이 메뉴보다 먼저", order.index(next(o for o in order if "[홈" in o)) > max(i for i, o in enumerate(order) if "theme-btn" in o or "notif-bell" in o or "top-user" in o))
        check("Tab 순서에 홈·공대·원정대·알림 설정·분배금 계산기·이용 가이드·관리", all(any(k in o for o in order) for k in ("[홈", "[공대", "[원정대", "[알림 설정", "[분배금 계산기", "[이용 가이드", "[관리")))
        page.keyboard.press("Shift+Tab"); page.keyboard.press("Shift+Tab"); page.wait_for_timeout(250)
        page.screenshot(path=str(OUT / "focus-nav.jpg"), type="jpeg", quality=80, clip={"x": 0, "y": 0, "width": 420, "height": 320})
        # 건너뛰기 링크 동작
        page.goto(BASE + "/main", wait_until="networkidle")
        page.keyboard.press("Tab"); page.keyboard.press("Enter")
        check("건너뛰기 → main에 포커스", page.evaluate("document.activeElement.id") == "main")

        # 2) 1400 미만은 처음에 접힘 → 펼치기 기억 → 다시 접기 기억 → 접힌 메뉴 툴팁
        side_w = "document.querySelector('.side-col').getBoundingClientRect().width"
        w0 = page.evaluate(side_w)
        check("1280: 처음엔 접힘(64px)", abs(w0 - 64) < 1, f"{w0}")
        page.click("[data-nav-fold]"); page.wait_for_timeout(350)  # 폭 전환 0.2s
        check("펼치면 252px", abs(page.evaluate(side_w) - 252) < 1, f"{page.evaluate(side_w)}")
        page.reload(wait_until="networkidle")
        check("새로고침해도 펼침 유지", abs(page.evaluate(side_w) - 252) < 1, f"{page.evaluate(side_w)}")
        page.click("[data-nav-fold]"); page.wait_for_timeout(350)
        w = page.evaluate(side_w)
        check("접으면 64px", abs(w - 64) < 1, f"{w}")
        page.reload(wait_until="networkidle")
        w2 = page.evaluate(side_w)
        check("새로고침해도 접힘 유지", abs(w2 - 64) < 1, f"{w2}")
        page.hover(".side-link[href='/parties']"); page.wait_for_timeout(250)
        page.screenshot(path=str(OUT / "rail-hover.jpg"), type="jpeg", quality=80, clip={"x": 0, "y": 0, "width": 360, "height": 320})
        page.focus(".side-link[href='/expedition']"); page.keyboard.press("Tab"); page.keyboard.press("Shift+Tab"); page.wait_for_timeout(200)
        tip_vis = page.evaluate("getComputedStyle(document.querySelector(\".side-link[href='/expedition']\"), '::after').opacity")
        check("접힌 메뉴: 키보드 포커스에 이름 표시", tip_vis == "1", tip_vis)
        page.screenshot(path=str(OUT / "rail-full.jpg"), type="jpeg", quality=70)
        page.click("[data-nav-fold]")

        # 3) 알림 팝오버: Enter로 열고, Esc로 닫고 종으로 포커스 복귀
        page.focus("#notif-bell"); page.keyboard.press("Enter"); page.wait_for_timeout(600)
        check("종 Enter → 팝오버 열림", page.is_visible("#notif-panel") and page.get_attribute("#notif-bell", "aria-expanded") == "true")
        page.screenshot(path=str(OUT / "notif-open.jpg"), type="jpeg", quality=80)
        page.click("#notif-panel [data-notif-tab=unread]"); page.wait_for_timeout(100)
        page.screenshot(path=str(OUT / "notif-unread-tab.jpg"), type="jpeg", quality=80, clip={"x": 740, "y": 0, "width": 540, "height": 520})
        page.click("#notif-panel [data-notif-tab=all]")
        check("오늘/이번 주 묶음", page.locator("#notif-panel [data-group-head]").count() >= 2)
        check("열면 배지 0 + 탭 제목 숫자 없음", page.is_hidden("#notif-bell .bell-cnt") and not page.title().startswith("("), page.title())
        tabs_ok = page.evaluate("!!document.querySelector('#notif-panel [data-notif-tab=\"unread\"]') || !!document.querySelector('#notif-panel .ui-empty')")
        check("팝오버 내용(탭 또는 빈 상태) 표시", tabs_ok)
        page.keyboard.press("Escape"); page.wait_for_timeout(150)
        check("Esc → 닫힘", not page.is_visible("#notif-panel"))
        check("Esc → 종으로 포커스 복귀", page.evaluate("document.activeElement.id") == "notif-bell", page.evaluate(FOCUS))
        page.click("#notif-bell"); page.wait_for_timeout(300)
        page.mouse.click(700, 600); page.wait_for_timeout(150)
        check("바깥 클릭 → 닫힘", not page.is_visible("#notif-panel"))

        # 4) 프로필 메뉴: Enter → 첫 항목, ↓ 이동, Esc 복귀
        page.focus(".top-user"); page.keyboard.press("Enter"); page.wait_for_timeout(100)
        first = page.evaluate(FOCUS)
        check("프로필 Enter → 메뉴 첫 항목 포커스", "알림 설정" in first, first)
        page.keyboard.press("ArrowDown")
        second = page.evaluate(FOCUS)
        check("↓ → 다음 항목", "관리자 모드" in second, second)
        page.wait_for_timeout(250)
        page.screenshot(path=str(OUT / "profile-menu.jpg"), type="jpeg", quality=80, clip={"x": 860, "y": 0, "width": 420, "height": 340})
        page.keyboard.press("Escape")
        check("Esc → 메뉴 닫힘·프로필로 복귀", page.is_hidden("#profile-menu") and "top-user" in page.evaluate(FOCUS))

        # 5) 확인 대화상자: 처음 포커스 취소, 포커스 가둠, Esc, 연 버튼으로 복귀
        page.goto(BASE + "/parties/p1", wait_until="networkidle")
        leave = page.locator("form[action$='/leave'] button[type=submit]")
        leave.focus(); page.keyboard.press("Enter"); page.wait_for_timeout(150)
        check("나가기 → 대화상자", page.is_visible(".dlg"))
        check("처음 포커스 = 취소", page.evaluate("document.activeElement.textContent") == "취소")
        page.screenshot(path=str(OUT / "confirm.jpg"), type="jpeg", quality=80)
        seq = []
        for k in ("Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab"):
            page.keyboard.press(k); seq.append(page.evaluate("document.activeElement.textContent"))
        check("포커스 가둠(취소↔나가기)", seq == ["나가기", "취소", "나가기", "취소", "나가기"], str(seq))
        page.keyboard.press("Escape"); page.wait_for_timeout(100)
        check("Esc → 닫힘", page.locator(".dlg").count() == 0)
        check("연 버튼으로 포커스 복귀", page.evaluate("document.activeElement.textContent.trim()") == "나가기")
        leave.click(); page.wait_for_timeout(100)
        page.mouse.click(20, 880); page.wait_for_timeout(100)
        check("바깥(배경) 클릭 → 닫힘", page.locator(".dlg").count() == 0)
        check("취소하면 제출 안 됨", page.url.endswith("/parties/p1"))

        # 6) 이름에 따옴표·꺾쇠가 있어도 확인 문구가 글자 그대로(스크립트 주입 없음)
        # 관리 > 레이드 편집 화면(2단계 개편 후): 기본 정보 폼의 이름 칸을 바꾸고 저장하면 확인창이 뜬다
        page.goto(BASE + "/admin/raids", wait_until="networkidle")
        form = page.locator("form[action='/admin/raids/save']").first
        form.locator("input[name=name]").fill("A'B\"<img src=x onerror=alert(1)>")
        form.locator("button[type=submit]").click(); page.wait_for_timeout(400)
        txt = page.evaluate("(function(){var d=[...document.querySelectorAll('.dlg')].find(e=>e.offsetParent);return d&&d.innerText})()")
        if not txt:
            print("DEBUG url", page.url, "dlgs", page.evaluate("[...document.querySelectorAll('.dlg,.dlg-back,[role=dialog]')].map(e=>e.className+':'+(e.offsetParent?'vis':'hid')).join(' | ')"))
        check("이름 변경 확인에 새 이름이 글자 그대로", bool(txt) and "<img src=x onerror=alert(1)>" in txt and page.locator(".dlg img").count() == 0, (txt or "")[:80])
        page.screenshot(path=str(OUT / "confirm-rename.jpg"), type="jpeg", quality=80)
        page.keyboard.press("Escape")

        # 7) 토스트(되돌리기 버튼·올리면 멈춤) + 처리 중 버튼 폭 유지 + 배너
        page.goto(BASE + "/parties/p1", wait_until="networkidle")
        page.evaluate("showToast('ok', '발키리 · 4막 하드 완료로 표시했습니다', {actionLabel: '되돌리기', onAction: function(){ window.__undo = 1; }})")
        page.evaluate("showToast('err', '저장하지 못했습니다. 봇 서버 응답 없음', {actionLabel: '다시 시도'})")
        page.evaluate("showToast('공대 정보가 바뀌어 새로 불러왔습니다', 'info')")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "toasts.jpg"), type="jpeg", quality=80, clip={"x": 700, "y": 600, "width": 580, "height": 300})
        page.hover(".toast >> nth=0"); page.wait_for_timeout(5600)
        check("올리고 있으면 5초 지나도 남음", page.locator(".toast").count() >= 1)
        page.locator(".toast .btn").first.click(); page.wait_for_timeout(50)
        check("되돌리기 버튼 → onAction", page.evaluate("window.__undo") == 1)
        btn = page.locator(".page-content button.btn").first
        w_before = btn.evaluate("e => e.getBoundingClientRect().width")
        btn.evaluate("e => e.setAttribute('aria-busy', 'true')")
        w_after = btn.evaluate("e => e.getBoundingClientRect().width")
        check("처리 중 스피너: 버튼 폭 그대로", abs(w_before - w_after) < 0.5, f"{w_before}→{w_after}")
        page.evaluate("""document.querySelector('.page-content').insertAdjacentHTML('afterbegin',
          '<div class="banner info"><span>이 공대에 바뀐 내용이 있습니다</span><button class="btn sm pri">지금 반영</button></div>' +
          '<div class="banner err"><b class="banner-mark">!</b><span>봇 서버에 연결할 수 없습니다. 3분 전 데이터를 보여주는 중</span><button class="btn sm">다시 시도</button></div>' +
          '<div class="banner warn"><b class="banner-mark">!</b><span>정기 점검 중 · 10:00 종료 예정</span></div>')""")
        page.wait_for_timeout(250)
        page.screenshot(path=str(OUT / "feedback.jpg"), type="jpeg", quality=80)

        # 8) 모바일: 위 줄 종 → 팝오버, 하단 탭 4개
        m = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
        m.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
        mp = m.new_page()
        mp.on("pageerror", lambda e: errors.append(str(e)))
        mp.goto(BASE + "/main", wait_until="networkidle")
        check("모바일 하단 탭 4개", mp.locator(".tabbar a").count() == 4 and mp.is_visible(".tabbar"))
        check("모바일: 왼쪽 메뉴 숨김", not mp.is_visible("#sidebar"))
        check("모바일: 위 머리줄(종·테마) 보임", mp.is_visible(".top #notif-bell") and mp.is_visible("[data-theme-toggle]"))
        mp.click("#notif-bell"); mp.wait_for_timeout(500)
        check("모바일 종 → 팝오버", mp.is_visible("#notif-panel"))
        mp.screenshot(path=str(OUT / "mobile-notif.jpg"), type="jpeg", quality=80)
        mp.keyboard.press("Escape")
        mp.goto(BASE + "/parties/p1", wait_until="networkidle")
        mp.locator("form[action$='/leave'] button[type=submit]").click(); mp.wait_for_timeout(150)
        mp.screenshot(path=str(OUT / "mobile-confirm.jpg"), type="jpeg", quality=80)
        m.close()

        # 9) 태블릿(761~1024): 접힌 띠 고정 / 비로그인 가이드
        t = browser.new_context(viewport={"width": 900, "height": 800})
        t.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
        tp = t.new_page(); tp.goto(BASE + "/parties", wait_until="networkidle")
        check("태블릿: 메뉴 64px 띠", abs(tp.evaluate("document.querySelector('.side-col').getBoundingClientRect().width") - 64) < 1)
        tp.screenshot(path=str(OUT / "tablet-parties.jpg"), type="jpeg", quality=70)
        t.close()
        g = browser.new_context(viewport={"width": 1280, "height": 800})
        gp = g.new_page(); gp.goto(BASE + "/guide", wait_until="networkidle")
        gp.screenshot(path=str(OUT / "guest-guide.jpg"), type="jpeg", quality=70)
        g.close()

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
