"""이용 가이드(/guide) 화면 사진 만들기 — 스텁 데이터로 단계별 화면을 PC·휴대폰 × 다크·라이트로 찍고,
빨간 번호 박스를 놓을 요소 위치를 사진 기준 %로 계산해 webapp/static/guide/boxes.json에 저장한다.

박스는 손으로 그리지 않는다 — 화면이 바뀌면 이 스크립트만 다시 돌리면 사진과 박스가 같이 맞춰진다.
사용: python scripts/ui_shots/guide_shots.py  (SHOT_BOT_PORT/SHOT_WEB_PORT로 포트 변경)"""
import base64, io, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "webapp" / "static" / "guide"
SECRET = "shot-secret"
BOT_PORT = os.environ.get("SHOT_BOT_PORT", "8791")
WEB_PORT = os.environ.get("SHOT_WEB_PORT", "8792")
ENV = {**os.environ, "SHOT_BOT_PORT": BOT_PORT, "DISCORD_CLIENT_ID": "x", "DISCORD_CLIENT_SECRET": "x", "DISCORD_REDIRECT_URI": f"http://127.0.0.1:{WEB_PORT}/callback",
       "BOT_API_BASE_URL": f"http://127.0.0.1:{BOT_PORT}", "BOT_API_WEBAPP_KEY": "k", "DISCORD_GUILD_ID": "1", "SESSION_SECRET": SECRET,
       "SESSION_HTTPS_ONLY": "false", "ADMIN_DISCORD_IDS": "999", "NOTIFICATION_DB_PATH": str(HERE / "out" / "notif-guide.db"), "PYTHONIOENCODING": "utf-8"}

# 박스: q = [(CSS 선택자, 포함할 글자)] — 맞는 요소들(각 첫 번째, last=True면 마지막)의 합집합 사각형.
# pc.clip = [x, y, w, h](1280 폭 기준 페이지 좌표), m.clip = [y0, y1](390 폭 전체) 또는 "viewport"(고정 탭바까지 화면 그대로).
STEPS = {
    "layout": {"path": "/main",
               "pc": {"clip": [0, 0, 1280, 600], "boxes": [
                   [1, [(".side-link", "홈"), (".side-link", "이용 가이드")]],
                   [2, [(".theme-btn", "")]], [3, [(".bell", "")]], [4, [("section, .ui-card", "할 일")], "smallest"]]},
               "m": {"clip": "viewport", "boxes": [
                   [1, [(".tabbar a", "홈"), (".tabbar a", "더보기")]],
                   [2, [(".theme-btn", "")]], [3, [(".bell", "")]], [4, [("section, .ui-card", "할 일")], "smallest"]]}},
    "expedition": {"path": "/expedition",
                   "pc": {"clip": [205, 190, 935, 720]}, "m": {"clip": [235, 1417]},
                   "boxes": [[1, [("input.field.exp-grow", ""), ("button.btn.pri", "캐릭터 추가")]],
                             [2, [("button.btn", "전체 동기화")]],
                             [3, [("h3.exp-sub", "부계정 추가"), ("button.btn.pri", "계정 추가")]]]},
    "homework": {"path": "/main",
                 "pc": {"clip": [90, 605, 1170, 420]}, "m": {"clip": [752, 1268]},
                 "boxes": [[1, [("button.hw-hit", "워로드부캐 · 아르모체(4막)")]],
                           [2, [("button.btn", "레이드 고르기")]], [3, [("a.btn", "지난 주")]]]},
    "create": {"path": "/parties/create",
               "pc": {"clip": [90, 205, 1170, 950]}, "m": {"clip": [185, 1605]},
               "boxes": [[1, [("button.chip-btn", "4막 하드 ·"), ("button.chip-btn", "세르카 하드 ·")]],
                         [2, [("button.chip-btn", "내일("), ("button.chip-btn", "직접 고르기")]],
                         [3, [("label.pt-copt", "발키리"), ("label.pt-copt", "나중에")]],
                         [4, [("h2.pt-h", "미리보기"), ("button.btn.pri", "공대 열기")]]]},
    "join": {"path": "/parties?filter=all",
             "pc": {"clip": [75, 112, 1195, 528]}, "m": {"clip": [170, 1135]},
             "boxes": [[1, [("a.chip-btn", "참여 가능")]],
                       [2, [("button.themed-select-trigger", "발키리"), ("button.btn.pri", "참여")]],
                       [3, [("a.pt-reason-lnk", "빈자리 알림")]]]},
    "settings": {"path": "/settings",
                 "pc": {"clip": [205, 200, 935, 1020]}, "m": {"clip": [180, 1632]},
                 "boxes": [[1, [("button.switch", "")]],
                           [2, [("label.settings-check", "공대 모집"), ("label.settings-check", "내게 온")]],
                           [3, [("button.themed-select-trigger", "1시간 전")]],
                           [4, [("h2.exp-h", "레이드 구독"), ("button.btn.pri", "구독")], "last"]]},
    "auction": {"path": "/tools/auction-calculator",
                "pc": {"clip": [205, 210, 935, 330]}, "m": {"clip": [210, 800]},
                "boxes": [[1, [("label.field-label", "템 가격")]], [2, [("button.themed-select-trigger", "아이템 선택")]],
                          [3, [("label.exp-seg", "8인"), ("input.exp-custom-size", "")]], [4, [("h2.exp-h", "결과"), ("h3.exp-sub", "판매")]]]},
}

RECT_JS = r"""([q, mode]) => {
  const rects = [];
  for (const [sel, text] of q) {
    let els = [...document.querySelectorAll(sel)].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.height && (!text || (e.innerText || e.getAttribute('aria-label') || '').includes(text)); });
    if (!els.length) return 'MISSING ' + sel + ' ' + text;
    if (mode === 'smallest') els.sort((a, b) => { const x = a.getBoundingClientRect(), y = b.getBoundingClientRect(); return x.width * x.height - y.width * y.height; });
    const e = mode === 'last' ? els[els.length - 1] : els[0];
    const r = e.getBoundingClientRect();
    rects.push([r.left + scrollX, r.top + scrollY, r.right + scrollX, r.bottom + scrollY]);
  }
  return [Math.min(...rects.map(r => r[0])), Math.min(...rects.map(r => r[1])), Math.max(...rects.map(r => r[2])), Math.max(...rects.map(r => r[3]))];
}"""
CLEAN_JS = "document.documentElement.style.scrollBehavior = 'auto'; document.querySelectorAll('.toast, .toasts').forEach(e => e.remove());"
HIDE_TABBAR_JS = "document.querySelectorAll('.tabbar').forEach(e => e.style.display = 'none');"


def wait(url):
    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=1); return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    from itsdangerous import TimestampSigner
    from PIL import Image
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    stub = subprocess.Popen([sys.executable, str(HERE / "stub_bot.py")], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", WEB_PORT, "--log-level", "warning"],
                           cwd=str(ROOT), env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    meta, missing = {}, []
    try:
        assert wait(f"http://127.0.0.1:{BOT_PORT}/api/internal/raids") and wait(f"http://127.0.0.1:{WEB_PORT}/health")
        user = {"discord_id": "111", "username": "발키리", "is_admin": False, "avatar_url": None, "admin_mode": False}
        cookie = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps({"user": user}).encode())).decode()
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for device, vp, scale in (("pc", {"width": 1280, "height": 800}, 1.5), ("m", {"width": 390, "height": 844}, 2)):
                for theme in ("dark", "light"):
                    ctx = browser.new_context(viewport=vp, device_scale_factor=scale)
                    ctx.add_cookies([{"name": "session", "value": cookie, "domain": "127.0.0.1", "path": "/"}])
                    ctx.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}'); }} catch (e) {{}}")
                    page = ctx.new_page()
                    for key, st in STEPS.items():
                        spec = st[device]
                        page.goto(f"http://127.0.0.1:{WEB_PORT}{st['path']}", wait_until="networkidle")
                        page.wait_for_timeout(400)
                        page.evaluate(CLEAN_JS)
                        if spec["clip"] == "viewport":
                            cx, cy, cw, ch = 0, 0, vp["width"], vp["height"]
                            png = page.screenshot()
                        else:
                            if device == "m":
                                page.evaluate(HIDE_TABBAR_JS)
                                y0, y1 = spec["clip"]
                                cx, cy, cw, ch = 0, y0, vp["width"], y1 - y0
                            else:
                                cx, cy, cw, ch = spec["clip"]
                            png = page.screenshot(clip={"x": cx, "y": cy, "width": cw, "height": ch}, full_page=True)
                        Image.open(io.BytesIO(png)).convert("RGB").save(OUT / f"{key}-{device}-{theme}.webp", "WEBP", quality=78, method=6)
                        if theme != "dark":
                            continue
                        boxes = []
                        for n, q, *mode in spec.get("boxes") or st["boxes"]:
                            r = page.evaluate(RECT_JS, [[list(x) for x in q], mode[0] if mode else "first"])
                            if isinstance(r, str):
                                missing.append(f"{device} {key} #{n}: {r}"); continue
                            pad = 5 if device == "pc" else 4
                            x0, y0 = max(r[0] - pad - cx, 2), max(r[1] - pad - cy, 2)
                            x1, y1 = min(r[2] + pad - cx, cw - 2), min(r[3] + pad - cy, ch - 2)
                            boxes.append({"n": n, "l": round(x0 / cw * 100, 2), "t": round(y0 / ch * 100, 2),
                                          "w": round((x1 - x0) / cw * 100, 2), "h": round((y1 - y0) / ch * 100, 2)})
                        meta.setdefault(key, {})[device] = {"w": cw, "h": ch, "boxes": boxes}
                    ctx.close()
            browser.close()
    finally:
        web.terminate(); stub.terminate()
    (OUT / "boxes.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    total = sum(f.stat().st_size for f in OUT.glob("*.webp"))
    print(f"사진 {len(list(OUT.glob('*.webp')))}장, {total // 1024}KB → {OUT}")
    for m in missing:
        print("박스 못 찾음:", m)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
