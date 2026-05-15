from fastapi import FastAPI
# CORSMiddleware: Electron(로컬)에서 서버로 요청할 때 브라우저 차단 방지
from fastapi.middleware.cors import CORSMiddleware

from bot.api.routes import raids, parties, users, stats

app = FastAPI(title="로아봇 관리자 API", version="1.0.0")

# ── CORS 설정 (Electron에서 호출 허용) ──────────────────
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_methods=["*"],
  allow_headers=["*"],
)

# ── 라우터 등록 ──────────────────────────────────────────
# include_router: 각 기능별 라우터를 앱에 연결
# prefix="/api/raids": 모든 레이드 API 주소가 /api/raids/...로 시작
app.include_router(raids.router,   prefix="/api/raids",   tags=["raids"])
app.include_router(parties.router, prefix="/api/parties", tags=["parties"])
app.include_router(users.router,   prefix="/api/users",   tags=["users"])
app.include_router(stats.router,   prefix="/api/stats",   tags=["stats"])

# /api/health: 서버가 살아있는지 확인용 엔드포인트 
@app.get("/api/health")
async def health():
    return {"status": "ok"}