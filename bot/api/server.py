from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.api.routes import raids, parties, users, stats, status, completions, subscriptions, internal

app = FastAPI(title="로아봇 관리자 API", version="1.0.0")

app.add_middleware(
  CORSMiddleware,
  allow_origins=[
    "http://localhost:5173",   # Vite 개발 서버
    "http://localhost:4173",   # Vite 프리뷰
    "http://localhost:3000",   # 기타 로컬 개발
    "null",                    # 패키징된 Electron (file:// origin)
  ],
  allow_methods=["*"],
  allow_headers=["*"],
)

app.include_router(raids.router,         prefix="/api/raids",         tags=["raids"])
app.include_router(parties.router,       prefix="/api/parties",       tags=["parties"])
app.include_router(users.router,         prefix="/api/users",         tags=["users"])
app.include_router(stats.router,         prefix="/api/stats",         tags=["stats"])
app.include_router(status.router,        prefix="/api/status",        tags=["status"])
app.include_router(completions.router,   prefix="/api/completions",   tags=["completions"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
app.include_router(internal.router,      prefix="/api/internal",      tags=["internal"])


@app.get("/api/health")
async def health():
  return {"status": "ok"}
