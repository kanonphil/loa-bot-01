import os
from dotenv import load_dotenv

load_dotenv()

# ── Discord OAuth2 ────────────────────────────────────────
# 기존 봇과 같은 Discord 애플리케이션의 OAuth2 탭에서 발급
DISCORD_CLIENT_ID: str = os.environ["DISCORD_CLIENT_ID"]
DISCORD_CLIENT_SECRET: str = os.environ["DISCORD_CLIENT_SECRET"]
DISCORD_REDIRECT_URI: str = os.environ.get(
    "DISCORD_REDIRECT_URI", "http://localhost:8001/callback"
)

# ── 봇 서버(다른 머신) 내부 API ─────────────────────────────
BOT_API_BASE_URL: str = os.environ.get("BOT_API_BASE_URL", "http://localhost:8000")
BOT_API_WEBAPP_KEY: str = os.environ["BOT_API_WEBAPP_KEY"]

# ── 세션 ──────────────────────────────────────────────────
SESSION_SECRET: str = os.environ.get("SESSION_SECRET", "dev-secret-change-me")
# 로컬 개발(http)에서는 false, Cloudflare 뒤 실서비스(https)에서는 반드시 true
SESSION_HTTPS_ONLY: bool = os.environ.get("SESSION_HTTPS_ONLY", "false").lower() == "true"

# ── AI 채팅 기록 (webapp 자체 소유, 봇 서버 DB와 분리) ────────
CHAT_DB_PATH: str = os.environ.get("CHAT_DB_PATH", "webapp_chat_history.db")
# 이 기간(일)이 지난 대화는 자동 삭제. 기본 30일 — 필요하면 언제든 값만 바꾸면 됨.
CHAT_RETENTION_DAYS: int = int(os.environ.get("CHAT_RETENTION_DAYS", "30"))

# ── Gemini API (AI 상담) ──────────────────────────────────
# 일부러 필수(os.environ[...])로 안 두고 선택값으로 둠 — 이 키 하나 때문에
# 로그인/레이드체크 같은 나머지 기능까지 앱 전체가 안 뜨는 걸 막기 위함.
# 없으면 AI 상담 라우트만 안내 메시지를 반환하고 나머지는 정상 동작.
GEMINI_API_KEY: str | None = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
