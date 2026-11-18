"""공대 화면 상호작용 점검 — ⋯ 메뉴 → 강제 퇴장 → 확인 대화상자 → Esc 포커스 복귀, 일정 변경·초대 팝오버,
공대 열기의 '다시 열기' 채움·경고 배너, 목록의 참여 폼, 모든 화면의 콘솔 오류.
사용: SHOT_BOT_PORT=8783 SHOT_WEB_PORT=8784 python scripts/ui_shots/interact_party.py"""
import base64, io, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8765")
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8766")
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"http://127.0.0.1:{WEB_PORT}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "out" / "notif-ip.db"), "PYTHONIOENCODING": "utf-8"}
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


FOCUS = "() => { const a = document.activeElement; if (!a) return ''; return (a.id ? '#' + a.id + ' ' : '') + a.tagName.toLowerCase() + ' [' + (a.getAttribute('aria-label') || a.innerText || '').trim().slice(0, 20) + ']'; }"
stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"],
                       cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids") and wait(f"{BASE}/health")
    from itsdangerous import TimestampSigner
    user = {"discord_id": "111", "username": "발키리", "is_admin": False, "avatar_url": None, "admin_mode": False}
    cookie = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps({"user": user}).encode())).decode()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1. 메뉴 -> 강제 퇴장 -> 확인 -> Esc
        page.goto(f"{BASE}/parties/p1", wait_until="networkidle")
        trigger = page.locator('button[aria-label="리퍼짱 메뉴"]')
        trigger.click()
        check("메뉴(⋯)가 열린다", page.locator("#mm-2").is_visible())
        page.screenshot(path=str(HERE / "out" / "party" / "interact-menu.jpg"), type="jpeg", quality=70)
        check("메뉴를 열면 첫 항목에 포커스", "파티장 위임" in page.evaluate(FOCUS), page.evaluate(FOCUS))
        page.keyboard.press("ArrowDown")
        page.get_by_role("menuitem", name="강제 퇴장").click()
        page.wait_for_timeout(200)
        dlg = page.locator(".dlg-back")
        check("확인 대화상자에 멤버 이름이 들어간다", dlg.count() == 1 and "리퍼짱 님을 내보낼까요?" in dlg.inner_text(), dlg.inner_text().replace("\n", " ")[:60] if dlg.count() else "")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        check("Esc로 대화상자가 닫힌다", page.locator(".dlg-back").count() == 0)
        foc = page.evaluate(FOCUS)
        check("대화상자를 닫으면 포커스가 메뉴로 돌아온다", "강제 퇴장" in foc or "리퍼짱 메뉴" in foc, foc)
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        check("Esc로 메뉴가 닫히고 메뉴 버튼에 포커스", not page.locator("#mm-2").is_visible() and "리퍼짱 메뉴" in page.evaluate(FOCUS), page.evaluate(FOCUS))

        # 2. 일정 변경 팝오버
        page.get_by_role("button", name="일정 변경").first.click()
        page.wait_for_timeout(200)
        check("일정 변경 팝오버가 열리고 날짜가 채워진다", page.locator("#reschedule-pop").is_visible() and page.locator("#reschedule-pop label").first.locator("input[type=text]").input_value() != "")
        page.screenshot(path=str(HERE / "out" / "party" / "interact-reschedule.jpg"), type="jpeg", quality=70)
        page.locator("#reschedule-pop label").first.locator("input[type=text]").click()
        page.wait_for_timeout(200)
        check("날짜 선택기를 열어도 팝오버가 유지된다", page.locator("#reschedule-pop").is_visible())
        page.get_by_role("button", name="+1시간").click()
        check("+1시간 빠른 조정 후에도 팝오버 유지", page.locator("#reschedule-pop").is_visible())
        page.keyboard.press("Escape"); page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        check("Esc로 팝오버가 닫히고 일정 변경 버튼에 포커스", not page.locator("#reschedule-pop").is_visible() and "일정 변경" in page.evaluate(FOCUS), page.evaluate(FOCUS))

        # 3. 빈 자리 초대 팝오버
        page.locator('[data-invite-slot="5"]').click()
        page.wait_for_timeout(200)
        title = page.locator("#invite-title").inner_text()
        check("초대 팝오버가 열리고 5번 자리가 선택돼 있다", page.locator("#invite-slot").input_value() == "5" and "2파티 1번" in title, title)
        page.screenshot(path=str(HERE / "out" / "party" / "interact-invite.jpg"), type="jpeg", quality=70)
        page.keyboard.press("Escape"); page.wait_for_timeout(150)
        check("Esc로 초대 팝오버 닫힘", not page.locator("#invite-pop").is_visible())

        # 4. 공대 열기: 다시 열기 칩
        page.goto(f"{BASE}/parties/create", wait_until="networkidle")
        check("제출 버튼은 레이드·일정 전에는 비활성", page.locator("#party-create-submit").is_disabled())
        chip = page.locator("[data-reopen]").first
        label = chip.inner_text()
        chip.click(); page.wait_for_timeout(700)
        raid, diff = page.locator("#raid-name-input").input_value(), page.locator("#difficulty-input").input_value()
        check("다시 열기: 레이드·난이도가 채워진다", raid != "" and diff != "", f"{raid} {diff} / {label}")
        check("다시 열기: 일정이 채워진다", page.locator("#scheduled-datetime-input").input_value() != "")
        check("다시 열기 후 제출 가능", page.locator("#party-create-submit").is_enabled())
        rows = page.locator("#char-list .pt-copt").all_inner_texts()
        check("이번 주 완료한 캐릭터는 사유와 함께 비활성", any("발키리" in r and "이번 주 완료" in r for r in rows), " | ".join(x.replace(chr(10), " ") for x in rows)[:160])
        check("같은 레이드의 같은 주 다른 공대에 있는 캐릭터도 사유와 함께 비활성", any("워로드부캐" in r and "다른 공대" in r for r in rows))
        check("레벨 부족 캐릭터는 비활성", page.locator("#char-list input:disabled").count() >= 1)
        # 충돌 없는 레이드(세르카 하드)로 바꾸면 추천 캐릭터가 선택된다
        page.evaluate("() => { [...document.querySelectorAll('.pt-seg button')].find(x => x.dataset.raid === '세르카' && x.dataset.diff === '하드').click(); }")
        page.wait_for_timeout(800)
        chosen = page.locator("#char-list input:checked").first.input_value()
        check("추천 캐릭터가 자동 선택된다(서포터 없는 새 공대는 서포터 우선)", chosen == "발키리", chosen)
        # 중복 경고: p1(4막 하드)과 같은 시간대
        page.evaluate("""() => { const b = [...document.querySelectorAll('.pt-seg button')].find(x => x.dataset.raid === '아르모체(4막)' && x.dataset.diff === '하드'); b.click();
            document.querySelector('#scheduled-datetime-input')._flatpickr.setDate(new Date(Date.now() + 3 * 3600e3), true); }""")
        page.wait_for_timeout(800)
        dup = page.locator("#warn-dup")
        check("같은 레이드·1시간 이내 모집 중이면 경고 배너", dup.is_visible() and "이미 모집 중" in dup.inner_text(), dup.inner_text().replace("\n", " "))
        page.evaluate("document.querySelector('#scheduled-datetime-input')._flatpickr.setDate(new Date(Date.now() + 9 * 86400e3), true)")
        page.wait_for_timeout(800)
        check("리셋 이후 일정이면 '다음 주 숙제' 경고", page.locator("#warn-reset").is_visible() and not page.locator("#warn-dup").is_visible())
        page.screenshot(path=str(HERE / "out" / "interact-create.jpg"), full_page=True, type="jpeg", quality=70)

        # 5. 목록 참여 폼
        page.goto(f"{BASE}/parties?filter=all", wait_until="networkidle")
        form = page.locator('form[action="/parties/p2/join"]')
        check("목록에 참여 폼(캐릭터 select + 참여 버튼)", form.count() == 1 and form.locator("button[type=submit]").is_visible())
        role = form.locator("input[name=role]").input_value()
        check("역할이 캐릭터에서 추론된다(서포터 캐릭터는 support)", role == "support", role)
        group = form.locator("input[name=party_group]").input_value()
        check("분할 공대는 파티가 자동 선택된다", group in ("1", "2"), group)

        # 6. 콘솔 오류 - 모든 화면
        for path in ["/parties", "/parties?filter=mine", "/parties/create", "/parties/p1", "/parties/p2", "/parties/p5", "/parties/p6", "/parties/p7", "/parties/p8", "/parties/history", "/calendar", "/calendar?view=week"]:
            page.goto(BASE + path, wait_until="networkidle")
        check("콘솔 오류 없음", not errors, "; ".join(errors)[:300])
        browser.close()
finally:
    web.terminate(); stub.terminate()
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} 통과")
sys.exit(1 if failed else 0)
