from fastapi import HTTPException, Request, status


class NotAuthenticated(HTTPException):
    """세션에 로그인된 유저가 없을 때. main.py에서 /login 리다이렉트로 변환."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")


def get_current_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user
