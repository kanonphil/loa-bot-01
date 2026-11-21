"""CSP 위반 점검 — 모든 화면을 열어 securitypolicyviolation 이벤트·콘솔 CSP 에러를 모은다(0건이어야 함). measure.py와 같은 스텁·화면 목록."""
import base64, json, os, subprocess, sys, time, urllib.request, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).parent
ROOT = str(Path(__file__).resolve().parents[2])
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

INIT = "window.__csp = []; document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline') + ' @' + (e.sourceFile || '') + ':' + e.lineNumber));"

stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids") and wait(f"http://127.0.0.1:{WEB_PORT}/health")
    from itsdangerous import TimestampSigner
    cookie = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps({"user": {"discord_id": "111", "username": "발키리", "is_admin": True, "avatar_url": None, "admin_mode": True}}).encode())).decode()
    from playwright.sync_api import sync_playwright
    PAGES = ["/main", "/parties", "/parties?filter=all", "/parties/p1", "/parties/p2", "/parties/p6", "/parties/p7", "/parties/create", "/parties/history", "/expedition", "/raid-check", "/raid-check/select/발키리",
             "/raid-check/history", "/invites", "/ranking", "/calendar", "/characters/발키리", "/settings", "/parties/p1/switch",
             "/admin/raids?tab=raids", "/admin/raids?tab=categories", "/admin/raids?tab=difficulties&raid=종막", "/admin/parties", "/admin/classes", "/admin/users", "/admin/notifications", "/tools/auction-calculator", "/more", "/guide"]
    console = []; bad = 0; checked = 0
    console = []; bad = 0; checked = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vpname, vp in (("desktop", {"width": 1280, "height": 900}), ("mobile", {"width": 390, "height": 844})):
            ctx = browser.new_context(viewport=vp); ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
            ctx.add_init_script(INIT)
            ctx.add_init_script(INIT)
            page = ctx.new_page()
            page.on('console', lambda m: console.append(m.text))
            page.on('console', lambda m: console.append(m.text))
            for path in PAGES:
                if vpname == "mobile" and path.startswith("/admin"): continue
                page.goto(f"http://127.0.0.1:{WEB_PORT}" + path, wait_until="networkidle"); page.wait_for_timeout(200)
                if path.startswith("/admin/raids"):
                    page.evaluate("document.querySelectorAll('details.admin-row-extra').forEach((d,i)=>{ if(i<2) d.open=true; })"); page.wait_for_timeout(150)
                if path == "/parties/p1":
                    page.evaluate("document.querySelectorAll('details.pt-set').forEach(d => d.open = true)")  # 공대 설정은 접혀 있다
                    page.click("text=게스트 초대 열기"); page.wait_for_timeout(600)
                page.wait_for_timeout(300)
                v = page.evaluate("window.__csp || []")
                errs = [m for m in console if "Content Security Policy" in m or "Refused to" in m]
                console.clear()
                if v or errs:
                    bad += 1
                    print(f"=== {vpname} {path}")
                    for x in v: print("   violation", x)
                    for x in errs: print("   console", x[:200])
                checked += 1
            ctx.close()
        browser.close()
    print(f'checked {checked} pages, {bad} with CSP problems')
finally:
    web.terminate(); stub.terminate()
