"""관리 화면 전 탭 스크린샷(데스크톱 1280 + 모바일 390). 사용: python shot_admin.py <tag>
포트는 SHOT_BOT_PORT / SHOT_WEB_PORT로 나눈다. STUB_ADMIN_MISSING=1이면 새 봇 엔드포인트가 404인 상태로 찍는다."""
import base64, io, json, os, subprocess, sys, time, urllib.request
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
TAG = sys.argv[1] if len(sys.argv) > 1 else "admin"
OUT = HERE / "out" / TAG
OUT.mkdir(parents=True, exist_ok=True)
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8765")
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8766")
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"http://127.0.0.1:{WEB_PORT}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "out" / f"notif-{TAG}.db"), "PYTHONIOENCODING": "utf-8"}


def wait(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1); return True
        except Exception:
            time.sleep(0.5)
    return False


PAGES = [
    ("raids", "/admin/raids"), ("raids-extreme", "/admin/raids?raid=카멘 익스트림"), ("classes", "/admin/classes"),
    ("parties", "/admin/parties"), ("parties-closed", "/admin/parties?tab=closed"), ("users", "/admin/users"),
    ("stats", "/admin/stats"), ("stats-activity", "/admin/stats?tab=activity"),
    ("notif-subs", "/admin/notifications"), ("notif-logs", "/admin/notifications?tab=logs"),
    ("notif-broadcast", "/admin/notifications?tab=broadcast"), ("notif-items", "/admin/notifications?tab=items"),
    ("completions", "/admin/completions?target_discord_id=222&character_name=버서커&week_key=2026-09-23"), ("actions", "/admin/actions"),
]
MOBILE = {"raids", "users", "parties", "actions", "notif-broadcast"}

stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"],
                       cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids"), "stub down"
    assert wait(f"http://127.0.0.1:{WEB_PORT}/health"), "web down"
    from itsdangerous import TimestampSigner
    session = {"user": {"discord_id": "111", "username": "발키리", "is_admin": True, "avatar_url": None, "admin_mode": True}}
    cookie = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps(session).encode())).decode()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, vp in (("desktop", {"width": 1280, "height": 900}), ("mobile", {"width": 390, "height": 844})):
            ctx = browser.new_context(viewport=vp, device_scale_factor=1)
            ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            for tag, path in PAGES:
                if name == "mobile" and tag not in MOBILE:
                    continue
                resp = page.goto(f"http://127.0.0.1:{WEB_PORT}" + path, wait_until="networkidle")
                page.wait_for_timeout(250)
                page.screenshot(path=str(OUT / f"{tag}-{name}.png"), full_page=True)
                print("shot", tag, name, resp.status)
            print("console errors:", errors or "none", name)
            ctx.close()
        browser.close()
finally:
    web.terminate(); stub.terminate()
    try:
        web.wait(5); stub.wait(5)
    except Exception:
        web.kill(); stub.kill()
print("done", OUT)
