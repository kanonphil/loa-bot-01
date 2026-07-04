from fastapi import Security, HTTPException, status
# APIKeyHeader: HTTP 헤더에서 X-API-Key 값을 읽어옴
from fastapi.security import APIKeyHeader
import config

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME)

WEBAPP_KEY_NAME = "X-Webapp-Key"
webapp_key_header = APIKeyHeader(name=WEBAPP_KEY_NAME)

# verify_api_key: 요청마다 Key가 맞는지 확인하는 함수
async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
  # config.ADMIN_API_KEY: .env에 저장할 비밀 키와 비교
  if api_key != config.ADMIN_API_KEY:
    raise HTTPException(
      # HTTP_401_UNAUTHORIZED: Key가 틀리면 401 오류 반환
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="유효하지 않은 API Key입니다.",
    )
  return api_key


# verify_webapp_key: 별도 서버에 있는 웹앱만 호출할 수 있는 내부 API용 인증.
# ADMIN_API_KEY와 분리해서, 웹앱이 뚫려도 관리자 권한까지 새지 않게 함.
async def verify_webapp_key(webapp_key: str = Security(webapp_key_header)) -> str:
  if webapp_key != config.WEBAPP_API_KEY:
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="유효하지 않은 웹앱 Key입니다.",
    )
  return webapp_key