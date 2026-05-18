from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.api.routes import raids, parties, users, stats, status, completions, subscriptions

app = FastAPI(title="로아봇 관리자 API", version="1.0.0")

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
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


@app.get("/api/health")
async def health():
  return {"status": "ok"}
