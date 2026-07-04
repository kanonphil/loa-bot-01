import random

_TEMPLATES = [
    "{username}님, 환영합니다!",
    "오늘도 화이팅하세요, {username}님!",
    "{username}님, 좋은 하루 보내고 계세요?",
    "다시 오셨네요, {username}님!",
    "{username}님, 무엇을 도와드릴까요?",
    "어서오세요, {username}님!",
]


def random_welcome(username: str) -> str:
    return random.choice(_TEMPLATES).format(username=username)
