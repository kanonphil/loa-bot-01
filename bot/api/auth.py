from fastapi import Security, HTTPException, status
# APIKeyHeader: HTTP 헤더에서 X-API-Key 값을 읽어옴
from fastapi.security import APIKeyHeader
import config

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME)

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