"""버튼/입력/셀렉트 규격 실측 — 같은 줄(flex row)에 놓인 컨트롤의 높이가 다르거나, 버튼이 늘어난(부모 폭 대부분 차지) 곳을 찾는다."""
import base64, json, os, subprocess, sys, time, urllib.request, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).parent
ROOT = r"C:\Users\xoghk\Desktop\loa-bot-01"
SECRET = "shot-secret"
ENV = {**os.environ, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": "http://127.0.0.1:8766/callback",
       "BOT_API_BASE_URL": "http://127.0.0.1:8765", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "111", "NOTIFICATION_DB_PATH": str(HERE / "notif.db"), "PYTHONIOENCODING": "utf-8"}

def wait(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1); return True
        except Exception:
            time.sleep(0.5)
    return False

JS = r"""
() => {
  const ctrlSel = 'button, a.ui-btn, a.party-create-link, a.party-switch-btn, a.calendar-today-btn, a.dash-card-link, input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select:not(.themed-select-native), textarea, .themed-select-trigger';
  const ctrls = Array.from(document.querySelectorAll(ctrlSel)).filter(el => el.offsetParent !== null && el.getBoundingClientRect().height > 0);
  // 같은 줄 판정: 가장 가까운 flex/grid 부모
  function rowOf(el) {
    let p = el.parentElement;
    while (p && p !== document.body) {
      const d = getComputedStyle(p).display;
      if (d === 'flex' || d === 'inline-flex' || d === 'grid') return p;
      p = p.parentElement;
    }
    return el.parentElement;
  }
  const rows = new Map();
  for (const el of ctrls) {
    const r = rowOf(el);
    if (!rows.has(r)) rows.set(r, []);
    rows.get(r).push(el);
  }
  const out = [];
  for (const [row, els] of rows) {
    const rr = row.getBoundingClientRect();
    const items = els.map(el => {
      const b = el.getBoundingClientRect();
      return { tag: el.tagName.toLowerCase(), cls: (el.className && el.className.baseVal === undefined ? el.className : '').toString().slice(0, 60), text: (el.innerText || el.value || el.placeholder || '').trim().slice(0, 18), h: Math.round(b.height), w: Math.round(b.width), top: Math.round(b.top) };
    });
    // 같은 시각적 줄(top이 비슷)끼리만 비교
    const lines = {};
    for (const it of items) { const k = Math.round(it.top / 12); (lines[k] = lines[k] || []).push(it); }
    for (const k in lines) {
      const line = lines[k];
      const hs = line.map(i => i.h);
      const spread = Math.max(...hs) - Math.min(...hs);
      const stretched = line.filter(i => (i.tag === 'button' || i.cls.includes('btn') || i.cls.includes('link')) && i.w > 0.7 * rr.width && rr.width > 300 && !i.cls.includes('is-block') && !i.cls.includes('armory-sync') && !i.cls.includes('raid-select-save'));
      if ((line.length > 1 && spread > 2) || stretched.length) {
        out.push({ row: (row.className || row.tagName).toString().slice(0, 50), roww: Math.round(rr.width), spread, stretched: stretched.map(s => s.text), items: line.map(i => `${i.tag}.${i.cls.split(' ')[0]}[${i.text}] ${i.w}x${i.h}`) });
      }
    }
  }
  return out;
}
"""

stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", "8766", "--log-level", "warning"], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    assert wait("http://127.0.0.1:8765/api/internal/raids") and wait("http://127.0.0.1:8766/health")
    from itsdangerous import TimestampSigner
    cookie = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps({"user": {"discord_id": "111", "username": "발키리", "is_admin": True, "avatar_url": None, "admin_mode": True}}).encode())).decode()
    from playwright.sync_api import sync_playwright
    PAGES = ["/main", "/parties", "/parties/p1", "/parties/p2", "/parties/create", "/parties/history", "/expedition", "/raid-check", "/raid-check/select/발키리",
             "/raid-check/history", "/invites", "/ranking", "/calendar", "/characters/발키리", "/settings", "/parties/p1/switch",
             "/admin/raids?tab=raids", "/admin/raids?tab=categories", "/admin/raids?tab=difficulties&raid=종막", "/admin/parties", "/admin/classes", "/admin/users", "/admin/notifications", "/tools/auction-calculator"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vpname, vp in (("desktop", {"width": 1280, "height": 900}), ("mobile", {"width": 390, "height": 844})):
            ctx = browser.new_context(viewport=vp); ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
            page = ctx.new_page()
            for path in PAGES:
                if vpname == "mobile" and path.startswith("/admin"): continue
                page.goto("http://127.0.0.1:8766" + path, wait_until="networkidle"); page.wait_for_timeout(200)
                if path.startswith("/admin/raids"):
                    page.evaluate("document.querySelectorAll('details.admin-row-extra').forEach((d,i)=>{ if(i<2) d.open=true; })"); page.wait_for_timeout(150)
                if path == "/parties/p1":
                    page.click("text=게스트 초대 열기"); page.wait_for_timeout(600)
                issues = page.evaluate(JS)
                if issues:
                    print(f"\n=== {vpname} {path}")
                    for it in issues:
                        flag = f" STRETCHED:{it['stretched']}" if it['stretched'] else ""
                        print(f"  [{it['row']} w={it['roww']}] spread={it['spread']}{flag}")
                        for i in it["items"]: print("     ", i)
            ctx.close()
        browser.close()
finally:
    web.terminate(); stub.terminate()
