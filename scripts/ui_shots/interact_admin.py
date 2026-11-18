"""관리 화면 상호작용 점검 — 목록에서 레이드 고르기, 순서 바 표시, 난이도 대화상자, 유저 내보내기 영향 범위,
Esc 닫힘·포커스 복귀, 공대 KPI 필터, 전체 공지 미리보기·진행률, 시세 아이템 칩, 작업 기록 되돌리기 확인, 콘솔 오류 0.
사용: SHOT_BOT_PORT=8785 SHOT_WEB_PORT=8786 python interact_admin.py → out/interact-admin/*.png + PASS/FAIL"""
import base64, io, json, os, subprocess, sys, time, urllib.request
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
OUT = HERE / "out" / "interact-admin"
OUT.mkdir(parents=True, exist_ok=True)
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8765")
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8766")
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"http://127.0.0.1:{WEB_PORT}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "out" / "notif-interact-admin.db"), "PYTHONIOENCODING": "utf-8"}
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


stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"],
                       cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids") and wait(f"{BASE}/health")
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
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        # 1) 레이드: 목록에서 고르면 편집기가 바뀐다
        page.goto(BASE + "/admin/raids", wait_until="networkidle")
        check("처음엔 첫 레이드가 선택됨", "아르모체(4막)" in page.inner_text("#raid-editor h2"))
        page.click("a.ad-ri-link:has-text('종막')")
        page.wait_for_load_state("networkidle")
        check("종막을 고르면 주소에 ?raid= 가 붙음", "raid=" in page.url, page.url)
        check("편집기 제목이 종막으로 바뀜", "종막" in page.inner_text("#raid-editor h2"))
        check("기본 정보 이름 칸이 종막", page.input_value("#f-name") == "종막")
        check("클리어 골드 열이 표에 있음", "클리어 골드" in page.inner_text("#diff-table") and "2,300" in page.inner_text("#diff-table"))
        page.screenshot(path=str(OUT / "raids-select.png"), full_page=True)

        # 2) 순서: 처음엔 저장 바 없음 → ↓ 키로 바꾸면 나타남 → 되돌리기로 사라짐
        check("순서 저장 바는 처음엔 숨김", page.is_hidden("#raid-order-bar"))
        grip = page.locator(".ad-ri[data-key='아르모체(4막)'] .ad-grip")
        grip.focus(); page.keyboard.press("ArrowDown")
        page.wait_for_timeout(100)
        check("↓ 키로 순서를 바꾸면 저장 바가 나타남", page.is_visible("#raid-order-bar"))
        orders = json.loads(page.input_value("#raid-order-bar input[name=orders]"))
        check("바뀐 카테고리만 orders에 담김", list(orders.keys()) == ["카제로스"] and orders["카제로스"][0] == "종막", str(orders))
        page.screenshot(path=str(OUT / "raids-reorder-bar.png"), full_page=True)
        page.click("#raid-order-bar [data-reorder-reset]")
        check("되돌리기를 누르면 저장 바가 사라짐", page.is_hidden("#raid-order-bar"))
        # 끌어서 바꾸기도(드래그 이벤트)
        src = page.locator(".ad-ri[data-key='세르카'] .ad-grip"); dst = page.locator(".ad-ri[data-key='아르모체(4막)']")
        src.drag_to(dst, target_position={"x": 40, "y": 4})
        page.wait_for_timeout(150)
        check("끌어서 바꿔도 저장 바가 나타남", page.is_visible("#raid-order-bar"))
        # 저장하지 않고 다른 레이드를 누르면 확인
        page.click("a.ad-ri-link:has-text('카멘')")
        page.wait_for_timeout(200)
        check("순서가 바뀐 채 이동하면 확인 대화상자", page.locator(".dlg-back .dlg").count() == 1 and "저장하지 않았습니다" in page.inner_text(".dlg-back h2"))
        page.keyboard.press("Escape"); page.wait_for_timeout(100)
        check("Esc로 확인 대화상자가 닫히고 이동하지 않음", page.locator(".dlg-back").count() == 0 and "카멘" not in page.inner_text("#raid-editor h2"))

        # 3) 난이도 수정 대화상자
        page.goto(BASE + "/admin/raids?raid=종막", wait_until="networkidle")
        page.locator("[data-diff-edit]").nth(1).click()
        page.wait_for_timeout(150)
        check("난이도 수정 대화상자가 열리고 값이 채워짐", page.is_visible("#dlg-diff-t") and page.input_value("#d-name") == "하드" and page.input_value("#d-gold") == "2300")
        page.screenshot(path=str(OUT / "diff-dialog.png"))
        page.keyboard.press("Escape"); page.wait_for_timeout(100)
        check("Esc로 닫히고 포커스가 수정 버튼으로 돌아감", page.is_hidden("#dlg-diff-t") and page.evaluate("document.activeElement.hasAttribute('data-diff-edit')"))
        page.click("[data-diff-add]"); page.wait_for_timeout(100)
        check("난이도 추가 모드는 값이 비어 있고 add 경로", page.input_value("#d-name") == "" and page.get_attribute("#diff-form", "action").endswith("/difficulties/add"))
        page.keyboard.press("Escape")
        page.click("[data-dlg-open='#dlg-categories']"); page.wait_for_timeout(100)
        check("카테고리 편집 대화상자", page.is_visible("#dlg-categories-t") and page.input_value("input[name=new_name]") == "카제로스")
        page.screenshot(path=str(OUT / "categories-dialog.png"))
        page.keyboard.press("Escape")

        # 4) 유저: 내보내기 영향 범위
        page.goto(BASE + "/admin/users", wait_until="networkidle")
        btn = page.locator("[data-user-kick='333']")
        btn.click(); page.wait_for_selector("#kick-impact .num", timeout=3000)
        txt = page.inner_text(".dlg-back")
        check("내보내기 대화상자에 영향 범위(캐릭터 3개·공대 2개·새 파티장)", "캐릭터 3개" in txt and "2개" in txt and "바드님" in txt, txt.replace("\n", " | ")[:200])
        check("대화상자 제목에 이름", "버서커" in page.inner_text("#dlg-kick-t"))
        check("삭제 폼이 기존 삭제 경로를 가리킴", page.get_attribute("#kick-form", "action") == "/admin/users/333/delete")
        page.screenshot(path=str(OUT / "kick-dialog.png"))
        page.keyboard.press("Escape"); page.wait_for_timeout(100)
        check("Esc로 닫히고 내보내기 버튼으로 포커스 복귀", page.is_hidden("#dlg-kick-t") and page.evaluate("document.activeElement.getAttribute('data-user-kick')") == "333")
        page.click("[data-user-details='333']"); page.wait_for_selector("#ud-333 .ad-details", timeout=3000)
        check("상세가 행 아래에 펼쳐짐", "버서커부캐" in page.inner_text("#ud-333"))
        page.fill(".ad-search", "리퍼")
        check("검색하면 해당 유저만 보임", page.locator("#users-table tr[data-row]:visible").count() == 1)

        # 5) 공대: KPI 필터 + ⋯ 메뉴 + 클리어 되돌리기는 can_revert일 때만
        page.goto(BASE + "/admin/parties", wait_until="networkidle")
        check("처음엔 진행 중 5줄 모두 보임", page.locator("#open-table tr[data-row]:visible").count() == 5)
        page.click(".ad-kpi button[data-key='problem']")
        check("일정 지남 KPI를 누르면 1줄만", page.locator("#open-table tr[data-row]:visible").count() == 1)
        page.click(".ad-kpi button[data-key='problem']")
        check("다시 누르면 필터 해제", page.locator("#open-table tr[data-row]:visible").count() == 5)
        page.click(".ad-kpi button[data-key='closed']")
        check("마감 KPI는 마감 1줄 + 재개 버튼", page.locator("#open-table tr[data-row]:visible").count() == 1 and "재개" in page.inner_text("#open-table tr[data-row]:visible"))
        page.click(".ad-kpi button[data-key='closed']")
        page.locator("#open-table tr[data-row]").first.locator("[data-menu-trigger]").click(); page.wait_for_timeout(100)
        check("⋯ 메뉴가 열림", page.locator(".menu:not([hidden])").count() == 1)
        page.screenshot(path=str(OUT / "parties-menu.png"))
        page.keyboard.press("Escape"); page.wait_for_timeout(100)
        check("Esc로 메뉴 닫힘", page.locator(".menu:not([hidden])").count() == 0)
        page.locator("#open-table tr[data-row]").nth(1).locator("form[action$='/close'] button").click(); page.wait_for_timeout(150)
        check("강제 마감은 확인 대화상자를 먼저 띄움", page.locator(".dlg-back h2").count() == 1 and "마감할까요" in page.inner_text(".dlg-back h2"))
        page.keyboard.press("Escape")
        page.click("[data-dlg-open='#dlg-forum']"); page.wait_for_timeout(100)
        check("포럼 채널 변경 대화상자", page.is_visible("#dlg-forum-t"))
        page.keyboard.press("Escape")
        page.goto(BASE + "/admin/parties?tab=closed", wait_until="networkidle")
        rows = page.locator("#closed-table tr[data-row]")
        rows.nth(0).locator("[data-menu-trigger]").click()
        first_menu = page.locator(".menu:not([hidden])").inner_text()
        page.keyboard.press("Escape")
        rows.nth(1).locator("[data-menu-trigger]").click()
        second_menu = page.locator(".menu:not([hidden])").inner_text()
        check("클리어 되돌리기는 can_revert 공대에만", "클리어 되돌리기" in first_menu and "클리어 되돌리기" not in second_menu)
        page.keyboard.press("Escape")

        # 6) 알림: 전체 공지 미리보기 → 확인 → 진행률
        page.goto(BASE + "/admin/notifications?tab=broadcast", wait_until="networkidle")
        check("내용이 없으면 보내기 버튼 비활성", page.is_disabled("#bc-send"))
        page.fill("#bc-content", "이번 주 점검 안내입니다.\n수요일 06시에 시작합니다.")
        check("미리보기에 입력 내용이 보임", "수요일 06시" in page.inner_text("#bc-preview") and not page.is_disabled("#bc-send"))
        check("수신 대상 수 표시", "22" in page.inner_text("[data-bc-count]"))
        page.click("#bc-send"); page.wait_for_timeout(150)
        check("보내기 전에 대상 수·내용 확인 대화상자", "22명" in page.inner_text(".dlg-back h2") and "점검 안내" in page.inner_text(".dlg-back p"))
        page.screenshot(path=str(OUT / "broadcast-confirm.png"))
        page.keyboard.press("Escape"); page.wait_for_timeout(100)
        check("취소하면 발송 안 함(진행률 숨김)", page.is_hidden("#bc-progress"))
        page.click("#bc-send"); page.wait_for_timeout(100)
        page.click(".dlg-back .btn.pri"); page.wait_for_selector("#bc-progress:not([hidden])", timeout=4000)
        check("queued이면 진행률이 나타남", page.is_visible("#bc-progress"))
        page.screenshot(path=str(OUT / "broadcast-progress.png"))
        page.wait_for_selector("#bc-progress.is-done", timeout=12000)
        check("끝나면 완료로 바뀌고 22/22", page.inner_text("[data-bc-sent]") == "22" and "발송 완료" in page.inner_text("#bc-progress"))

        # 7) 시세 아이템
        page.goto(BASE + "/admin/notifications?tab=items", wait_until="networkidle")
        n0 = page.locator(".ad-tchip").count()
        page.fill("#tracked-input", "명예의 파편 주머니"); page.keyboard.press("Enter")
        check("Enter로 아이템 추가", page.locator(".ad-tchip").count() == n0 + 1)
        page.locator(".ad-tchip button[data-remove]").first.click()
        check("× 로 빼기", page.locator(".ad-tchip").count() == n0)
        check("개수 표시가 갱신", page.inner_text("#tracked-count").strip().startswith(str(n0)))

        # 8) 작업 기록: 되돌리기 확인
        page.goto(BASE + "/admin/actions", wait_until="networkidle")
        check("되돌릴 수 있는 줄에만 되돌리기 버튼(2개)", page.locator("form[action$='/undo'] button").count() == 2)
        check("되돌릴 수 없는 줄은 안내 문구", "되돌릴 수 없음" in page.inner_text("table"))
        page.locator("form[action$='/undo'] button").first.click(); page.wait_for_timeout(150)
        check("되돌리기는 확인 대화상자를 먼저 띄움", "되돌릴까요" in page.inner_text(".dlg-back h2"))
        page.keyboard.press("Escape")
        page.click("a.chip-btn:has-text('레이드')"); page.wait_for_load_state("networkidle")
        check("종류 칩이 ?kind= 로 걸러줌", "kind=raid" in page.url)

        check("콘솔·페이지 오류 없음", not errors, str(errors))
        browser.close()
finally:
    web.terminate(); stub.terminate()
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f"  FAILED: {failed}" if failed else ""))
