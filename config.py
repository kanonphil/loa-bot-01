import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
ADMIN_API_KEY: str = os.environ.get("ADMIN_API_KEY", "changeme")
# 웹앱(별도 서버)이 봇 서버의 내부 API를 호출할 때 쓰는 전용 키.
# ADMIN_API_KEY와 분리해 웹앱이 관리자 권한을 갖지 않도록 함.
WEBAPP_API_KEY: str = os.environ.get("WEBAPP_API_KEY", "changeme-webapp")

# /api등록 시 검증용 캐릭터가 이 길드 소속이어야만 등록을 허용.
# 빈 문자열이면 길드 확인을 건너뜀 (다른 서버에서 재사용할 때 대비).
REQUIRED_GUILD_NAME: str = os.environ.get("REQUIRED_GUILD_NAME", "동물롱장")

# 게스트(API 키 미등록자) 초대 시 캐릭터 정보(직업/전투력/아이템레벨) 조회에 쓸 API 키의 소유자.
# 로스트아크 오픈API 캐릭터 조회는 조회 대상 소유 키가 아니어도 되는 공개 조회라, 이 discord_id가
# /api등록으로 등록해둔 키를 그대로 재사용한다. 비어있으면 게스트 초대 시 조회를 건너뛴다.
GUEST_LOOKUP_DISCORD_ID: str = os.environ.get("GUEST_LOOKUP_DISCORD_ID", "")

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
