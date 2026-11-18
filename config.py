import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
# 관리자 API(X-API-Key) / 웹앱 내부 API(X-Webapp-Key) 키. 예전엔 .env에 없으면
# "changeme"/"changeme-webapp"으로 조용히 대체돼, 설정을 빠뜨린 서버가 누구나 아는 키로
# 열려 있게 됐다. 이제 비어 있으면 그 API는 모든 요청을 거부하고(bot/api/auth.py),
# 봇 기동 자체도 validate_required_settings()에서 멈춘다(main.py).
ADMIN_API_KEY: str = os.environ.get("ADMIN_API_KEY", "").strip()
# 웹앱(별도 서버)이 봇 서버의 내부 API를 호출할 때 쓰는 전용 키.
# ADMIN_API_KEY와 분리해 웹앱이 관리자 권한을 갖지 않도록 함.
WEBAPP_API_KEY: str = os.environ.get("WEBAPP_API_KEY", "").strip()

# /api등록 시 검증용 캐릭터가 이 길드 소속이어야만 등록을 허용.
# 빈 문자열이면 길드 확인을 건너뜀 (다른 서버에서 재사용할 때 대비).
REQUIRED_GUILD_NAME: str = os.environ.get("REQUIRED_GUILD_NAME", "동물롱장")

# 웹 관리자 탭(카테고리/레이드/난이도/직업 관리) 접근을 허용할 디스코드 ID 목록(콤마 구분).
# 웹앱은 ADMIN_API_KEY를 갖지 않으므로, 이 목록에 대한 재검증을 여기(봇 서버)에서 직접 한다 —
# 웹앱 서버가 뚫려도 이 목록에 없는 계정으로는 관리자 액션이 실행되지 않는다.
ADMIN_DISCORD_IDS: set[str] = {
    x.strip() for x in os.environ.get("ADMIN_DISCORD_IDS", "").split(",") if x.strip()
}

# 게스트(API 키 미등록자) 초대 시 캐릭터 정보(직업/전투력/아이템레벨) 조회에 쓸 API 키의 소유자.
# 로스트아크 오픈API 캐릭터 조회는 조회 대상 소유 키가 아니어도 되는 공개 조회라, 이 discord_id가
# /api등록으로 등록해둔 키를 그대로 재사용한다. 비어있으면 게스트 초대 시 조회를 건너뛴다.
GUEST_LOOKUP_DISCORD_ID: str = os.environ.get("GUEST_LOOKUP_DISCORD_ID", "")


def validate_required_settings() -> None:
    """봇 기동 전 필수 설정 확인 — 빠졌으면 바로 멈춘다(조용히 기본값으로 뜨지 않게)."""
    missing = [name for name, value in (("ADMIN_API_KEY", ADMIN_API_KEY), ("WEBAPP_API_KEY", WEBAPP_API_KEY)) if not value]
    if missing:
        raise RuntimeError(f".env에 {', '.join(missing)} 값이 없습니다. 설정한 뒤 다시 실행해주세요.")


# ── API 키 암호화 ─────────────────────────────────────────
# .env에 ENCRYPTION_KEY가 없으면 평문 저장 (미설정 환경 호환)
# 키 생성: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
_ENCRYPTION_KEY: str | None = os.environ.get("ENCRYPTION_KEY") or None

# Fernet 토큰은 버전 바이트 0x80으로 시작해 base64로 항상 "gAAAAA"로 시작한다. 로스트아크
# API 키(JWT, "eyJ...")와 겹치지 않으므로 "암호문인지"를 이 접두어로 판단한다 — 예전엔
# "지금 키로 복호화되면 암호문"으로 판단해서, ENCRYPTION_KEY를 바꾼 뒤 기동하면 옛 키로
# 암호화된 값을 평문으로 착각하고 한 번 더 암호화해 저장값이 영구히 망가졌다.
_FERNET_PREFIX = "gAAAAA"

_fernet = None
if _ENCRYPTION_KEY:
    from cryptography.fernet import Fernet

    try:
        _fernet = Fernet(_ENCRYPTION_KEY.encode())
    except Exception as e:
        # 잘못된 키를 조용히 무시하면 이후 모든 키가 평문으로 저장된다 — 기동을 멈춘다
        raise RuntimeError(f"ENCRYPTION_KEY가 올바른 Fernet 키가 아닙니다: {e}") from e


def encryption_enabled() -> bool:
    return _fernet is not None


def is_encrypted_value(stored: str) -> bool:
    return bool(stored) and stored.startswith(_FERNET_PREFIX)


def encrypt_api_key(plain: str) -> str:
    """API 키를 암호화. ENCRYPTION_KEY 미설정 시 평문 반환."""
    if _fernet is None:
        return plain
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_api_key(stored: str) -> str:
    """저장된 API 키를 복호화. 평문(구 데이터)이면 그대로 반환."""
    if not is_encrypted_value(stored):
        return stored  # 평문(ENCRYPTION_KEY 설정 전 데이터)
    if _fernet is None:
        print("[config] 암호화된 API 키가 있는데 ENCRYPTION_KEY가 설정되지 않았습니다.")
        return stored
    try:
        return _fernet.decrypt(stored.encode()).decode()
    except Exception:
        print("[config] API 키 복호화 실패 — ENCRYPTION_KEY가 바뀌었을 수 있습니다(저장값은 그대로 둡니다).")
        return stored


def is_plaintext_key(stored: str) -> bool:
    """저장된 값이 암호화되지 않은 평문인지 — 암호화 마이그레이션 대상 판단용.
    접두어로만 판단하므로 다른 키로 암호화된 값을 평문으로 오인해 재암호화하지 않는다."""
    return not is_encrypted_value(stored)
