"""공대 화면(목록·열기·상세·달력·이력) 스크린샷 — 사용자 종류별(관리자 모드 / 일반 파티장 / 일반 참가자 / 외부인)로 찍는다.
사용: SHOT_BOT_PORT=8783 SHOT_WEB_PORT=8784 python scripts/ui_shots/shot_party.py party  → out/party/*.jpg"""
import base64, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
TAG = sys.argv[1] if len(sys.argv) > 1 else "party"
OUT = HERE / "out" / TAG
OUT.mkdir(parents=True, exist_ok=True)
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8765")
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8766")
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"http://127.0.0.1:{WEB_PORT}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "out" / "notif-party.db"), "PYTHONIOENCODING": "utf-8"}


def wait(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1); return True
        except Exception:
            time.sleep(0.5)
    return False


def cookie(discord_id, name, admin):
    from itsdangerous import TimestampSigner
    user = {"discord_id": discord_id, "username": name, "is_admin": admin, "avatar_url": None, "admin_mode": admin}
    return TimestampSigner(SECRET).sign(base64.b64encode(json.dumps({"user": user}).encode())).decode()


# (파일 이름, 경로, 사용자) — 사용자: admin(111, 관리자 모드) · leader(111, 일반) · member(111이 p6 참가자) · outsider(111이 p2 외부인)
SHOTS = [
    ("list", "/parties", "leader"), ("list-all", "/parties?filter=all", "leader"), ("list-mine", "/parties?filter=mine", "leader"),
    ("create", "/parties/create", "leader"), ("create-filled", "/parties/create?raid=아르모체(4막)&difficulty=하드&scheduled_datetime=2026-11-25T21:00", "leader"),
    ("detail-leader", "/parties/p1", "leader"), ("detail-admin", "/parties/p1", "admin"), ("detail-member", "/parties/p6", "leader"),
    ("detail-outsider", "/parties/p2", "leader"), ("detail-closed", "/parties/p5", "leader"), ("detail-full", "/parties/p4", "leader"),
    ("detail-expired", "/parties/p7", "leader"), ("detail-cleared", "/parties/p8", "leader"), ("detail-cleared-admin", "/parties/p8", "admin"),
    ("detail-disbanded", "/parties/p9", "leader"), ("history", "/parties/history", "leader"), ("calendar", "/calendar?view=week", "leader"),
]
stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"],
                       cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids") and wait(f"http://127.0.0.1:{WEB_PORT}/health")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vpname, vp in (("desktop", {"width": 1280, "height": 900}), ("mobile", {"width": 390, "height": 844})):
            for who in ("leader", "admin"):
                ctx = browser.new_context(viewport=vp)
                ctx.add_cookies([{"name": "session", "value": cookie("111", "발키리", who == "admin"), "domain": "127.0.0.1", "path": "/"}])
                page = ctx.new_page()
                errors = []
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                for name, path, user in SHOTS:
                    if user != who:
                        continue
                    page.goto(f"http://127.0.0.1:{WEB_PORT}" + path, wait_until="networkidle")
                    page.wait_for_timeout(400)
                    if name.startswith("detail-") and page.locator("details.pt-set").count():
                        page.evaluate("document.querySelectorAll('details.pt-set').forEach(d => d.open = true)")
                    page.screenshot(path=str(OUT / f"{name}-{vpname}.jpg"), full_page=True, type="jpeg", quality=70)
                    print("shot", name, vpname)
                if errors:
                    print("CONSOLE ERRORS", vpname, who, errors)
                ctx.close()
        browser.close()
finally:
    web.terminate(); stub.terminate()
print("done", OUT)
