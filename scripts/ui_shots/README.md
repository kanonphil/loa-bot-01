# UI 스크린샷 검증 도구

봇 내부 API를 스텁(`stub_bot.py`, 포트 8765)으로 띄우고 webapp(포트 8766)을 더미 OAuth 환경으로 실행한 뒤,
Starlette 세션 쿠키를 위조해 로그인 상태로 Playwright 스크린샷을 찍는다. 유닛 테스트 통과와
"실제로 그렇게 보인다"는 다른 문제라 시각 변경(CSS/레이아웃) 뒤엔 이걸로 확인한다.

```bash
pip install playwright && python -m playwright install chromium   # 최초 1회
python scripts/ui_shots/shot.py before      # → scripts/ui_shots/out/before/*.jpg (데스크톱 1280 + 모바일 390)
python scripts/ui_shots/measure.py          # 같은 줄 컨트롤 높이 차이(>2px)·늘어난 버튼 실측 보고
```

`shot.py`의 `PAGES`에 경로를 추가하면 새 화면도 찍힌다. 스텁 데이터는 `stub_bot.py`의 상수(캐릭터 3, 공대 4, 초대 1 등).
