from fastapi import Depends, HTTPException, Request, status


class NotAuthenticated(HTTPException):
    """세션에 로그인된 유저가 없을 때. main.py에서 /login 리다이렉트로 변환."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")


class NotAdmin(HTTPException):
    """로그인은 했지만 관리자가 아닐 때."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail="관리자만 접근할 수 있습니다.")


def get_current_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise NotAdmin()
    return user
