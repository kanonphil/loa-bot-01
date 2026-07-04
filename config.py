import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
ADMIN_API_KEY: str = os.environ.get("ADMIN_API_KEY", "changeme")
# 웹앱(별도 서버)이 봇 서버의 내부 API를 호출할 때 쓰는 전용 키.
# ADMIN_API_KEY와 분리해 웹앱이 관리자 권한을 갖지 않도록 함.
WEBAPP_API_KEY: str = os.environ.get("WEBAPP_API_KEY", "changeme-webapp")

# ── API 키 암호화 ─────────────────────────────────────────
# .env에 ENCRYPTION_KEY가 없으면 평문 저장 (미설정 환경 호환)
# 키 생성: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
_ENCRYPTION_KEY: str | None = os.environ.get("ENCRYPTION_KEY")

try:
    from cryptography.fernet import Fernet, InvalidToken
    _fernet = Fernet(_ENCRYPTION_KEY.encode()) if _ENCRYPTION_KEY else None
except Exception:
    _fernet = None


def encrypt_api_key(plain: str) -> str:
    """API 키를 암호화. ENCRYPTION_KEY 미설정 시 평문 반환."""
    if _fernet is None:
        return plain
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_api_key(stored: str) -> str:
    """저장된 API 키를 복호화. 평문(구 데이터)이면 그대로 반환."""
    if _fernet is None:
        return stored
    try:
        return _fernet.decrypt(stored.encode()).decode()
    except Exception:
        return stored  # 기존 평문 키 호환


def is_plaintext_key(stored: str) -> bool:
    """저장된 값이 암호화되지 않은 평문인지 확인."""
    if _fernet is None:
        return True
    try:
        _fernet.decrypt(stored.encode())
        return False  # 복호화 성공 → 암호화된 값
    except Exception:
        return True   # 복호화 실패 → 평문
