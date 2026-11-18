from pathlib import Path

from fastapi.templating import Jinja2Templates

from webapp.utils import combat_power, ilvl, kst_time, time_ago

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 전역 Jinja 필터 — DB가 UTC로 저장한 시각을 화면에 그대로 찍으면 9시간 어긋난다.
#   {{ value|time_ago }}   → "13분 전" (7일 넘으면 "N일 전")
#   {{ value|kst_time }}   → "2026-11-18 14:05" (한국 시간). 형식은 {{ value|kst_time("%m/%d %H:%M") }}
# 보통 짝으로 쓴다: <time title="{{ v|kst_time }}">{{ v|time_ago }}</time>
templates.env.filters["time_ago"] = time_ago
templates.env.filters["kst_time"] = kst_time
# 숫자 표기 — 화면마다 1735.0 / 1735 / 1735.00이 섞이지 않게 한 곳에서
#   {{ c.item_level|ilvl }}  → "1735.00"     {{ c.combat_power|cp }} → "2,812.45"   (값 없으면 "—")
templates.env.filters["ilvl"] = ilvl
templates.env.filters["cp"] = combat_power
