"""관리 화면 컨트롤 규격 실측 — measure.py의 판정 JS를 그대로 가져와 관리 탭 전체(+대화상자를 연 상태)에 돌린다.
같은 줄 컨트롤 높이 차이(>2px)나 늘어난 버튼이 나오면 출력, 없으면 'mismatches: 0'."""
import base64, io, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
JS = re.search(r'JS = r"""(.*?)"""', (HERE / "measure.py").read_text(encoding="utf-8"), re.S).group(1)
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8765")
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8766")
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"http://127.0.0.1:{WEB_PORT}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "out" / "notif-measure.db"), "PYTHONIOENCODING": "utf-8"}


def wait(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1); return True
        except Exception:
            time.sleep(0.5)
    return False


# (경로, 측정 전에 눌러 볼 선택자들) — 대화상자도 열어서 잰다
PAGES = [
    ("/admin/raids", []), ("/admin/raids", ["[data-diff-edit]"]), ("/admin/raids", ["[data-dlg-open='#dlg-categories']"]), ("/admin/raids", ["[data-dlg-open='#dlg-raid-add']"]),
    ("/admin/classes", []), ("/admin/classes", ["[data-dlg-open='#dlg-class-add']"]),
    ("/admin/parties", []), ("/admin/parties?tab=closed", []), ("/admin/parties", ["[data-dlg-open='#dlg-forum']"]),
    ("/admin/users", []), ("/admin/users", ["[data-user-kick]"]), ("/admin/stats", []), ("/admin/stats?tab=activity", []),
    ("/admin/notifications", []), ("/admin/notifications?tab=logs", []), ("/admin/notifications?tab=broadcast", []), ("/admin/notifications?tab=items", []),
    ("/admin/completions?target_discord_id=222&character_name=버서커", []), ("/admin/actions", []),
]
stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
total = 0
try:
    assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids") and wait(f"http://127.0.0.1:{WEB_PORT}/health")
    from itsdangerous import TimestampSigner
    cookie = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps({"user": {"discord_id": "111", "username": "발키리", "is_admin": True, "avatar_url": None, "admin_mode": True}}).encode())).decode()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vpname, vp in (("desktop", {"width": 1280, "height": 900}),):
            ctx = browser.new_context(viewport=vp); ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
            page = ctx.new_page()
            for path, clicks in PAGES:
                page.goto(f"http://127.0.0.1:{WEB_PORT}" + path, wait_until="networkidle"); page.wait_for_timeout(200)
                for sel in clicks:
                    page.locator(sel).first.click(); page.wait_for_timeout(250)
                issues = page.evaluate(JS)
                label = path + (" + " + ",".join(clicks) if clicks else "")
                if issues:
                    print(f"\n=== {vpname} {label}")
                    for it in issues:
                        total += 1
                        flag = f" STRETCHED:{it['stretched']}" if it['stretched'] else ""
                        print(f"  [{it['row']} w={it['roww']}] spread={it['spread']}{flag}")
                        for i in it["items"]: print("     ", i)
            ctx.close()
        browser.close()
finally:
    web.terminate(); stub.terminate()
print(f"\nmismatches: {total}")
