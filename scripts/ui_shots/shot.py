"""webapp + 스텁 봇을 띄우고 Playwright로 페이지 스크린샷. 사용: python shot.py <tag>"""
import base64, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
TAG = sys.argv[1] if len(sys.argv) > 1 else "before"
OUT = HERE / "out" / TAG
OUT.mkdir(parents=True, exist_ok=True)
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8765")  # 다른 워크트리와 동시에 돌릴 때 포트 분리
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8766")
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"http://127.0.0.1:{WEB_PORT}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "out" / "notif.db"), "PYTHONIOENCODING": "utf-8"}

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
    assert wait(f"http://127.0.0.1:{WEB_PORT}/health"), "web down"
    from itsdangerous import TimestampSigner
    session = {"user": {"discord_id": "111", "username": "발키리", "is_admin": True, "avatar_url": None, "admin_mode": True}}
    data = base64.b64encode(json.dumps(session).encode())
    cookie = TimestampSigner(SECRET).sign(data).decode()

    from playwright.sync_api import sync_playwright
    PAGES = [
        ("main", "/main"), ("parties", "/parties"), ("party-detail", "/parties/p1"), ("party-detail-other", "/parties/p2"),
        ("party-create", "/parties/create"), ("history", "/parties/history"), ("expedition", "/expedition"),
        ("raid-check", "/raid-check"), ("raid-select", "/raid-check/select/발키리"), ("raid-history", "/raid-check/history"),
        ("invites", "/invites"), ("ranking", "/ranking"), ("calendar", "/calendar"), ("character", "/characters/발키리"),
        ("settings", "/settings"), ("switch", "/parties/p1/switch"),
        ("admin-raids", "/admin/raids?tab=raids"), ("admin-diffs", "/admin/raids?tab=difficulties&raid=종막"),
        ("admin-parties", "/admin/parties"), ("admin-classes", "/admin/classes"),
        ("more", "/more"), ("admin-users", "/admin/users"), ("guide", "/guide"), ("auction", "/tools/auction-calculator"),
    ]
    MOBILE = {"more", "history", "main", "parties", "party-detail", "expedition", "raid-check", "invites", "ranking", "calendar", "settings", "raid-select"}
    # SHOT_PAGES=main,parties — 이 화면만 찍는다. SHOT_WIDE=1 — 1920 모니터·배율 125%(CSS 1536px, 배율 1.25)도 찍는다.
    only = {p for p in os.environ.get("SHOT_PAGES", "").split(",") if p}
    if only:
        PAGES = [p for p in PAGES if p[0] in only]
    VIEWPORTS = [("desktop", {"width": 1280, "height": 900}, 1), ("mobile", {"width": 390, "height": 844}, 1)]
    if os.environ.get("SHOT_WIDE"):
        VIEWPORTS.insert(1, ("wide", {"width": 1536, "height": 814}, 1.25))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, vp, dpr in VIEWPORTS:
            ctx = browser.new_context(viewport=vp, device_scale_factor=dpr)
            ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
            page = ctx.new_page()
            for tag, path in PAGES:
                if name == "mobile" and tag not in MOBILE:
                    continue
                page.goto(f"http://127.0.0.1:{WEB_PORT}" + path, wait_until="networkidle")
                page.wait_for_timeout(300)
                # 관리자 수정 폼·상세 펼침
                if tag.startswith("admin-raids") or tag == "admin-diffs":
                    page.evaluate("document.querySelectorAll('details.admin-row-extra').forEach((d,i)=>{ if(i<2) d.open=true; })")
                    page.wait_for_timeout(300)
                page.screenshot(path=str(OUT / f"{tag}-{name}.jpg"), full_page=True, type="jpeg", quality=68)
                print("shot", tag, name)
            ctx.close()
        browser.close()
finally:
    web.terminate(); stub.terminate()
    try:
        web.wait(5); stub.wait(5)
    except Exception:
        web.kill(); stub.kill()
print("done", OUT)
